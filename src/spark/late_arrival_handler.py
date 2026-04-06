"""
Spark Late Arrival Handler — Identifies and audits sessions restated by late events.

This job runs AFTER session_stitcher.py. It reads the restatement audit data
produced by the stitcher, enriches it with the original real-time session values
(read from the DynamoDB snapshot in S3), and writes a final audit report.

The output of this job powers the accuracy/latency dashboard.

Submit with:
    bash scripts/submit_spark_job.sh late_arrival_handler 2024-10-15
"""

import argparse
import logging
from datetime import datetime

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    ArrayType,
    BooleanType,
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)
from spark_utils import get_spark

logger = logging.getLogger(__name__)

# ─── Schemas ────────────────────────────────────────────────────────────────

# Schema for the batch-reconciled sessions (output of session_stitcher.py)
BATCH_SESSION_SCHEMA = StructType([
    StructField("batch_session_id",     StringType(),              nullable=False),
    StructField("user_id",              StringType(),              nullable=False),
    StructField("session_start",        StringType(),              nullable=True),
    StructField("session_end",          StringType(),              nullable=True),
    StructField("event_count",          LongType(),                nullable=False),
    StructField("cart_total",           DoubleType(),              nullable=True),
    StructField("conversion_value",     DoubleType(),              nullable=True),
    StructField("converted",            BooleanType(),             nullable=True),
    StructField("duration_seconds",     LongType(),                nullable=True),
    StructField("late_arrival_count",   LongType(),                nullable=False),
    StructField("had_restatement",      BooleanType(),             nullable=False),
    StructField("original_session_ids", ArrayType(StringType()),   nullable=True),
])

# Schema for the DynamoDB snapshot (speed layer snapshot written to S3)
REALTIME_SESSION_SCHEMA = StructType([
    StructField("session_id",       StringType(), nullable=False),
    StructField("event_count",      StringType(), nullable=True),   # DynamoDB exports as strings
    StructField("cart_total",       StringType(), nullable=True),
    StructField("conversion_value", StringType(), nullable=True),
    StructField("converted",        StringType(), nullable=True),
    StructField("session_start",    StringType(), nullable=True),
    StructField("last_event_time",  StringType(), nullable=True),
    StructField("duration_seconds", StringType(), nullable=True),
    StructField("date_partition",   StringType(), nullable=True),
])


# ─── Data loading ────────────────────────────────────────────────────────────

def load_batch_sessions(spark: SparkSession, s3_path: str, date: str) -> DataFrame:
    """Load batch-reconciled sessions from Parquet (written by session_stitcher.py)."""
    dt = datetime.strptime(date, "%Y-%m-%d")
    path = f"{s3_path.rstrip('/')}/year={dt.year}/month={dt.month:02d}/day={dt.day:02d}/"
    logger.info("Loading batch sessions from: %s", path)
    return spark.read.schema(BATCH_SESSION_SCHEMA).parquet(path)


def load_realtime_sessions(spark: SparkSession, s3_path: str, date: str) -> DataFrame:
    """Load speed-layer session snapshot from S3 NDJSON (written by export_dynamodb_snapshot.sh)."""
    path = f"{s3_path.rstrip('/')}/realtime-sessions/date_partition={date}/"
    logger.info("Loading real-time sessions from: %s", path)
    df = (
        spark.read
        .schema(REALTIME_SESSION_SCHEMA)
        .option("multiLine", "false")
        .json(path)
    )
    # Cast DynamoDB string numbers to proper types
    return df.withColumn("rt_event_count",      F.col("event_count").cast(LongType())) \
             .withColumn("rt_cart_total",        F.col("cart_total").cast(DoubleType())) \
             .withColumn("rt_conversion_value",  F.col("conversion_value").cast(DoubleType())) \
             .withColumn("rt_converted",         F.col("converted").cast(BooleanType())) \
             .withColumn("rt_duration_seconds",  F.col("duration_seconds").cast(LongType())) \
             .drop("event_count", "cart_total", "conversion_value", "converted", "duration_seconds")


# ─── Restatement analysis ────────────────────────────────────────────────────

