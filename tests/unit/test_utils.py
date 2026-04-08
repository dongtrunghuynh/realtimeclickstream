"""Unit tests for shared Lambda utilities (S3 writer and log context)."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/lambda/shared"))


class TestWriteEventsToS3:

    def _events(self, n=3):
        return [
            {
                "event_id": f"evt_{i}",
                "event_time": "2024-10-15T10:00:00+00:00",
                "arrival_time": "2024-10-15T10:00:01+00:00",
                "event_type": "view",
                "product_id": f"p{i}",
                "category_id": "999",
                "category_code": "electronics.phone",
                "brand": "samsung",
                "price": float(i * 10),
                "user_id": f"u{i}",
                "session_id": f"s{i}",
                "is_late_arrival": False,
                "late_arrival_delay_seconds": None,
            }
            for i in range(n)
        ]

    # NOTE: utils.py creates _s3 at module load time via boto3.client("s3").
    # We must patch the already-created module-level object, not boto3.client.
    # Use patch("utils._s3") so the mock replaces the live client object.

    @patch("utils._s3")
    def test_ndjson_put_called_once(self, mock_s3):
        from utils import write_events_to_s3
        write_events_to_s3("my-bucket", "events/year=2024/", self._events(3), fmt="ndjson")
        mock_s3.put_object.assert_called_once()
        args = mock_s3.put_object.call_args[1]
        assert args["Bucket"] == "my-bucket"
        assert args["Key"].startswith("events/year=2024/")
        assert args["Key"].endswith(".ndjson")

    @patch("utils._s3")
    def test_ndjson_body_is_valid_ndjson(self, mock_s3):
        from utils import write_events_to_s3
        write_events_to_s3("my-bucket", "events/", self._events(5), fmt="ndjson")
        body_bytes = mock_s3.put_object.call_args[1]["Body"]
        lines = body_bytes.decode("utf-8").strip().split("\n")
        assert len(lines) == 5
        for line in lines:
            parsed = json.loads(line)
            assert "event_id" in parsed

    @patch("utils._s3")
    def test_empty_events_returns_empty_string(self, mock_s3):
        from utils import write_events_to_s3
        result = write_events_to_s3("my-bucket", "events/", [], fmt="ndjson")
        assert result == ""
        mock_s3.put_object.assert_not_called()

    @patch("utils._s3")
    def test_key_prefix_used_as_prefix(self, mock_s3):
        from utils import write_events_to_s3
        write_events_to_s3("b", "late-arrivals/year=2024/month=10/", self._events(1))
        key = mock_s3.put_object.call_args[1]["Key"]
        assert key.startswith("late-arrivals/year=2024/month=10/")

    @patch("utils._s3")
    def test_content_type_is_ndjson(self, mock_s3):
        from utils import write_events_to_s3
        write_events_to_s3("b", "events/", self._events(2), fmt="ndjson")
        content_type = mock_s3.put_object.call_args[1]["ContentType"]
        assert content_type == "application/x-ndjson"

    @patch("utils._s3")
    def test_parquet_format_falls_back_gracefully(self, mock_s3):
        """When pyarrow is unavailable, parquet falls back to NDJSON without crashing."""
        import sys
        # Simulate pyarrow not installed
        old_pyarrow = sys.modules.get("pyarrow")
        old_pq = sys.modules.get("pyarrow.parquet")
        sys.modules["pyarrow"] = None
        sys.modules["pyarrow.parquet"] = None
        try:
            from utils import write_events_to_s3
            # Should not raise — falls back to NDJSON
            write_events_to_s3("b", "p/", self._events(2), fmt="parquet")
            assert mock_s3.put_object.called
        finally:
            if old_pyarrow is None:
                sys.modules.pop("pyarrow", None)
            else:
                sys.modules["pyarrow"] = old_pyarrow
            if old_pq is None:
                sys.modules.pop("pyarrow.parquet", None)
            else:
                sys.modules["pyarrow.parquet"] = old_pq


class TestBuildLogContext:

    def test_includes_all_key_fields(self):
        from utils import build_log_context
        state = {
            "event_count": 5,
            "cart_total": 29.99,
            "converted": True,
            "last_event_time": "2024-10-15T10:05:00+00:00",
        }
        result = build_log_context("sess_abc", state)
        assert "session_id=sess_abc" in result
        assert "event_count=5" in result
        assert "cart_total=29.99" in result
        assert "converted=True" in result

    def test_empty_state_does_not_raise(self):
        from utils import build_log_context
        result = build_log_context("sess_xyz", {})
        assert "session_id=sess_xyz" in result
        assert "event_count=0" in result

    def test_cart_total_formatted_to_2dp(self):
        from utils import build_log_context
        state = {"cart_total": 29.9}
        result = build_log_context("s1", state)
        assert "cart_total=29.90" in result
