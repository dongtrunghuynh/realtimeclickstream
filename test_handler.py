"""
tests/unit/test_handler.py
──────────────────────────────────────────────────────────────────────────────
Tests for the Lambda handler (handler.py).
All AWS calls are mocked — no real infrastructure needed.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Set env vars BEFORE importing the module
os.environ.update({
    "RAW_BUCKET":       "test-raw-bucket",
    "PROCESSED_BUCKET": "test-processed-bucket",
    "PROCESSED_PREFIX": "processed/",
    "ENVIRONMENT":      "test",
    "AWS_DEFAULT_REGION": "ap-southeast-2",
    "AWS_XRAY_SDK_ENABLED": "false",
})

from src.stream_processor.handler import lambda_handler  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _encode(payload: dict) -> str:
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _make_record(payload: dict, seq: str = "seq-001") -> dict:
    return {
        "kinesis": {
            "sequenceNumber": seq,
            "partitionKey":   "pk-1",
            "data":           _encode(payload),
        }
    }


def _make_event(payloads: list[dict]) -> dict:
    return {
        "Records": [
            _make_record(p, f"seq-{i:03d}")
            for i, p in enumerate(payloads)
        ]
    }


VALID_PAYLOAD = {
    "event_id":   str(uuid.uuid4()),
    "event_type": "page_view",
    "session_id": str(uuid.uuid4()),
    "user_id":    "user-test",
    "timestamp":  "2025-06-14T10:00:00Z",
    "page":       {"url": "https://example.com/home"},
}

_CTX = MagicMock(
    function_name="clickstream-test-stream-processor",
    get_remaining_time_in_millis=lambda: 55000,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLambdaHandlerHappyPath:
    @patch("src.stream_processor.transformer._s3")
    def test_processes_valid_single_record(self, mock_s3: MagicMock):
        result = lambda_handler(_make_event([VALID_PAYLOAD]), _CTX)

        assert result["total"]     == 1
        assert result["processed"] == 1
        assert result["skipped"]   == 0
        assert result["failed"]    == 0
        assert result["batchItemFailures"] == []

    @patch("src.stream_processor.transformer._s3")
    def test_writes_raw_and_processed_for_each_record(self, mock_s3: MagicMock):
        lambda_handler(_make_event([VALID_PAYLOAD, VALID_PAYLOAD]), _CTX)
        # 2 raw writes + 1 processed write (grouped into one)
        assert mock_s3.put_object.call_count == 3

    @patch("src.stream_processor.transformer._s3")
    def test_empty_batch_returns_zeros(self, mock_s3: MagicMock):
        result = lambda_handler({"Records": []}, _CTX)
        assert result["total"]   == 0
        assert result["processed"] == 0
        mock_s3.put_object.assert_not_called()

    @patch("src.stream_processor.transformer._s3")
    def test_mixed_event_types_grouped_separately(self, mock_s3: MagicMock):
        import uuid as _uuid
        payloads = [
            {**VALID_PAYLOAD, "event_id": str(_uuid.uuid4()), "event_type": "page_view"},
            {**VALID_PAYLOAD, "event_id": str(_uuid.uuid4()), "event_type": "click"},
        ]
        result = lambda_handler(_make_event(payloads), _CTX)
        assert result["processed"] == 2
        # 2 raw + 2 processed (different event_type partitions)
        assert mock_s3.put_object.call_count == 4


class TestLambdaHandlerSchemaViolations:
    @patch("src.stream_processor.transformer._s3")
    def test_invalid_schema_skipped_not_failed(self, mock_s3: MagicMock):
        bad = {"wrong": "schema", "no_required_fields": True}
        result = lambda_handler(_make_event([bad]), _CTX)

        assert result["skipped"]            == 1
        assert result["failed"]             == 0
        assert result["batchItemFailures"]  == []

    @patch("src.stream_processor.transformer._s3")
    def test_invalid_event_type_skipped(self, mock_s3: MagicMock):
        bad = {**VALID_PAYLOAD, "event_type": "not_real"}
        result = lambda_handler(_make_event([bad]), _CTX)
        assert result["skipped"] == 1

    @patch("src.stream_processor.transformer._s3")
    def test_valid_records_still_processed_alongside_invalid(self, mock_s3: MagicMock):
        import uuid as _uuid
        bad   = {"junk": True}
        good  = {**VALID_PAYLOAD, "event_id": str(_uuid.uuid4())}
        result = lambda_handler(_make_event([bad, good]), _CTX)

        assert result["processed"] == 1
        assert result["skipped"]   == 1


class TestLambdaHandlerFailures:
    @patch("src.stream_processor.transformer._s3")
    def test_corrupt_base64_returns_batch_item_failure(self, mock_s3: MagicMock):
        bad_record = {
            "kinesis": {
                "sequenceNumber": "seq-bad",
                "partitionKey":   "pk-1",
                "data":           "%%%not_valid_base64%%%",
            }
        }
        result = lambda_handler({"Records": [bad_record]}, _CTX)

        assert result["failed"] == 1
        assert any(
            f["itemIdentifier"] == "seq-bad"
            for f in result["batchItemFailures"]
        )

    @patch("src.stream_processor.transformer._s3")
    def test_s3_error_returns_batch_item_failure(self, mock_s3: MagicMock):
        import uuid as _uuid
        mock_s3.put_object.side_effect = Exception("S3 throttled")
        payload = {**VALID_PAYLOAD, "event_id": str(_uuid.uuid4())}
        result  = lambda_handler(_make_event([payload]), _CTX)

        assert result["failed"]             == 1
        assert len(result["batchItemFailures"]) == 1

    @patch("src.stream_processor.transformer._s3")
    def test_partial_failure_does_not_block_other_records(self, mock_s3: MagicMock):
        import uuid as _uuid

        good1  = {**VALID_PAYLOAD, "event_id": str(_uuid.uuid4())}
        bad    = {"kinesis": {"sequenceNumber": "seq-bad", "partitionKey": "pk", "data": "!!!"}}
        good2  = {**VALID_PAYLOAD, "event_id": str(_uuid.uuid4())}

        result = lambda_handler({"Records": [
            _make_record(good1, "seq-000"),
            bad,
            _make_record(good2, "seq-002"),
        ]}, _CTX)

        assert result["processed"] == 2
        assert result["failed"]    == 1
