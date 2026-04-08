"""Unit tests for Lambda sessionizer — session state and cart calculator."""

import os
import sys
from datetime import UTC, datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/lambda/sessionizer"))

from cart_calculator import CartCalculator
from session_state import SessionState, _parse_timestamp

# ---------------------------------------------------------------------------
# SessionState tests
# ---------------------------------------------------------------------------

class TestSessionState:
    """Tests for the 30-minute inactivity session boundary logic."""

    def setup_method(self):
        self.state = SessionState()

    def _ts(self, dt: datetime) -> str:
        return dt.isoformat()

    def test_no_prior_state_is_not_new_session(self):
        """First event for a session_id — no boundary."""
        result = self.state.is_new_session(
            last_event_time=None,
            current_event_time="2024-10-15T10:00:00+00:00",
        )
        assert result is False

    def test_gap_under_30_min_is_same_session(self):
        base = datetime(2024, 10, 15, 10, 0, 0, tzinfo=UTC)
        last = self._ts(base)
        current = self._ts(base + timedelta(minutes=29))
        assert self.state.is_new_session(last, current) is False

    def test_gap_exactly_30_min_is_same_session(self):
        base = datetime(2024, 10, 15, 10, 0, 0, tzinfo=UTC)
        last = self._ts(base)
        current = self._ts(base + timedelta(minutes=30))
        # Exactly 30 min is NOT a new session (boundary is >30 min)
        assert self.state.is_new_session(last, current) is False

    def test_gap_over_30_min_triggers_new_session(self):
        base = datetime(2024, 10, 15, 10, 0, 0, tzinfo=UTC)
        last = self._ts(base)
        current = self._ts(base + timedelta(minutes=31))
        assert self.state.is_new_session(last, current) is True

    def test_large_gap_triggers_new_session(self):
        base = datetime(2024, 10, 15, 10, 0, 0, tzinfo=UTC)
        last = self._ts(base)
        current = self._ts(base + timedelta(hours=3))
        assert self.state.is_new_session(last, current) is True

    def test_null_current_time_uses_wall_clock(self):
        """When current_event_time is None, should use now — won't trigger boundary for a fresh session."""
        recent_ts = self._ts(datetime.now(tz=UTC) - timedelta(minutes=5))
        result = self.state.is_new_session(
            last_event_time=recent_ts,
            current_event_time=None,
        )
        assert result is False

    def test_malformed_timestamp_does_not_raise(self):
        """Conservative: bad timestamp → treat as same session (no data loss)."""
        result = self.state.is_new_session(
            last_event_time="NOT_A_TIMESTAMP",
            current_event_time="2024-10-15T10:00:00+00:00",
        )
        assert result is False

    def test_update_increments_event_count(self):
        session = {}
        event = {"event_type": "view", "event_time": "2024-10-15T10:00:00+00:00"}
        updated = self.state.update(session, event)
        assert updated["event_count"] == 1

        updated2 = self.state.update(updated, event)
        assert updated2["event_count"] == 2

    def test_update_sets_session_start_on_first_event(self):
        session = {}
        event = {"event_type": "view", "event_time": "2024-10-15T10:00:00+00:00"}
        updated = self.state.update(session, event)
        assert updated["session_start"] == "2024-10-15T10:00:00+00:00"

    def test_update_does_not_overwrite_session_start(self):
        session = {"session_start": "2024-10-15T10:00:00+00:00", "event_count": 1}
        event = {"event_type": "view", "event_time": "2024-10-15T10:05:00+00:00"}
        updated = self.state.update(session, event)
        assert updated["session_start"] == "2024-10-15T10:00:00+00:00"

    def test_purchase_event_sets_converted_true(self):
        session = {"event_count": 3}
        event = {"event_type": "purchase", "event_time": "2024-10-15T10:10:00+00:00"}
        updated = self.state.update(session, event)
        assert updated["converted"] is True
        assert "conversion_time" in updated

    def test_view_event_does_not_set_converted(self):
        session = {}
        event = {"event_type": "view", "event_time": "2024-10-15T10:00:00+00:00"}
        updated = self.state.update(session, event)
        assert updated.get("converted") is not True

    def test_update_tracks_event_types_seen(self):
        session = {}
        for et in ["view", "cart", "view", "purchase"]:
            event = {"event_type": et, "event_time": "2024-10-15T10:00:00+00:00"}
            session = self.state.update(session, event)
        assert set(session["event_types_seen"]) == {"view", "cart", "purchase"}

    def test_update_does_not_mutate_input(self):
        """update() must return a new dict — immutability."""
        original = {"event_count": 5}
        event = {"event_type": "view", "event_time": "2024-10-15T10:00:00+00:00"}
        self.state.update(original, event)
        assert original["event_count"] == 5  # unchanged


