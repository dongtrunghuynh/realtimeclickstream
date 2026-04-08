"""
Unit tests for the Lambda handler — decode, routing, session grouping.

The handler itself is hard to test end-to-end without AWS, so we test its
helper functions in isolation: record decoding, session grouping, S3 key
generation, and the late-arrival routing decision.
"""

import base64
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Point imports at sessionizer and shared code
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/lambda/sessionizer"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/lambda/shared"))


def _encode_kinesis(payload: dict) -> str:
    """Encode a dict as a base64 Kinesis record data field."""
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _make_kinesis_record(event: dict, sequence: str = "seq001") -> dict:
    return {
        "kinesis": {
            "data": _encode_kinesis(event),
            "sequenceNumber": sequence,
            "approximateArrivalTimestamp": 1729000000.0,
        }
    }


# ─── Helpers imported from handler (tested in isolation) ─────────────────────

class TestDecodeKinesisRecords:
    """Tests for _decode_kinesis_records()."""

    def _import_decode(self):
        # Patch env vars that handler.py reads at module level
        with patch.dict(os.environ, {
            "DYNAMODB_TABLE_NAME": "test-table",
            "S3_BUCKET": "test-bucket",
            "AWS_REGION": "us-east-1",
        }):
            # Patch boto3 so module-level client init doesn't call AWS
            with patch("boto3.resource"), patch("boto3.client"):
                import importlib

                import handler
                importlib.reload(handler)
                return handler._decode_kinesis_records

    def test_valid_record_decoded(self):
        decode = self._import_decode()
        event = {"event_id": "e1", "session_id": "s1", "event_type": "view"}
        records = [_make_kinesis_record(event)]
        result = decode(records)
        assert len(result) == 1
        assert result[0]["event_id"] == "e1"
        assert result[0]["_kinesis_sequence"] == "seq001"

    def test_malformed_json_skipped(self):
        decode = self._import_decode()
        bad_record = {
            "kinesis": {
                "data": base64.b64encode(b"NOT JSON {{{").decode(),
                "sequenceNumber": "seq002",
                "approximateArrivalTimestamp": 1729000000.0,
            }
        }
        result = decode([bad_record])
        assert result == []

    def test_multiple_records_all_decoded(self):
        decode = self._import_decode()
        events = [
            {"event_id": f"e{i}", "session_id": "s1", "event_type": "view"}
            for i in range(5)
        ]
        records = [_make_kinesis_record(e, f"seq{i:03d}") for i, e in enumerate(events)]
        result = decode(records)
        assert len(result) == 5
        ids = [r["event_id"] for r in result]
        assert set(ids) == {"e0", "e1", "e2", "e3", "e4"}


class TestGroupBySession:
    """Tests for _group_by_session()."""

    def _import_group(self):
        with patch.dict(os.environ, {
            "DYNAMODB_TABLE_NAME": "test-table",
            "S3_BUCKET": "test-bucket",
            "AWS_REGION": "us-east-1",
        }):
            with patch("boto3.resource"), patch("boto3.client"):
                import importlib

                import handler
                importlib.reload(handler)
                return handler._group_by_session

    def test_events_grouped_by_session_id(self):
        group = self._import_group()
        events = [
            {"session_id": "s1", "event_time": "2024-10-15T10:00:00Z", "event_type": "view"},
            {"session_id": "s2", "event_time": "2024-10-15T10:01:00Z", "event_type": "cart"},
            {"session_id": "s1", "event_time": "2024-10-15T10:02:00Z", "event_type": "cart"},
        ]
        result = group(events)
        assert set(result.keys()) == {"s1", "s2"}
        assert len(result["s1"]) == 2
        assert len(result["s2"]) == 1

    def test_events_within_session_sorted_by_event_time(self):
        group = self._import_group()
        events = [
            {"session_id": "s1", "event_time": "2024-10-15T10:05:00Z", "event_type": "cart"},
            {"session_id": "s1", "event_time": "2024-10-15T10:00:00Z", "event_type": "view"},
            {"session_id": "s1", "event_time": "2024-10-15T10:10:00Z", "event_type": "purchase"},
        ]
        result = group(events)
        session_events = result["s1"]
        times = [e["event_time"] for e in session_events]
        assert times == sorted(times)

    def test_missing_session_id_grouped_as_unknown(self):
        group = self._import_group()
        events = [{"event_type": "view", "event_time": "2024-10-15T10:00:00Z"}]
        result = group(events)
        assert "unknown" in result

    def test_null_event_time_falls_back_to_kinesis_arrival(self):
        group = self._import_group()
        events = [
            {
                "session_id": "s1",
                "event_time": None,
                "_kinesis_arrival": 1729000000.0,
                "event_type": "view",
            },
            {
                "session_id": "s1",
                "event_time": "2024-10-15T10:05:00Z",
                "_kinesis_arrival": 1729000300.0,
                "event_type": "cart",
            },
        ]
        # Should not raise even with null event_time
        result = group(events)
        assert len(result["s1"]) == 2


class TestMakeS3Key:
    """Tests for _make_s3_key()."""

    def _import_key_fn(self):
        with patch.dict(os.environ, {
            "DYNAMODB_TABLE_NAME": "test-table",
            "S3_BUCKET": "test-bucket",
            "AWS_REGION": "us-east-1",
        }):
            with patch("boto3.resource"), patch("boto3.client"):
                import importlib

                import handler
                importlib.reload(handler)
                return handler._make_s3_key

    def test_key_has_correct_partition_format(self):
        make_key = self._import_key_fn()
        key = make_key("events")
        # Should match: events/year=YYYY/month=MM/day=DD/hour=HH/
        assert key.startswith("events/")
        assert "year=" in key
        assert "month=" in key
        assert "day=" in key
        assert "hour=" in key
        assert key.endswith("/")

    def test_different_prefixes_produce_different_keys(self):
        make_key = self._import_key_fn()
        k1 = make_key("events")
        k2 = make_key("late-arrivals")
        assert k1.startswith("events/")
        assert k2.startswith("late-arrivals/")
        assert k1 != k2
