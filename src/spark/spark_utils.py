"""
Shared Spark utilities — used by session_stitcher.py and late_arrival_handler.py.

Centralises:
  - SparkSession creation with correct EMR Serverless settings
  - S3 path helpers
  - Schema constants
  - Common DataFrame transformations
"""

import logging
from datetime import datetime

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    BooleanType,
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)

logger = logging.getLogger(__name__)

# ─── Schemas ─────────────────────────────────────────────────────────────────

RAW_EVENT_SCHEMA = StructType([
    StructField("event_id",                   StringType(),  nullable=False),
    StructField("event_time",                 StringType(),  nullable=True),
    StructField("arrival_time",               StringType(),  nullable=False),
    StructField("event_type",                 StringType(),  nullable=False),
    StructField("product_id",                 StringType(),  nullable=True),
    StructField("category_id",                StringType(),  nullable=True),
    StructField("category_code",              StringType(),  nullable=True),
    StructField("brand",                      StringType(),  nullable=True),
    StructField("price",                      DoubleType(),  nullable=True),
    StructField("user_id",                    StringType(),  nullable=False),
    StructField("session_id",                 StringType(),  nullable=False),
    StructField("is_late_arrival",            BooleanType(), nullable=False),
    StructField("late_arrival_delay_seconds", LongType(),    nullable=True),
])

SESSION_TIMEOUT_MINUTES = 30

# ─── SparkSession ─────────────────────────────────────────────────────────────

def get_spark(app_name: str = "ClickstreamPipeline") -> SparkSession:
    """
    Create or retrieve a SparkSession configured for EMR Serverless.

    For local testing (pyspark installed): uses local[*] master automatically.
    For EMR Serverless: master is set by the cluster — no config needed.

    Iceberg extensions are included for future table format upgrades.
    Current pipeline uses plain Parquet — Iceberg is additive and harmless.
    """
    builder = (
        SparkSession.builder
        .appName(app_name)
        # Reduce shuffle partitions for small dev datasets — override via spark-submit
        .config("spark.sql.shuffle.partitions", "8")
        # Iceberg — optional, ready for table format upgrade in Week 5+
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config("spark.sql.catalog.glue", "org.apache.iceberg.spark.SparkCatalog")
        .config(
            "spark.sql.catalog.glue.catalog-impl",
            "org.apache.iceberg.aws.glue.GlueCatalog",
        )
        .config(
            "spark.sql.catalog.glue.io-impl",
            "org.apache.iceberg.aws.s3.S3FileIO",
        )
    )

    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    logger.info("SparkSession created: %s", app_name)
    return spark


# ─── S3 path helpers ──────────────────────────────────────────────────────────

def raw_events_path(base: str, date: str) -> str:
    """
    Build the S3 path for raw events on a given date.

    Args:
        base: Base S3 URI, e.g. 's3://clickstream-raw-123-dev/events/'
        date: Date string 'YYYY-MM-DD'

    Returns:
        Partition path covering all hours on that date.
        Spark's recursiveFileLookup reads all sub-partitions automatically.
    """
    dt = datetime.strptime(date, "%Y-%m-%d")
    return (
        f"{base.rstrip('/')}/"
        f"year={dt.year}/month={dt.month:02d}/day={dt.day:02d}/"
    )


def corrected_sessions_path(base: str, date: str) -> str:
    dt = datetime.strptime(date, "%Y-%m-%d")
    return f"{base.rstrip('/')}/year={dt.year}/month={dt.month:02d}/day={dt.day:02d}/"


def restatement_audit_path(base: str, date: str) -> str:
    dt = datetime.strptime(date, "%Y-%m-%d")
    return f"{base.rstrip('/')}-audit/year={dt.year}/month={dt.month:02d}/day={dt.day:02d}/"


# ─── DataFrame utilities ──────────────────────────────────────────────────────

def add_effective_time(df: DataFrame) -> DataFrame:
    """
    Add `effective_time` column: event_time coalesced with arrival_time.

    Lambda writes both. event_time comes from the REES46 dataset and
    represents when the user action actually occurred. For late arrivals,
    this may be many minutes before arrival_time.

    We sessionize on event_time (actual occurrence) not arrival_time (when
    Lambda saw it) to correctly reconstruct the user's journey.
    """
    return df.withColumn(
        "effective_time",
        F.coalesce(
            F.to_timestamp(F.col("event_time")),
            F.to_timestamp(F.col("arrival_time")),
        ),
    )


def filter_valid_events(df: DataFrame) -> DataFrame:
    """
    Drop rows with null user_id or session_id — these are malformed records
    that slipped past the Lambda validator. Logging the count helps diagnose
    upstream data quality issues.
    """
    total = df.count()
    valid = df.filter(
        F.col("user_id").isNotNull() & F.col("session_id").isNotNull()
    )
    dropped = total - valid.count()
    if dropped > 0:
        logger.warning("Dropped %d malformed records (null user_id or session_id)", dropped)
    return valid


def repartition_for_write(df: DataFrame, target_file_size_mb: int = 128) -> DataFrame:
    """
    Repartition before writing to S3 to avoid the small-files problem.

    Aim for ~128MB Parquet files. Too many small files slow Athena queries
    significantly. Too few large files reduce parallelism in downstream jobs.

    This is a heuristic — adjust target_file_size_mb based on your data volume.
    """
    try:
        row_count = df.count()
        # Estimate ~1KB per row (compressed Parquet, this schema)
        estimated_size_mb = row_count * 1024 / (1024 * 1024)
        n_partitions = max(1, int(estimated_size_mb / target_file_size_mb))
        logger.info(
            "Repartitioning to %d partitions (estimated %.1fMB, target %dMB/file)",
            n_partitions, estimated_size_mb, target_file_size_mb,
        )
        return df.repartition(n_partitions)
    except Exception as exc:
        logger.warning("Could not auto-repartition: %s — using default", exc)
        return df


def write_parquet(df: DataFrame, path: str, mode: str = "overwrite") -> None:
    """
    Write DataFrame to S3 as Snappy-compressed Parquet.

    Uses coalesce-before-write to avoid the small-files problem.
    mode='overwrite' is safe for idempotent daily batch jobs.
    """
    logger.info("Writing Parquet to: %s (mode=%s)", path, mode)
    (
        repartition_for_write(df)
        .write
        .mode(mode)
        .option("compression", "snappy")
        .parquet(path)
    )
    logger.info("Write complete: %s", path)
