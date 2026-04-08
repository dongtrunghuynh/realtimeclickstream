"""
Shared utilities for Lambda functions — S3 writing and log helpers.

Week 3 default: NDJSON (no extra dependencies, works out of the box).
Week 4 upgrade: switch fmt="parquet" to use pyarrow (bundled in Lambda zip).
"""

import io
import json
import logging
from datetime import UTC, datetime

import boto3

logger    = logging.getLogger(__name__)
_s3       = boto3.client("s3")


def write_events_to_s3(
    bucket: str,
    key_prefix: str,
    events: list[dict],
    fmt: str = "ndjson",
) -> str:
    """
    Write event dicts to S3 as NDJSON or Parquet.

    Args:
        bucket:     Target S3 bucket
        key_prefix: Key prefix ending with '/' — e.g. 'events/year=2024/month=10/day=15/hour=09/'
        events:     List of event dicts
        fmt:        'ndjson' (default) or 'parquet' (Week 4 upgrade)

    Returns:
        Full S3 key written, or '' if events is empty.
    """
    if not events:
        return ""
    if fmt == "parquet":
        return _write_parquet(bucket, key_prefix, events)
    return _write_ndjson(bucket, key_prefix, events)


def build_log_context(session_id: str, state: dict) -> str:
    """Return a compact structured string for CloudWatch log filtering."""
    return (
        f"session_id={session_id} "
        f"event_count={state.get('event_count', 0)} "
        f"cart_total={float(state.get('cart_total', 0)):.2f} "
        f"converted={state.get('converted', False)} "
        f"last_event={state.get('last_event_time', 'unknown')}"
    )


# ─── Private writers ─────────────────────────────────────────────────────────

def _write_ndjson(bucket: str, key_prefix: str, events: list[dict]) -> str:
    now      = datetime.now(tz=UTC)
    filename = f"{now.strftime('%Y%m%dT%H%M%S')}_{len(events)}.ndjson"
    key      = f"{key_prefix}{filename}"
    body     = "\n".join(json.dumps(e, default=str) for e in events)

    _s3.put_object(
        Bucket      = bucket,
        Key         = key,
        Body        = body.encode("utf-8"),
        ContentType = "application/x-ndjson",
    )
    logger.debug("s3://%s/%s — %d events (NDJSON)", bucket, key, len(events))
    return key


def _write_parquet(bucket: str, key_prefix: str, events: list[dict]) -> str:
    """
    Parquet writer using pyarrow. Falls back to NDJSON if pyarrow unavailable.

    To activate for Week 4:
        1. scripts/build_lambda.sh already bundles pyarrow in the Lambda zip.
        2. Change write_events_to_s3(...) calls in handler.py to fmt="parquet".
        3. Redeploy: make deploy-lambda

    Benefits over NDJSON:
        - ~7x smaller files for this schema (many repeated string columns)
        - Athena columnar pushdown — only reads columns in SELECT/WHERE
        - Spark reads Parquet natively with full type safety
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        logger.warning("pyarrow not installed — falling back to NDJSON")
        return _write_ndjson(bucket, key_prefix, events)

    schema = pa.schema([
        pa.field("event_id",                   pa.string()),
        pa.field("event_time",                 pa.string()),
        pa.field("arrival_time",               pa.string()),
        pa.field("event_type",                 pa.string()),
        pa.field("product_id",                 pa.string()),
        pa.field("category_id",                pa.string()),
        pa.field("category_code",              pa.string()),
        pa.field("brand",                      pa.string()),
        pa.field("price",                      pa.float64()),
        pa.field("user_id",                    pa.string()),
        pa.field("session_id",                 pa.string()),
        pa.field("is_late_arrival",            pa.bool_()),
        pa.field("late_arrival_delay_seconds", pa.int64()),
    ])

    def _col(key, default=None):
        return [e.get(key, default) for e in events]

    table = pa.table(
        {
            "event_id":                   _col("event_id", ""),
            "event_time":                 _col("event_time"),
            "arrival_time":               _col("arrival_time", ""),
            "event_type":                 _col("event_type", ""),
            "product_id":                 _col("product_id", ""),
            "category_id":                _col("category_id"),
            "category_code":              _col("category_code"),
            "brand":                      _col("brand"),
            "price":                      [float(e.get("price") or 0.0) for e in events],
            "user_id":                    _col("user_id", ""),
            "session_id":                 _col("session_id", ""),
            "is_late_arrival":            [bool(e.get("is_late_arrival", False)) for e in events],
            "late_arrival_delay_seconds": [
                int(v) if (v := e.get("late_arrival_delay_seconds")) is not None else None
                for e in events
            ],
        },
        schema=schema,
    )

    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    buf.seek(0)

    now      = datetime.now(tz=UTC)
    filename = f"{now.strftime('%Y%m%dT%H%M%S')}_{len(events)}.parquet"
    key      = f"{key_prefix}{filename}"

    _s3.put_object(
        Bucket      = bucket,
        Key         = key,
        Body        = buf.getvalue(),
        ContentType = "application/octet-stream",
    )
    logger.debug(
        "s3://%s/%s — %d events (Parquet, %.1fKB)",
        bucket, key, len(events), len(buf.getvalue()) / 1024,
    )
    return key
