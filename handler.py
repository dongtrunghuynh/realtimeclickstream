"""
src/stream_processor/handler.py
──────────────────────────────────────────────────────────────────────────────
Lambda entry point for the clickstream stream processor.

Flow per invocation:
  1. Receive batch of Kinesis records
  2. For each record:
     a. Base64-decode and write raw bytes to S3 (raw bucket)
     b. JSON-parse and validate against ClickstreamEvent schema
     c. Build ProcessedEvent with enrichment metadata
  3. Group validated events by event_type
  4. Write each group to its S3 partition (processed bucket)
  5. Return batchItemFailures so bad records go to DLQ without
     blocking the rest of the batch

Environment variables (injected by Terraform):
  RAW_BUCKET        — S3 bucket for raw events
  PROCESSED_BUCKET  — S3 bucket for processed NDJSON
  PROCESSED_PREFIX  — S3 key prefix (default: processed/)
  ENVIRONMENT       — dev | staging | prod
  LOG_LEVEL         — Python log level (default: INFO)
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from aws_xray_sdk.core import patch_all, xray_recorder
from pydantic import ValidationError

from .models import ClickstreamEvent, ProcessedEvent
from .transformer import write_all_groups, write_raw

# Instrument all boto3 clients for X-Ray tracing
patch_all()

# ---------------------------------------------------------------------------
# Structured logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    format=(
        '{"time":"%(asctime)s","level":"%(levelname)s",'
        '"logger":"%(name)s","message":"%(message)s"}'
    ),
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("stream_processor")
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

# ---------------------------------------------------------------------------
# Config — read once at cold start
# ---------------------------------------------------------------------------
RAW_BUCKET       = os.environ["RAW_BUCKET"]
PROCESSED_BUCKET = os.environ["PROCESSED_BUCKET"]
PROCESSED_PREFIX = os.environ.get("PROCESSED_PREFIX", "processed/")
ENVIRONMENT      = os.environ.get("ENVIRONMENT", "unknown")


# ---------------------------------------------------------------------------
# Per-record processing
# ---------------------------------------------------------------------------

def _process_record(
    record: dict[str, Any],
) -> ProcessedEvent | None:
    """
    Decode, validate, and transform a single Kinesis record.

    Returns a ProcessedEvent on success, None if the record should be
    skipped (invalid schema). Raises on unexpected errors so the caller
    can add to batchItemFailures.
    """
    kinesis_data = record["kinesis"]
    sequence     = kinesis_data["sequenceNumber"]
    raw_bytes    = base64.b64decode(kinesis_data["data"])

    # Always persist the raw event first — before any validation —
    # so we have a full replay buffer regardless of schema changes.
    write_raw(raw_bytes, sequence, RAW_BUCKET)

    payload = json.loads(raw_bytes)
    try:
        event = ClickstreamEvent.model_validate(payload)
    except ValidationError as exc:
        # Schema violation — log detail and skip, don't retry
        logger.warning(
            "Schema validation failed — skipping record",
            extra={
                "sequence":     sequence,
                "error_count":  exc.error_count(),
                "errors":       exc.errors(include_url=False),
            },
        )
        return None

    return ProcessedEvent.from_event(
        event,
        kinesis_sequence=sequence,
        environment=ENVIRONMENT,
    )


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Main Lambda handler invoked by the Kinesis event source mapping.

    Returns a dict with batchItemFailures so the ESM can selectively
    retry only failed records rather than the full batch.

    See: https://docs.aws.amazon.com/lambda/latest/dg/with-kinesis.html#services-kinesis-batchfailurereporting
    """
    records   = event.get("Records", [])
    total     = len(records)

    processed_events: list[ProcessedEvent] = []
    skipped_seqs:     list[str] = []
    failed_seqs:      list[str] = []

    logger.info(
        "Batch received",
        extra={
            "total_records": total,
            "function_name": context.function_name,
            "remaining_ms":  context.get_remaining_time_in_millis(),
        },
    )

    with xray_recorder.in_subsegment("process_records"):
        for record in records:
            seq = record["kinesis"]["sequenceNumber"]
            try:
                result = _process_record(record)
                if result is None:
                    skipped_seqs.append(seq)
                else:
                    processed_events.append(result)

            except (json.JSONDecodeError, KeyError) as exc:
                logger.error(
                    "Decode error — sending to DLQ",
                    extra={"sequence": seq, "error": str(exc)},
                )
                failed_seqs.append(seq)

            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Unexpected error processing record",
                    extra={"sequence": seq, "error": str(exc), "type": type(exc).__name__},
                )
                failed_seqs.append(seq)

    # Write all valid events to processed bucket, grouped by event_type
    if processed_events:
        with xray_recorder.in_subsegment("write_processed"):
            write_all_groups(processed_events, PROCESSED_BUCKET, PROCESSED_PREFIX)

    summary = {
        "total":     total,
        "processed": len(processed_events),
        "skipped":   len(skipped_seqs),    # invalid schema — not retried
        "failed":    len(failed_seqs),     # unexpected errors — retried via DLQ
    }

    logger.info("Batch complete", extra=summary)

    # Return partial failure report — only failed records are retried
    return {
        **summary,
        "batchItemFailures": [
            {"itemIdentifier": seq} for seq in failed_seqs
        ],
    }
