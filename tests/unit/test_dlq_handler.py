"""Unit tests for the DLQ handler."""

import base64
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/lambda/sessionizer"))


def _make_dlq_msg(events: list[dict], msg_id: str = "msg_001") -> dict:
    """Build a DLQ SQS message containing embedded Kinesis records."""
    records = [
        {
            "kinesis": {
                "data": base64.b64encode(json.dumps(e).encode()).decode(),
                "sequenceNumber": f"seq_{i}",
            }
        }
        for i, e in enumerate(events)
    ]
    return {
        "MessageId": msg_id,
        "ReceiptHandle": f"receipt_{msg_id}",
        "Body": json.dumps({"Records": records}),
    }


def _make_event(session_id="s1"):
    return {
        "event_id": "evt_001",
        "session_id": session_id,
        "user_id": "u1",
        "event_type": "view",
        "is_late_arrival": False,
    }


class TestDLQHandler:

    def _handler(self):
        with patch("dlq_handler.boto3.client"):
            from dlq_handler import DLQHandler
            return DLQHandler("https://sqs.us-east-1.amazonaws.com/123/test-dlq", "test-stream", "us-east-1")

    def test_parse_valid_embedded_records(self):
        h = self._handler()
        msg = _make_dlq_msg([_make_event("s1"), _make_event("s2")])
        result = h._parse_dlq_message(msg)
        assert len(result) == 2
        assert result[0]["session_id"] == "s1"
        assert result[1]["session_id"] == "s2"

    def test_parse_malformed_body_returns_empty(self):
        h = self._handler()
        msg = {"MessageId": "bad", "ReceiptHandle": "r", "Body": "NOT JSON {{{"}
        result = h._parse_dlq_message(msg)
        assert result == []

    def test_parse_malformed_kinesis_data_skipped(self):
        h = self._handler()
        msg = {
            "MessageId": "m1",
            "ReceiptHandle": "r",
            "Body": json.dumps({
                "Records": [
                    {"kinesis": {"data": "NOT_VALID_BASE64!!!!!!"}},
                    {"kinesis": {"data": base64.b64encode(json.dumps(_make_event()).encode()).decode()}},
                ]
            }),
        }
        result = h._parse_dlq_message(msg)
        # Second record should parse; first should be skipped
        assert len(result) == 1

    @patch("dlq_handler.boto3.client")
    def test_reprocess_dry_run_does_not_call_kinesis(self, mock_boto3):
        mock_sqs     = MagicMock()
        mock_kinesis = MagicMock()
        mock_boto3.side_effect = lambda svc, **kw: mock_sqs if svc == "sqs" else mock_kinesis

        from dlq_handler import DLQHandler
        h = DLQHandler("https://sqs.us-east-1.amazonaws.com/123/q", "stream", "us-east-1")

        mock_sqs.receive_message.return_value = {
            "Messages": [_make_dlq_msg([_make_event()])]
        }

        result = h.reprocess(dry_run=True)

        mock_kinesis.put_records.assert_not_called()
        mock_sqs.delete_message.assert_not_called()
        assert result["replayed"] == 1
        assert result["deleted"] == 0

    @patch("dlq_handler.boto3.client")
    def test_reprocess_live_publishes_and_deletes(self, mock_boto3):
        mock_sqs     = MagicMock()
        mock_kinesis = MagicMock()
        mock_boto3.side_effect = lambda svc, **kw: mock_sqs if svc == "sqs" else mock_kinesis

        from dlq_handler import DLQHandler
        h = DLQHandler("https://sqs.us-east-1.amazonaws.com/123/q", "stream", "us-east-1")

        mock_sqs.receive_message.return_value = {
            "Messages": [_make_dlq_msg([_make_event("s1"), _make_event("s2")])]
        }
        mock_kinesis.put_records.return_value = {
            "FailedRecordCount": 0,
            "Records": [{"SequenceNumber": "1"}, {"SequenceNumber": "2"}],
        }

        result = h.reprocess(dry_run=False)

        mock_kinesis.put_records.assert_called_once()
        mock_sqs.delete_message.assert_called_once()
        assert result["replayed"] == 2
        assert result["deleted"] == 1

    @patch("dlq_handler.boto3.client")
    def test_empty_queue_returns_zero_counts(self, mock_boto3):
        mock_sqs = MagicMock()
        mock_boto3.return_value = mock_sqs
        mock_sqs.receive_message.return_value = {"Messages": []}

        from dlq_handler import DLQHandler
        h = DLQHandler("https://sqs.us-east-1.amazonaws.com/123/q", "stream", "us-east-1")
        result = h.reprocess(dry_run=False)
        assert result == {"replayed": 0, "skipped": 0, "deleted": 0}
