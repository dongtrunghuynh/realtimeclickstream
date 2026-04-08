"""Unit tests for the event simulator components."""

import os
import sys
import time
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/event_simulator"))

from event_schema import ClickstreamEvent
from kinesis_producer import KinesisProducer
from late_arrival_injector import LateArrivalInjector

# ---------------------------------------------------------------------------
# ClickstreamEvent tests
# ---------------------------------------------------------------------------

class TestClickstreamEvent:
    """Tests for CSV parsing and event schema validation."""

    def _make_row(self, **overrides) -> pd.Series:
        defaults = {
            "event_time": "2019-10-01 00:00:00 UTC",
            "event_type": "view",
            "product_id": "12345",
            "category_id": "999",
            "category_code": "electronics.phone",
            "brand": "samsung",
            "price": 49.99,
            "user_id": "u_001",
            "user_session": "sess_abc",
        }
        defaults.update(overrides)
        return pd.Series(defaults)

    def test_valid_row_parses_correctly(self):
        row = self._make_row()
        event = ClickstreamEvent.from_csv_row(row)

        assert event is not None
        assert event.event_type == "view"
        assert event.user_id == "u_001"
        assert event.session_id == "sess_abc"
        assert event.price == 49.99
        assert event.is_late_arrival is False

    def test_all_valid_event_types_accepted(self):
        for et in ["view", "cart", "purchase"]:
            row = self._make_row(event_type=et)
            event = ClickstreamEvent.from_csv_row(row)
            assert event is not None, f"event_type '{et}' should be valid"
            assert event.event_type == et

    def test_unknown_event_type_returns_none(self):
        row = self._make_row(event_type="wishlist")
        assert ClickstreamEvent.from_csv_row(row) is None

    def test_null_category_code_allowed(self):
        row = self._make_row(category_code=None)
        event = ClickstreamEvent.from_csv_row(row)
        assert event is not None
        assert event.category_code is None

    def test_null_brand_allowed(self):
        row = self._make_row(brand=float("nan"))
        event = ClickstreamEvent.from_csv_row(row)
        assert event is not None
        assert event.brand is None

    def test_null_price_defaults_to_zero(self):
        row = self._make_row(price=float("nan"))
        event = ClickstreamEvent.from_csv_row(row)
        assert event is not None
        assert event.price == 0.0

    def test_to_dict_contains_all_required_keys(self):
        row = self._make_row()
        event = ClickstreamEvent.from_csv_row(row)
        d = event.to_dict()

        required_keys = [
            "event_id", "event_time", "arrival_time", "event_type",
            "product_id", "price", "user_id", "session_id", "is_late_arrival",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"

    def test_event_id_is_unique_per_instance(self):
        row = self._make_row()
        e1 = ClickstreamEvent.from_csv_row(row)
        e2 = ClickstreamEvent.from_csv_row(row)
        assert e1.event_id != e2.event_id

    def test_missing_required_field_returns_none(self):
        row = self._make_row()
        row = row.drop("user_id")
        # Should not raise — returns None gracefully
        result = ClickstreamEvent.from_csv_row(row)
        assert result is None


# ---------------------------------------------------------------------------
# LateArrivalInjector tests
# ---------------------------------------------------------------------------

class TestLateArrivalInjector:
    """Tests for the late arrival simulation logic."""

    def _make_event(self, **kwargs) -> dict:
        return {
            "event_id": "evt_001",
            "session_id": "sess_abc",
            "user_id": "u_001",
            "event_type": "view",
            "is_late_arrival": False,
            **kwargs,
        }

    def test_zero_pct_never_delays(self):
        injector = LateArrivalInjector(late_arrival_pct=0.0)
        event = self._make_event()
        result = injector.maybe_delay(event)
        assert result.get("_held") is not True
        assert injector.pending_count == 0

    def test_100_pct_always_delays(self):
        injector = LateArrivalInjector(late_arrival_pct=1.0, min_delay_seconds=1, max_delay_seconds=1)
        event = self._make_event()
        result = injector.maybe_delay(event)
        assert result.get("_held") is True
        assert injector.pending_count == 1

    def test_delayed_event_flagged_as_late_arrival(self):
        injector = LateArrivalInjector(late_arrival_pct=1.0, min_delay_seconds=1, max_delay_seconds=1)
        event = self._make_event()
        injector.maybe_delay(event)
        # Fast-forward past the delay
        time.sleep(1.1)
        ready = injector.flush_ready()
        assert len(ready) == 1
        assert ready[0]["is_late_arrival"] is True
        assert ready[0]["late_arrival_delay_seconds"] == 1

    def test_not_yet_due_events_stay_in_queue(self):
        injector = LateArrivalInjector(late_arrival_pct=1.0, min_delay_seconds=60, max_delay_seconds=60)
        event = self._make_event()
        injector.maybe_delay(event)
        ready = injector.flush_ready()
        assert len(ready) == 0
        assert injector.pending_count == 1

    def test_invalid_pct_raises_value_error(self):
        with pytest.raises(ValueError):
            LateArrivalInjector(late_arrival_pct=1.5)

    def test_approximate_rate_respected_over_many_events(self):
        """Statistical test: over 1000 events, ~5% should be held."""
        injector = LateArrivalInjector(late_arrival_pct=0.05, seed=42)
        held = 0
        for i in range(1000):
            result = injector.maybe_delay(self._make_event(event_id=f"evt_{i}"))
            if result.get("_held"):
                held += 1
        # Allow ±3% tolerance for randomness
        assert 20 <= held <= 80, f"Expected ~50 held events, got {held}"


# ---------------------------------------------------------------------------
# KinesisProducer tests (mocked boto3)
# ---------------------------------------------------------------------------

class TestKinesisProducer:
    """Tests for Kinesis producer — all boto3 calls are mocked."""

    @patch("kinesis_producer.boto3.client")
    def test_publish_batch_calls_put_records(self, mock_boto3_client):
        mock_client = MagicMock()
        mock_boto3_client.return_value = mock_client
        mock_client.put_records.return_value = {
            "FailedRecordCount": 0,
            "Records": [{"SequenceNumber": "1", "ShardId": "s0"}],
        }

        producer = KinesisProducer(stream_name="test-stream", region="us-east-1")
        result = producer.publish_batch([
            {"event_id": "e1", "user_id": "u1", "event_type": "view"}
        ])

        mock_client.put_records.assert_called_once()
        assert result["sent"] == 1
        assert result["failed"] == 0

    @patch("kinesis_producer.boto3.client")
    def test_large_batch_split_into_chunks(self, mock_boto3_client):
        mock_client = MagicMock()
        mock_boto3_client.return_value = mock_client
        mock_client.put_records.return_value = {
            "FailedRecordCount": 0,
            "Records": [{"SequenceNumber": str(i)} for i in range(500)],
        }

        producer = KinesisProducer(stream_name="test-stream", region="us-east-1")
        events = [{"event_id": f"e{i}", "user_id": f"u{i}", "event_type": "view"} for i in range(1200)]
        producer.publish_batch(events)

        # 1200 events / 500 per call = 3 calls (500 + 500 + 200)
        assert mock_client.put_records.call_count == 3

    @patch("kinesis_producer.boto3.client")
    def test_partition_key_uses_user_id(self, mock_boto3_client):
        mock_client = MagicMock()
        mock_boto3_client.return_value = mock_client
        mock_client.put_records.return_value = {
            "FailedRecordCount": 0,
            "Records": [{"SequenceNumber": "1"}],
        }

        producer = KinesisProducer(stream_name="test-stream", region="us-east-1")
        producer.publish_batch([{"event_id": "e1", "user_id": "user_42", "event_type": "view"}])

        call_args = mock_client.put_records.call_args
        records = call_args[1]["Records"]
        assert records[0]["PartitionKey"] == "user_42"
