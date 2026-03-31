"""
src/stream_processor/transformer.py
──────────────────────────────────────────────────────────────────────────────
Stateless transformation and enrichment functions.

Separated from handler.py so each concern is independently testable.

Responsibilities:
  - Build S3 keys (Hive-partitioned)
  - Serialise batches to NDJSON
  - Write raw + processed records to S3
  - Emit structured log lines
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import boto3
from aws_xray_sdk.core import xray_recorder

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

from .models import ClickstreamEvent, ProcessedEvent

logger = logging.getLogger(__name__)

# Module-level S3 client — reused across Lambda invocations (warm starts)
_s3: S3Client = boto3.client("s3")  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# S3 key helpers
# ---------------------------------------------------------------------------

def raw_s3_key(kinesis_sequence: str) -> str:
    """
    Raw events land in a flat prefix keyed by sequence number.
    No partitioning — raw bucket is replay storage, not query storage.

    Pattern: raw/<sequence>/<uuid>.json
    """
    return f"raw/{kinesis_sequence}/{uuid.uuid4()}.json"


def processed_s3_key(event_type: str, ts: datetime, prefix: str = "processed/") -> str:
    """
    Hive-compatible partition key for the processed bucket.

    Pattern: processed/event_type=<type>/year=<Y>/month=<M>/day=<D>/<uuid>.ndjson

    Using event timestamp (not processing time) so Athena partition
    pruning aligns with when events actually happened.
    """
    return (
        f"{prefix.rstrip('/')}/"
        f"event_type={event_type}/"
        f"year={ts.year:04d}/"
        f"month={ts.month:02d}/"
        f"day={ts.day:02d}/"
        f"{uuid.uuid4()}.ndjson"
    )


# ---------------------------------------------------------------------------
# S3 writers
# ---------------------------------------------------------------------------

@xray_recorder.capture("write_raw_to_s3")
def write_raw(
    raw_payload: bytes,
    kinesis_sequence: str,
    bucket: str,
) -> str:
    """Write a single raw (unvalidated) Kinesis record to the raw bucket."""
    key = raw_s3_key(kinesis_sequence)

    _s3.put_object(
        Bucket      = bucket,
        Key         = key,
        Body        = raw_payload,
        ContentType = "application/json",
        Metadata    = {"kinesis-sequence": kinesis_sequence},
    )

    logger.info(
        "Wrote raw record",
        extra={"s3_bucket": bucket, "s3_key": key, "bytes": len(raw_payload)},
    )
    return key


@xray_recorder.capture("write_processed_batch_to_s3")
def write_processed_batch(
    events: list[ProcessedEvent],
    bucket: str,
    prefix: str,
) -> str | None:
    """
    Serialise a batch of ProcessedEvents as NDJSON and write to S3.

    All events in a batch share the same event_type and date partition —
    batching is done in the handler before calling this function.

    Returns the S3 key written, or None if the batch was empty.
    """
    if not events:
        return None

    # Use the first event's type and timestamp for the partition key
    first = events[0]
    ts    = datetime.fromisoformat(first.timestamp)
    key   = processed_s3_key(first.partition_event_type, ts, prefix)

    body = "\n".join(
        e.model_dump_json(exclude_none=True) for e in events
    ).encode("utf-8")

    _s3.put_object(
        Bucket      = bucket,
        Key         = key,
        Body        = body,
        ContentType = "application/x-ndjson",
        Metadata    = {
            "record-count": str(len(events)),
            "event-type":   first.partition_event_type,
            "environment":  first.environment,
        },
    )

    logger.info(
        "Wrote processed batch",
        extra={
            "s3_bucket":    bucket,
            "s3_key":       key,
            "record_count": len(events),
            "event_type":   first.partition_event_type,
            "bytes":        len(body),
        },
    )
    return key


# ---------------------------------------------------------------------------
# Batch grouping
# ---------------------------------------------------------------------------

def group_by_event_type(
    events: list[ProcessedEvent],
) -> dict[str, list[ProcessedEvent]]:
    """
    Group processed events by event_type so each S3 write lands in the
    correct Hive partition.

    Returns a dict of {event_type: [ProcessedEvent, ...]}
    """
    groups: dict[str, list[ProcessedEvent]] = {}
    for event in events:
        groups.setdefault(event.partition_event_type, []).append(event)
    return groups


def write_all_groups(
    events: list[ProcessedEvent],
    bucket: str,
    prefix: str,
) -> list[str]:
    """
    Group events by type and write each group to its correct S3 partition.
    Returns list of S3 keys written.
    """
    groups = group_by_event_type(events)
    keys: list[str] = []

    for event_type, group in groups.items():
        key = write_processed_batch(group, bucket, prefix)
        if key:
            keys.append(key)
            logger.info(
                "Partition written",
                extra={"event_type": event_type, "count": len(group), "s3_key": key},
            )

    return keys
