"""
Spark Batch Reconciler — Nightly session stitching with late-arrival handling.

This job runs on EMR Serverless and produces the "correct" view of sessions
by re-processing all events (including late arrivals) from S3.

Submitting this job:
    bash scripts/submit_spark_job.sh session_stitcher

Why this is necessary:
    The Lambda speed layer processes events as they arrive. Late-arriving events
    (is_late_arrival=True) are skipped by Lambda — they go to S3 but not DynamoDB.
    This Spark job reads ALL events (on-time + late arrivals) and recomputes
    sessions from scratch, producing corrected session metrics.

    The comparison between DynamoDB (speed) and Athena/S3 (batch) outputs is
    the core deliverable of this project — the accuracy/latency tradeoff dashboard.
"""

import logging
from datetime import datetime

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window
from spark_utils import (
    RAW_EVENT_SCHEMA,
    SESSION_TIMEOUT_MINUTES,
    get_spark,
    raw_events_path,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

# Schemas and constants imported from spark_utils


# SparkSession creation is handled by spark_utils.get_spark() for consistency.


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_raw_events(spark: SparkSession, s3_path: str, date: str) -> DataFrame:
    """
    Load raw events from S3 for a given date partition (YYYY-MM-DD).
    Reads both on-time events and late arrivals.

    Args:
        s3_path: Base S3 path, e.g. s3://clickstream-raw-123456-dev/events/
        date:    Date string YYYY-MM-DD — loads year/month/day partition
    """
    partition_path = raw_events_path(s3_path, date)
    logger.info("Loading raw events from: %s", partition_path)
    df = (
        spark.read
        .schema(RAW_EVENT_SCHEMA)
        .option("recursiveFileLookup", "true")
        .json(partition_path)   # NDJSON — use .parquet() after Week 4 format upgrade
    )

    event_count = df.count()
    logger.info("Loaded %d raw events", event_count)
    return df


# ---------------------------------------------------------------------------
# Sessionization
# ---------------------------------------------------------------------------

def sessionize(df: DataFrame) -> DataFrame:
    """
    Re-sessionize all events using a 30-minute inactivity window.

    Algorithm:
    1. Sort events by user_id and event_time
    2. Compute the gap between each event and the previous event for the same user
    3. Mark a new session when gap > 30 minutes
    4. Assign a session sequence number per user
    5. Aggregate events into session-level metrics

    Note: We use user_id for sessionization (not the original session_id from
    the dataset). This is because late-arriving events may span the original
    session boundary, requiring session stitching across session_ids.
    """
    # Step 1: Parse event_time, fall back to arrival_time if null
    df = df.withColumn(
        "effective_time",
        F.coalesce(
            F.to_timestamp("event_time"),
            F.to_timestamp("arrival_time"),
        )
    )

    # Step 2: Compute lag (previous event time per user)
    user_window = Window.partitionBy("user_id").orderBy("effective_time")
    df = df.withColumn(
        "prev_event_time",
        F.lag("effective_time").over(user_window)
    )

    # Step 3: Mark session boundaries (gap > 30 min OR first event)
    df = df.withColumn(
        "is_session_start",
        F.when(
            F.col("prev_event_time").isNull() |
            (
                (F.col("effective_time").cast("long") - F.col("prev_event_time").cast("long"))
                > SESSION_TIMEOUT_MINUTES * 60
            ),
            F.lit(1)
        ).otherwise(F.lit(0))
    )

    # Step 4: Assign cumulative session counter per user
    df = df.withColumn(
        "user_session_seq",
        F.sum("is_session_start").over(user_window)
    )

    # Step 5: Create a stable batch_session_id from user + sequence
    df = df.withColumn(
        "batch_session_id",
        F.concat_ws("_", F.col("user_id"), F.col("user_session_seq").cast("string"))
    )

    return df


def aggregate_sessions(df: DataFrame) -> DataFrame:
    """
    Aggregate event-level data to session-level metrics.

    Output schema per session:
    - batch_session_id, user_id, session_start, session_end
    - event_count, cart_total, conversion_value
    - converted (bool), duration_seconds
    - late_arrival_count, had_restatement (bool)
    - original_session_ids (array of user_session values)
    """
    return df.groupBy("batch_session_id", "user_id").agg(
        F.min("effective_time").alias("session_start"),
        F.max("effective_time").alias("session_end"),
        F.count("*").alias("event_count"),
        F.sum(
            F.when(F.col("event_type") == "cart", F.col("price")).otherwise(F.lit(0.0))
        ).alias("cart_total"),
        F.sum(
            F.when(F.col("event_type") == "purchase", F.col("price")).otherwise(F.lit(0.0))
        ).alias("conversion_value"),
        F.max(
            F.when(F.col("event_type") == "purchase", F.lit(True)).otherwise(F.lit(False))
        ).alias("converted"),
        F.sum(F.col("is_late_arrival").cast("int")).alias("late_arrival_count"),
        F.collect_set("session_id").alias("original_session_ids"),
    ).withColumn(
        "duration_seconds",
        F.col("session_end").cast("long") - F.col("session_start").cast("long")
    ).withColumn(
        "had_restatement",
        F.col("late_arrival_count") > 0
    ).withColumn(
        "session_date",
        F.to_date(F.col("session_start"))
    )


# ---------------------------------------------------------------------------
# Late arrival audit
# ---------------------------------------------------------------------------

def compute_restatement_audit(
    realtime_sessions: DataFrame,
    batch_sessions: DataFrame,
) -> DataFrame:
    """
    Join real-time (speed layer) sessions with batch-reconciled sessions.
    Computes restatement metrics for the accuracy/latency dashboard.

    This is the core deliverable — quantifying the tradeoff.

    Args:
        realtime_sessions: Sessions from DynamoDB export (speed layer)
        batch_sessions:    Sessions from this Spark job (batch layer)

    Returns:
        DataFrame with one row per original session_id, showing:
        - revenue discrepancy
        - event count discrepancy
        - whether the session required restatement
    """
    realtime_renamed = realtime_sessions.select(
        F.col("session_id"),
        F.col("cart_total").alias("rt_cart_total"),
        F.col("event_count").alias("rt_event_count"),
        F.col("converted").alias("rt_converted"),
    )

    batch_exploded = batch_sessions.select(
        F.explode("original_session_ids").alias("session_id"),
        F.col("cart_total").alias("batch_cart_total"),
        F.col("event_count").alias("batch_event_count"),
        F.col("converted").alias("batch_converted"),
        F.col("had_restatement"),
    )

    return realtime_renamed.join(batch_exploded, on="session_id", how="outer").withColumn(
        "revenue_discrepancy",
        F.abs(F.coalesce(F.col("batch_cart_total"), F.lit(0.0)) -
              F.coalesce(F.col("rt_cart_total"), F.lit(0.0)))
    ).withColumn(
        "event_count_discrepancy",
        F.abs(F.coalesce(F.col("batch_event_count"), F.lit(0)) -
              F.coalesce(F.col("rt_event_count"), F.lit(0)))
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_sessions(df: DataFrame, output_path: str, date: str) -> None:
    """
    Write reconciled sessions to S3 as Parquet, partitioned by date.

    Partition by day so Athena partition pruning works correctly.
    """
    dt = datetime.strptime(date, "%Y-%m-%d")
    output = (
        f"{output_path.rstrip('/')}/"
        f"year={dt.year}/month={dt.month:02d}/day={dt.day:02d}/"
    )

    logger.info("Writing reconciled sessions to: %s", output)

    (
        df.write
        .mode("overwrite")
        .parquet(output)
    )

    logger.info("Write complete")


def write_restatement_audit(df: DataFrame, output_path: str, date: str) -> None:
    """Write restatement audit records alongside the corrected sessions."""
    dt = datetime.strptime(date, "%Y-%m-%d")
    output = (
        f"{output_path.rstrip('/')}-audit/"
        f"year={dt.year}/month={dt.month:02d}/day={dt.day:02d}/"
    )
    df.write.mode("overwrite").parquet(output)
    logger.info("Restatement audit written to: %s", output)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Clickstream batch reconciler")
    parser.add_argument("--date", required=True, help="Processing date YYYY-MM-DD")
    parser.add_argument("--raw-path", required=True, help="s3://bucket/events/")
    parser.add_argument("--output-path", required=True, help="s3://bucket/corrected-sessions/")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    spark = get_spark("ClickstreamBatchReconciler")

    # Load
    raw_df = load_raw_events(spark, args.raw_path, args.date)

    # Sessionize
    with_sessions = sessionize(raw_df)

    # Aggregate
    session_df = aggregate_sessions(with_sessions)

    # Write corrected sessions
    write_sessions(session_df, args.output_path, args.date)

    logger.info("Batch reconciler complete for date: %s", args.date)
    spark.stop()


if __name__ == "__main__":
    main()
