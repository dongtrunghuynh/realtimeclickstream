"""
Lambda Sessionizer — Kinesis event source handler.

Triggered every ~5 seconds by the Kinesis event source mapping.
Each invocation processes a batch of up to 100 records.

Design decisions:
1. Late arrivals (is_late_arrival=True) are written to S3 but NOT applied
   to DynamoDB. This keeps the speed layer fast and avoids incorrect session
   state from out-of-order events. The Spark batch job reconciles them.

2. Events within the batch are sorted by event_time before sessionization.
   Within a shard, Kinesis preserves arrival order — but event_time (from
   the original dataset) may still be slightly out of order.

3. DynamoDB writes use conditional expressions for idempotency. Kinesis
   guarantees at-least-once delivery, so Lambda may process the same record
   twice during shard re-balancing.

4. On DynamoDB write failure: log the error and continue processing the
   remaining batch. We do NOT raise — raising would cause Lambda to retry
   the entire batch, potentially causing duplicate DynamoDB writes for
   successfully processed records.
"""

import base64
import json
import logging
import os

# Shared utilities live alongside the handler in the Lambda zip.
# When deployed as a proper Lambda Layer they would come from /opt/python.
# Both paths work: zip-bundled (this project) and Layer-based (production upgrade).
import sys
import time
from datetime import UTC, datetime

from cart_calculator import CartCalculator
from session_state import SessionState

if "/opt/python" not in sys.path:
    sys.path.insert(0, "/opt/python")

from dynamodb_client import DynamoDBClient
from utils import build_log_context, write_events_to_s3

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Module-level singletons — reused across Lambda invocations in the same container
_dynamodb = DynamoDBClient(
    table_name=os.environ["DYNAMODB_TABLE_NAME"],
    region=os.environ.get("AWS_REGION", "us-east-1"),
)
_session_logic = SessionState()
_cart_calculator = CartCalculator()
_s3_bucket = os.environ["S3_BUCKET"]


def lambda_handler(event: dict, context) -> dict:
    """
    Entry point for Kinesis trigger.

    event["Records"] contains up to 100 Kinesis records (configured in
    Terraform event source mapping).
    """
    invocation_start = time.monotonic()
    records = event.get("Records", [])

    if not records:
        logger.info("Empty batch — nothing to process")
        return {"statusCode": 200, "processed": 0}

    logger.info("Processing batch of %d records", len(records))

    # Step 1: Decode all Kinesis records
    decoded_events = _decode_kinesis_records(records)

    # Step 2: Separate late arrivals from on-time events
    on_time_events = [e for e in decoded_events if not e.get("is_late_arrival")]
    late_events = [e for e in decoded_events if e.get("is_late_arrival")]

    # Step 3: Write ALL events to S3 (speed + batch layer raw storage)
    all_events_key = _make_s3_key(prefix="events")
    write_events_to_s3(_s3_bucket, all_events_key, decoded_events)

    # Step 4: Write late arrivals to a separate S3 prefix for Spark
    if late_events:
        late_key = _make_s3_key(prefix="late-arrivals")
        write_events_to_s3(_s3_bucket, late_key, late_events)
        logger.info("Held %d late arrivals for batch reconciliation", len(late_events))

    # Step 5: Process on-time events → DynamoDB (speed layer)
    processed = 0
    errors = 0
    for session_id, session_events in _group_by_session(on_time_events).items():
        try:
            _process_session(session_id, session_events)
            processed += 1
        except Exception as exc:
            errors += 1
            logger.error(
                "Failed to process session %s: %s — continuing",
                session_id,
                exc,
                exc_info=True,
            )

    elapsed_ms = (time.monotonic() - invocation_start) * 1000
    logger.info(
        "Batch complete | on_time=%d late=%d sessions_processed=%d errors=%d latency_ms=%.1f",
        len(on_time_events),
        len(late_events),
        processed,
        errors,
        elapsed_ms,
    )

    return {
        "statusCode": 200,
        "processed_sessions": processed,
        "late_arrivals": len(late_events),
        "errors": errors,
    }


def _decode_kinesis_records(records: list[dict]) -> list[dict]:
    """Base64-decode Kinesis records and parse JSON payloads."""
    events = []
    for record in records:
        try:
            payload = base64.b64decode(record["kinesis"]["data"]).decode("utf-8")
            event = json.loads(payload)
            # Attach Kinesis metadata for ordering / debugging
            event["_kinesis_sequence"] = record["kinesis"]["sequenceNumber"]
            event["_kinesis_arrival"] = record["kinesis"]["approximateArrivalTimestamp"]
            events.append(event)
        except (KeyError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Skipping malformed Kinesis record: %s", exc)
    return events


def _group_by_session(events: list[dict]) -> dict[str, list[dict]]:
    """
    Group events by session_id and sort each group by event_time.
    Falls back to _kinesis_arrival if event_time is missing.
    """
    groups: dict[str, list[dict]] = {}
    for event in events:
        sid = event.get("session_id", "unknown")
        groups.setdefault(sid, []).append(event)

    for sid in groups:
        groups[sid].sort(
            # Always produce a str so mixed event_time/float _kinesis_arrival values
            # compare cleanly. Kinesis arrival is a float epoch — convert to str.
            key=lambda e: str(e.get("event_time") or e.get("_kinesis_arrival", ""))
        )

    return groups


def _process_session(session_id: str, events: list[dict]) -> None:
    """
    Load current session state from DynamoDB, apply new events, write back.
    """
    current_state = _dynamodb.get_session(session_id) or {}

    for event in events:
        # Check if this is a new session (30-min inactivity boundary)
        if _session_logic.is_new_session(
            last_event_time=current_state.get("last_event_time"),
            current_event_time=event.get("event_time"),
        ):
            # New session detected — persist the old one if it exists
            if current_state:
                _dynamodb.put_session(session_id, {**current_state, "status": "closed"})
            current_state = {}

        # Apply event to session state
        current_state = _session_logic.update(current_state, event)

    # Compute cart total
    current_state["cart_total"] = _cart_calculator.compute(events)

    # Write updated state to DynamoDB with 2-hour TTL
    _dynamodb.put_session(session_id, current_state, ttl_hours=2)

    ctx = build_log_context(session_id, current_state)
    logger.debug("Session updated: %s", ctx)


def _make_s3_key(prefix: str) -> str:
    """Generate a partitioned S3 key: prefix/year=Y/month=M/day=D/hour=H/."""
    now = datetime.now(tz=UTC)
    return (
        f"{prefix}/"
        f"year={now.year}/month={now.month:02d}/"
        f"day={now.day:02d}/hour={now.hour:02d}/"
    )