# ---------------------------------------------------------------------------
# CartCalculator tests
# ---------------------------------------------------------------------------

class TestCartCalculator:
    """Tests for cart total and conversion value computation."""

    def setup_method(self):
        self.calc = CartCalculator()

    def _event(self, event_type: str, price: float) -> dict:
        return {"event_type": event_type, "price": price}

    def test_view_events_not_added_to_cart(self):
        events = [self._event("view", 100.0), self._event("view", 50.0)]
        assert self.calc.compute(events) == 0.0

    def test_cart_events_accumulate(self):
        events = [self._event("cart", 29.99), self._event("cart", 49.99)]
        assert self.calc.compute(events) == pytest.approx(79.98, rel=1e-3)

    def test_mixed_events_only_counts_cart(self):
        events = [
            self._event("view", 100.0),
            self._event("cart", 29.99),
            self._event("view", 50.0),
            self._event("purchase", 29.99),
        ]
        # Only cart event contributes
        assert self.calc.compute(events) == pytest.approx(29.99, rel=1e-3)

    def test_none_price_defaults_to_zero(self):
        events = [{"event_type": "cart", "price": None}]
        assert self.calc.compute(events) == 0.0

    def test_nan_price_defaults_to_zero(self):
        import math
        events = [{"event_type": "cart", "price": float("nan")}]
        assert self.calc.compute(events) == 0.0

    def test_negative_price_clamped_to_zero(self):
        events = [{"event_type": "cart", "price": -10.0}]
        assert self.calc.compute(events) == 0.0

    def test_empty_events_returns_zero(self):
        assert self.calc.compute([]) == 0.0

    def test_conversion_value_sums_purchases(self):
        events = [
            self._event("cart", 29.99),
            self._event("purchase", 29.99),
        ]
        assert self.calc.get_conversion_value(events) == pytest.approx(29.99, rel=1e-3)

    def test_conversion_value_zero_if_no_purchase(self):
        events = [self._event("view", 50.0), self._event("cart", 29.99)]
        assert self.calc.get_conversion_value(events) == 0.0

    def test_result_rounded_to_2dp(self):
        events = [self._event("cart", 0.1), self._event("cart", 0.2)]
        result = self.calc.compute(events)
        # Floating point: 0.1 + 0.2 = 0.30000000000000004, but we round to 2dp
        assert result == 0.30


# ---------------------------------------------------------------------------
# Timestamp parsing tests
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    def test_iso_with_utc_offset(self):
        dt = _parse_timestamp("2024-10-15T10:00:00+00:00")
        assert dt.tzinfo is not None
        assert dt.hour == 10

    def test_iso_with_z_suffix(self):
        dt = _parse_timestamp("2024-10-15T10:00:00Z")
        assert dt.tzinfo is not None

    def test_naive_datetime_gets_utc(self):
        dt = _parse_timestamp("2024-10-15 10:00:00")
        assert dt.tzinfo is not None

    def test_invalid_raises_value_error(self):
        with pytest.raises((ValueError, TypeError)):
            _parse_timestamp("not-a-date")
