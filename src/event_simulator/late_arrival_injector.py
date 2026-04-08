"""
Late Arrival Injector — simulates mobile clients with intermittent connectivity.

With probability `late_arrival_pct`, an event is held back for a random delay
(2–15 minutes) before being released into the main event stream. These events
have `is_late_arrival=True` and will be handled differently by the Lambda
sessionizer (written to S3 but NOT applied to DynamoDB real-time state).

This is the mechanism that makes the accuracy/latency tradeoff visible:
without late arrivals, the speed layer would always be correct.
"""

import logging
import random
import time
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


class LateArrivalInjector:
    """
    Holds back a fraction of events and releases them after a delay,
    mimicking real-world network delays, mobile client sync lag, and
    batch uploads from offline systems.
    """

    def __init__(
        self,
        late_arrival_pct: float = 0.05,
        min_delay_seconds: int = 120,
        max_delay_seconds: int = 900,
        seed: int | None = None,
    ):
        """
        Args:
            late_arrival_pct:   Fraction of events to delay (0.0–1.0)
            min_delay_seconds:  Minimum hold time
            max_delay_seconds:  Maximum hold time
            seed:               Random seed for reproducibility in tests
        """
        if not 0.0 <= late_arrival_pct <= 1.0:
            raise ValueError("late_arrival_pct must be between 0.0 and 1.0")

        self.late_arrival_pct = late_arrival_pct
        self.min_delay = min_delay_seconds
        self.max_delay = max_delay_seconds
        self._rng = random.Random(seed)
        self._held_events: list[dict] = []  # (release_at_monotonic, event)
        logger.info(
            "LateArrivalInjector: %.1f%% of events delayed %d–%ds",
            late_arrival_pct * 100,
            min_delay_seconds,
            max_delay_seconds,
        )

    def maybe_delay(self, event: dict) -> dict:
        """
        Possibly hold back the event. If held, adds it to the internal
        queue and returns a placeholder. If not held, returns the event
        unchanged (is_late_arrival stays False).

        NOTE: This returns the SAME event if not delayed. Callers should
        check if the returned event is the same object or a new one.
        """
        if self._rng.random() < self.late_arrival_pct:
            delay = self._rng.randint(self.min_delay, self.max_delay)
            release_at = time.monotonic() + delay

            delayed_event = dict(event)
            delayed_event["is_late_arrival"] = True
            delayed_event["late_arrival_delay_seconds"] = delay

            self._held_events.append((release_at, delayed_event))
            logger.debug(
                "Holding event %s for %ds (session=%s)",
                event.get("event_id"),
                delay,
                event.get("session_id"),
            )
            # Return a sentinel so the caller knows this event was swallowed
            return {"_held": True}

        return event

    def flush_ready(self) -> list[dict]:
        """
        Return all held events whose release time has passed.
        Remove them from the internal queue.
        """
        now = time.monotonic()
        ready = []
        still_held = []

        for release_at, event in self._held_events:
            if now >= release_at:
                # Update arrival_time to now — the event is finally "arriving"
                event["arrival_time"] = datetime.now(tz=UTC).isoformat()
                ready.append(event)
            else:
                still_held.append((release_at, event))

        if ready:
            logger.info("Releasing %d late-arriving events", len(ready))

        self._held_events = still_held
        return ready

    @property
    def pending_count(self) -> int:
        """Number of events currently being held."""
        return len(self._held_events)