def compute_session_deltas(
    batch_df: DataFrame,
    realtime_df: DataFrame,
) -> DataFrame:
    """
    Join batch-reconciled sessions with real-time speed-layer sessions.

    For each original session_id that appeared in the speed layer, we want to
    know what the batch layer says the "correct" values are. The delta between
    the two is the restatement.

    Key challenge: A batch session may stitch together multiple original session_ids
    (when late arrivals bridge a false session boundary). We explode the
    original_session_ids array to get one row per original speed-layer session.
    """
    # Explode: one row per original session_id
    batch_exploded = (
        batch_df
        .select(
            F.explode("original_session_ids").alias("session_id"),
            F.col("batch_session_id"),
            F.col("cart_total").alias("batch_cart_total"),
            F.col("conversion_value").alias("batch_conversion_value"),
            F.col("event_count").alias("batch_event_count"),
            F.col("converted").alias("batch_converted"),
            F.col("duration_seconds").alias("batch_duration_seconds"),
            F.col("late_arrival_count"),
            F.col("had_restatement"),
        )
    )

    # Join with real-time sessions on original session_id
    joined = (
        batch_exploded
        .join(realtime_df, on="session_id", how="outer")
    )

    # Compute deltas
    return (
        joined
        .withColumn(
            "cart_total_delta",
            F.round(
                F.coalesce(F.col("batch_cart_total"), F.lit(0.0)) -
                F.coalesce(F.col("rt_cart_total"), F.lit(0.0)),
                2,
            ),
        )
        .withColumn(
            "cart_total_abs_delta",
            F.abs(F.col("cart_total_delta")),
        )
        .withColumn(
            "event_count_delta",
            F.coalesce(F.col("batch_event_count"), F.lit(0)) -
            F.coalesce(F.col("rt_event_count"), F.lit(0)),
        )
        .withColumn(
            "conversion_flipped",
            F.col("batch_converted") != F.col("rt_converted"),
        )
        .withColumn(
            "restatement_type",
            F.when(F.col("session_id").isNull(), F.lit("new_in_batch"))
             .when(F.col("rt_cart_total").isNull(), F.lit("missing_in_realtime"))
             .when(F.col("cart_total_abs_delta") > 0.01, F.lit("revenue_restatement"))
             .when(F.col("event_count_delta") != 0, F.lit("event_count_restatement"))
             .when(F.col("conversion_flipped"), F.lit("conversion_flip"))
             .otherwise(F.lit("no_restatement")),
        )
    )


def compute_aggregate_stats(delta_df: DataFrame) -> DataFrame:
    """
    Aggregate session deltas to a single summary row.
    This is what the accuracy/latency dashboard displays.
    """
    return delta_df.agg(
        F.count("*").alias("total_sessions_compared"),
        F.sum(
            F.when(F.col("restatement_type") != "no_restatement", F.lit(1)).otherwise(F.lit(0))
        ).alias("sessions_restated"),
        F.avg("cart_total_abs_delta").alias("avg_revenue_discrepancy"),
        F.max("cart_total_abs_delta").alias("max_revenue_discrepancy"),
        F.sum("cart_total_abs_delta").alias("total_revenue_restated"),
        F.avg("event_count_delta").alias("avg_event_count_discrepancy"),
        F.sum(
            F.when(F.col("restatement_type") == "conversion_flip", F.lit(1)).otherwise(F.lit(0))
        ).alias("conversion_flips"),
        F.sum(
            F.when(F.col("restatement_type") == "new_in_batch", F.lit(1)).otherwise(F.lit(0))
        ).alias("new_sessions_in_batch"),
    )


def compute_restatement_type_breakdown(delta_df: DataFrame) -> DataFrame:
    """How many sessions fell into each restatement category?"""
    return (
        delta_df
        .groupBy("restatement_type")
        .agg(
            F.count("*").alias("session_count"),
            F.sum("cart_total_abs_delta").alias("total_revenue_impact"),
        )
        .orderBy(F.col("session_count").desc())
    )


# ─── Output ──────────────────────────────────────────────────────────────────

def write_restatement_detail(df: DataFrame, output_path: str, date: str) -> None:
    """Write per-session restatement detail to S3 Parquet."""
    dt = datetime.strptime(date, "%Y-%m-%d")
    path = (
        f"{output_path.rstrip('/')}/"
        f"year={dt.year}/month={dt.month:02d}/day={dt.day:02d}/"
    )
    logger.info("Writing restatement detail to: %s", path)
    df.write.mode("overwrite").parquet(path)


def write_summary_stats(df: DataFrame, output_path: str, date: str) -> None:
    """Write aggregate summary stats to S3 as a single JSON file for the dashboard."""
    dt = datetime.strptime(date, "%Y-%m-%d")
    path = (
        f"{output_path.rstrip('/')}-summary/"
        f"year={dt.year}/month={dt.month:02d}/day={dt.day:02d}/"
    )
    logger.info("Writing summary stats to: %s", path)
    df.coalesce(1).write.mode("overwrite").json(path)


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Late arrival handler — restatement audit")
    parser.add_argument("--date",           required=True, help="Processing date YYYY-MM-DD")
    parser.add_argument("--batch-path",     required=True, help="s3://bucket/corrected-sessions/")
    parser.add_argument("--realtime-path",  required=True, help="s3://bucket/ (prefix for realtime-sessions/)")
    parser.add_argument("--output-path",    required=True, help="s3://bucket/restatement-audit/")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    spark = get_spark("ClickstreamLateArrivalHandler")

    # Load both layers
    batch_df    = load_batch_sessions(spark, args.batch_path, args.date)
    realtime_df = load_realtime_sessions(spark, args.realtime_path, args.date)

    # Compute deltas
    delta_df = compute_session_deltas(batch_df, realtime_df)
    delta_df.cache()

    # Write per-session detail (for the per-session Athena view)
    write_restatement_detail(delta_df, args.output_path, args.date)

    # Write aggregate summary (for the dashboard script)
    summary_df = compute_aggregate_stats(delta_df)
    write_summary_stats(summary_df, args.output_path, args.date)

    # Log breakdown for visibility in CloudWatch
    breakdown = compute_restatement_type_breakdown(delta_df)
    logger.info("Restatement type breakdown:")
    breakdown.show(truncate=False)

    delta_df.unpersist()
    spark.stop()
    logger.info("Late arrival handler complete for date: %s", args.date)


if __name__ == "__main__":
    main()
