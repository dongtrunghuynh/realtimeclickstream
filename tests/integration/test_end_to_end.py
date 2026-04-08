"""
Integration tests — hit real AWS services in the dev workspace.

Prerequisites:
    terraform workspace select dev
    terraform apply -var-file=environments/dev.tfvars
    export KINESIS_STREAM_NAME, DYNAMODB_TABLE_NAME, S3_BUCKET, AWS_REGION

Run:
    pytest tests/integration/ -v -m integration

Skip in CI (CI runs unit tests only):
    pytest tests/unit/ -v   (default per pytest.ini)
"""

import json
import os
import time
import uuid
from datetime import UTC, datetime, timezone

import boto3
import pytest

# ─── Fixtures ────────────────────────────────────────────────────────────────

# Fixtures (kinesis_client, dynamodb_table, s3_client, kinesis_stream_name,
# dynamodb_table_name, s3_bucket) are provided by tests/integration/conftest.py.
# Renamed here for backwards compat with the test bodies below.

@pytest.fixture(scope="module")
def kinesis(kinesis_client):
    return kinesis_client

@pytest.fixture(scope="module")
def dynamodb(dynamodb_table):
    return dynamodb_table

@pytest.fixture(scope="module")
def s3(s3_client):
    return s3_client


def _make_event(session_id, event_type="view", price=0.0, is_late=False) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_time": datetime.now(tz=UTC).isoformat(),
        "arrival_time": datetime.now(tz=UTC).isoformat(),
        "event_type": event_type,
        "product_id": "p_test_001",
        "category_id": "999",
        "category_code": "electronics.test",
        "brand": "testbrand",
        "price": price,
        "user_id": f"integration_test_user_{session_id}",
        "session_id": session_id,
        "is_late_arrival": is_late,
        "late_arrival_delay_seconds": 300 if is_late else None,
    }


def _poll_dynamodb(dynamodb, session_id, max_wait=30, interval=3):
    """Poll DynamoDB until session_id appears or timeout."""
    for _ in range(max_wait // interval):
        time.sleep(interval)
        response = dynamodb.get_item(Key={"session_id": session_id})
        if "Item" in response:
            return response["Item"]
    return None


# ─── Tests ───────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestKinesisToLambdaToDynamoDB:
    """End-to-end: event → Kinesis → Lambda → DynamoDB."""

    def test_on_time_event_appears_in_dynamodb(self, kinesis, dynamodb):
        stream     = kinesis_stream_name
        session_id = f"it_view_{uuid.uuid4().hex[:8]}"
        event      = _make_event(session_id, "view")

        kinesis.put_record(
            StreamName=stream,
            Data=json.dumps(event).encode(),
            PartitionKey=event["user_id"],
        )

        item = _poll_dynamodb(dynamodb, session_id)
        assert item is not None, f"Session {session_id} not found in DynamoDB after 30s"
        assert int(item["event_count"]["N"]) >= 1

    def test_cart_total_accumulates(self, kinesis, dynamodb):
        stream     = kinesis_stream_name
        session_id = f"it_cart_{uuid.uuid4().hex[:8]}"
        events = [
            _make_event(session_id, "view",  price=0.0),
            _make_event(session_id, "cart",  price=29.99),
            _make_event(session_id, "cart",  price=49.99),
        ]

        kinesis.put_records(
            StreamName=stream,
            Records=[{"Data": json.dumps(e).encode(), "PartitionKey": e["user_id"]} for e in events],
        )

        time.sleep(15)
        item = _poll_dynamodb(dynamodb, session_id, max_wait=15)
        assert item is not None, f"Session {session_id} not in DynamoDB"
        cart_total = float(item.get("cart_total", {}).get("N", 0))
        assert cart_total == pytest.approx(79.98, rel=0.01)

    def test_purchase_sets_converted_true(self, kinesis, dynamodb):
        stream     = kinesis_stream_name
        session_id = f"it_purchase_{uuid.uuid4().hex[:8]}"
        events = [
            _make_event(session_id, "cart",     price=49.99),
            _make_event(session_id, "purchase", price=49.99),
        ]

        kinesis.put_records(
            StreamName=stream,
            Records=[{"Data": json.dumps(e).encode(), "PartitionKey": e["user_id"]} for e in events],
        )

        time.sleep(15)
        item = _poll_dynamodb(dynamodb, session_id, max_wait=15)
        assert item is not None
        assert item.get("converted", {}).get("BOOL") is True


@pytest.mark.integration
class TestLateArrivalRouting:
    """Late arrivals → S3 only, NOT DynamoDB."""

    def test_late_arrival_not_in_dynamodb(self, kinesis, dynamodb, s3):
        stream     = kinesis_stream_name
        bucket     = s3_bucket
        session_id = f"it_late_{uuid.uuid4().hex[:8]}"
        event      = _make_event(session_id, "cart", price=29.99, is_late=True)

        kinesis.put_record(
            StreamName=stream,
            Data=json.dumps(event).encode(),
            PartitionKey=event["user_id"],
        )

        time.sleep(15)

        # Must NOT be in DynamoDB
        response = dynamodb.get_item(Key={"session_id": session_id})
        assert "Item" not in response, (
            f"Late arrival session {session_id} should NOT be in DynamoDB"
        )

        # Must be in S3 late-arrivals prefix
        now    = datetime.now(tz=UTC)
        prefix = f"late-arrivals/year={now.year}/month={now.month:02d}/day={now.day:02d}/"
        objs   = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        assert objs.get("KeyCount", 0) > 0, (
            f"Expected late arrival files in s3://{bucket}/{prefix}"
        )

    def test_mixed_batch_only_on_time_in_dynamodb(self, kinesis, dynamodb):
        stream     = kinesis_stream_name
        session_id = f"it_mixed_{uuid.uuid4().hex[:8]}"
        events = [
            _make_event(session_id, "view", price=0.0,   is_late=False),
            _make_event(session_id, "cart", price=49.99, is_late=True),
        ]

        kinesis.put_records(
            StreamName=stream,
            Records=[{"Data": json.dumps(e).encode(), "PartitionKey": e["user_id"]} for e in events],
        )

        time.sleep(15)
        item = _poll_dynamodb(dynamodb, session_id, max_wait=15)
        assert item is not None
        # Only 1 on-time event should be in DynamoDB
        assert int(item["event_count"]["N"]) == 1, (
            "Only the on-time view event should be in DynamoDB"
        )


@pytest.mark.integration
class TestS3RawEvents:
    """Every event (on-time + late) must land in S3 raw prefix."""

    def test_all_events_written_to_s3(self, kinesis, s3):
        stream     = kinesis_stream_name
        bucket     = s3_bucket
        session_id = f"it_s3_{uuid.uuid4().hex[:8]}"
        event      = _make_event(session_id, "view")

        kinesis.put_record(
            StreamName=stream,
            Data=json.dumps(event).encode(),
            PartitionKey=event["user_id"],
        )

        time.sleep(15)

        now    = datetime.now(tz=UTC)
        prefix = f"events/year={now.year}/month={now.month:02d}/day={now.day:02d}/"
        objs   = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        assert objs.get("KeyCount", 0) > 0, (
            f"Expected raw event files in s3://{bucket}/{prefix}"
        )
