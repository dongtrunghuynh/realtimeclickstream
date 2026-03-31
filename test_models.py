"""
tests/unit/test_models.py
──────────────────────────────────────────────────────────────────────────────
Tests for Pydantic event schema validation (models.py).
No AWS calls — pure Python.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.stream_processor.models import (
    ClickstreamEvent,
    DeviceType,
    EventType,
    GeoContext,
    PageContext,
    ProcessedEvent,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _valid_payload(**overrides: object) -> dict:
    base = {
        "event_id":   str(uuid.uuid4()),
        "event_type": "page_view",
        "session_id": str(uuid.uuid4()),
        "user_id":    "user-abc",
        "timestamp":  "2025-06-14T10:00:00Z",
        "page":       {"url": "https://example.com/home"},
        "device":     {"type": "desktop", "browser": "Chrome"},
        "properties": {},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# ClickstreamEvent — happy path
# ---------------------------------------------------------------------------

class TestClickstreamEventValid:
    def test_parses_minimal_payload(self):
        event = ClickstreamEvent.model_validate(_valid_payload())
        assert event.event_type == EventType.PAGE_VIEW
        assert event.user_id    == "user-abc"

    def test_timestamp_normalised_to_utc(self):
        payload = _valid_payload(timestamp="2025-06-14T12:00:00+02:00")
        event   = ClickstreamEvent.model_validate(payload)
        assert event.timestamp == datetime(2025, 6, 14, 10, 0, 0, tzinfo=timezone.utc)

    def test_naive_timestamp_assumed_utc(self):
        payload = _valid_payload(timestamp="2025-06-14T10:00:00")
        event   = ClickstreamEvent.model_validate(payload)
        assert event.timestamp.tzinfo == timezone.utc

    def test_extra_fields_ignored(self):
        payload = _valid_payload(unknown_field="should_be_ignored")
        event   = ClickstreamEvent.model_validate(payload)
        assert not hasattr(event, "unknown_field")

    def test_all_event_types_accepted(self):
        for et in EventType:
            props = {"amount": 9.99, "currency": "AUD"} if et == EventType.PURCHASE else {}
            payload = _valid_payload(event_type=et.value, properties=props)
            event   = ClickstreamEvent.model_validate(payload)
            assert event.event_type == et

    def test_purchase_with_required_properties(self):
        payload = _valid_payload(
            event_type="purchase",
            properties={"amount": 49.99, "currency": "AUD", "item_id": "SKU-123"},
        )
        event = ClickstreamEvent.model_validate(payload)
        assert event.event_type == EventType.PURCHASE


# ---------------------------------------------------------------------------
# ClickstreamEvent — validation failures
# ---------------------------------------------------------------------------

class TestClickstreamEventInvalid:
    @pytest.mark.parametrize("field", ["event_id", "event_type", "session_id", "user_id", "timestamp", "page"])
    def test_missing_required_field_raises(self, field: str):
        payload = _valid_payload()
        del payload[field]
        with pytest.raises(ValidationError):
            ClickstreamEvent.model_validate(payload)

    def test_invalid_event_type_raises(self):
        with pytest.raises(ValidationError):
            ClickstreamEvent.model_validate(_valid_payload(event_type="not_a_real_type"))

    def test_empty_user_id_raises(self):
        with pytest.raises(ValidationError):
            ClickstreamEvent.model_validate(_valid_payload(user_id=""))

    def test_purchase_missing_amount_raises(self):
        payload = _valid_payload(event_type="purchase", properties={"currency": "AUD"})
        with pytest.raises(ValidationError, match="amount"):
            ClickstreamEvent.model_validate(payload)

    def test_purchase_missing_currency_raises(self):
        payload = _valid_payload(event_type="purchase", properties={"amount": 9.99})
        with pytest.raises(ValidationError, match="currency"):
            ClickstreamEvent.model_validate(payload)

    def test_empty_page_url_raises(self):
        payload = _valid_payload(page={"url": "  "})
        with pytest.raises(ValidationError):
            ClickstreamEvent.model_validate(payload)


# ---------------------------------------------------------------------------
# GeoContext
# ---------------------------------------------------------------------------

class TestGeoContext:
    def test_country_code_uppercased(self):
        geo = GeoContext(country_code="au", region="QLD", city="Brisbane")
        assert geo.country_code == "AU"

    def test_null_country_code_ok(self):
        geo = GeoContext()
        assert geo.country_code is None


# ---------------------------------------------------------------------------
# ProcessedEvent.from_event
# ---------------------------------------------------------------------------

class TestProcessedEvent:
    def _make_event(self) -> ClickstreamEvent:
        return ClickstreamEvent.model_validate(_valid_payload())

    def test_from_event_sets_metadata(self):
        event  = self._make_event()
        result = ProcessedEvent.from_event(event, kinesis_sequence="seq-001", environment="test")

        assert result.environment      == "test"
        assert result.kinesis_sequence == "seq-001"
        assert result.schema_version   == "1.0"
        assert result.event_type       == "page_view"

    def test_from_event_sets_partition_columns(self):
        event  = self._make_event()
        result = ProcessedEvent.from_event(event, kinesis_sequence="seq-001", environment="test")

        assert result.partition_event_type == "page_view"
        assert result.partition_year       == "2025"
        assert result.partition_month      == "06"
        assert result.partition_day        == "14"

    def test_from_event_serialises_uuids_as_strings(self):
        event  = self._make_event()
        result = ProcessedEvent.from_event(event, kinesis_sequence="seq-001", environment="test")

        # Should be strings, not UUID objects
        assert isinstance(result.event_id,  str)
        assert isinstance(result.session_id, str)

    def test_model_dump_json_roundtrip(self):
        event  = self._make_event()
        result = ProcessedEvent.from_event(event, kinesis_sequence="seq-001", environment="test")

        # Should serialise and back without error
        import json
        data = json.loads(result.model_dump_json(exclude_none=True))
        assert data["event_type"] == "page_view"
