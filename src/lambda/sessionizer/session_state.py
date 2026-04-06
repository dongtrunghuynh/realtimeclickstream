"""
Session state management — core sessionization logic.

The 30-minute inactivity rule:
    If the gap between a user's last event and the next event exceeds
    30 minutes, a new session begins. This is the industry standard
    (Google Analytics uses the same default).

Why this is hard in streaming:
    Events arrive at Lambda in Kinesis polling batches. An event that
    arrives 5 minutes late might belong to the previous session, but
    Lambda has already closed it. The Spark batch job corrects this.
"""

import logging
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

SESSION_TIMEOUT_MINUTES = 30


class SessionState:
    """Encapsulates session boundary detection and state update logic."""

    TIMEOUT = timedelta(minutes=SESSION_TIMEOUT_MINUTES)

    def is_new_session(
        self,
        last_event_time: str | None,
        current_event_time: str | None,
    ) -> bool:
        """
        Returns True if the gap between events exceeds SESSION_TIMEOUT_MINUTES,
        indicating the start of a new session.

        Edge cases:
        - last_event_time is None → first event, not a new session relative to
          existing state (state is empty)
        - current_event_time is None → use current wall clock time
        - Parsing failures → log warning and treat as NOT a new session
          (conservative — avoids losing session state on bad data)
        """
        if last_event_time is None:
            return False  # No prior state — this is the first event for this session_id

        try:
            last_dt = _parse_timestamp(last_event_time)
            current_dt = _parse_timestamp(current_event_time) if current_event_time else datetime.now(tz=UTC)

            gap = current_dt - last_dt
            is_new = gap > self.TIMEOUT

            if is_new:
                logger.info(
                    "New session boundary detected — gap=%.1f minutes",
                    gap.total_seconds() / 60,
                )

            return is_new

        except (ValueError, TypeError) as exc:
            logger.warning(
                "Could not parse timestamps (last=%s, current=%s): %s — assuming same session",
                last_event_time,
                current_event_time,
                exc,
            )
            return False

    def update(self, session: dict, event: dict) -> dict:
        """
        Apply a new event to the current session state dict.
        Returns a new dict (does not mutate the input).

        State fields updated:
        - event_count: incremented
        - last_event_time: updated to event's time
        - session_start: set on first event only
        - converted: True if event_type is 'purchase'
        - event_types_seen: set of event types (for funnel analysis)
        """
        updated = dict(session)

        updated["event_count"] = session.get("event_count", 0) + 1
        updated["last_event_time"] = event.get("event_time") or event.get("arrival_time")

        if "session_start" not in updated or not updated["session_start"]:
            updated["session_start"] = updated["last_event_time"]

        if event.get("event_type") == "purchase":
            updated["converted"] = True
            updated["conversion_time"] = updated["last_event_time"]

        # Track which event types appeared in this session
        seen = set(updated.get("event_types_seen", []))
        seen.add(event.get("event_type", "unknown"))
        updated["event_types_seen"] = list(seen)

        return updated


def _parse_timestamp(ts: str) -> datetime:
    """
    Parse an ISO8601 timestamp string to a timezone-aware datetime.
    Handles both 'Z' suffix and '+00:00' offset formats.
    """
    ts = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
