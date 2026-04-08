"""
Unit tests for the Spark session stitcher and late arrival handler.

Spark tests use a local SparkSession (no AWS, no cluster needed).
These run in CI on a plain Python environment with pyspark installed.

Add pyspark to requirements-dev.txt to run locally:
    pip install pyspark==3.5.0
"""

import pytest

try:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    PYSPARK_AVAILABLE = True
except ImportError:
    PYSPARK_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not PYSPARK_AVAILABLE,
    reason="pyspark not installed — run 'pip install pyspark==3.5.0' to enable Spark tests",
)

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/spark"))


@pytest.fixture(scope="module")
def spark():
    """Local SparkSession for unit testing — no cluster required."""
    session = (
        SparkSession.builder
        .master("local[2]")
        .appName("clickstream-unit-tests")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    session.sparkContext.setLogLevel("ERROR")
    yield session
    session.stop()


def make_events(spark, rows: list[dict]):
    """Create a DataFrame from a list of event dicts."""
    return spark.createDataFrame(rows)


# ─── session_stitcher tests ──────────────────────────────────────────────────

class TestSessionize:
    """Tests for the sessionize() function."""

    def test_single_user_single_session(self, spark):
        from session_stitcher import aggregate_sessions, sessionize

        events = make_events(spark, [
            {"user_id": "u1", "session_id": "s1", "event_type": "view",  "event_time": "2024-10-15 10:00:00", "arrival_time": "2024-10-15 10:00:01", "price": 0.0,  "is_late_arrival": False},
            {"user_id": "u1", "session_id": "s1", "event_type": "cart",  "event_time": "2024-10-15 10:05:00", "arrival_time": "2024-10-15 10:05:01", "price": 49.99, "is_late_arrival": False},
            {"user_id": "u1", "session_id": "s1", "event_type": "purchase","event_time": "2024-10-15 10:10:00","arrival_time": "2024-10-15 10:10:01","price": 49.99,"is_late_arrival": False},
        ])

        stitched   = sessionize(events)
        aggregated = aggregate_sessions(stitched)
        rows       = aggregated.collect()

        assert len(rows) == 1
        assert rows[0]["event_count"] == 3
        assert rows[0]["converted"]   is True

    def test_30_min_gap_creates_two_sessions(self, spark):
        from session_stitcher import aggregate_sessions, sessionize

        events = make_events(spark, [
            {"user_id": "u1", "session_id": "s1", "event_type": "view", "event_time": "2024-10-15 10:00:00", "arrival_time": "2024-10-15 10:00:01", "price": 0.0, "is_late_arrival": False},
            # 35-minute gap — should trigger a new session boundary
            {"user_id": "u1", "session_id": "s2", "event_type": "view", "event_time": "2024-10-15 10:35:00", "arrival_time": "2024-10-15 10:35:01", "price": 0.0, "is_late_arrival": False},
        ])

        stitched   = sessionize(events)
        aggregated = aggregate_sessions(stitched)
        rows       = aggregated.collect()

        assert len(rows) == 2

    def test_gap_under_30_min_stays_one_session(self, spark):
        from session_stitcher import aggregate_sessions, sessionize

        events = make_events(spark, [
            {"user_id": "u1", "session_id": "s1", "event_type": "view", "event_time": "2024-10-15 10:00:00", "arrival_time": "2024-10-15 10:00:01", "price": 0.0, "is_late_arrival": False},
            {"user_id": "u1", "session_id": "s1", "event_type": "view", "event_time": "2024-10-15 10:29:00", "arrival_time": "2024-10-15 10:29:01", "price": 0.0, "is_late_arrival": False},
        ])

        stitched   = sessionize(events)
        aggregated = aggregate_sessions(stitched)
        rows       = aggregated.collect()

        assert len(rows) == 1

    def test_two_users_independent_sessions(self, spark):
        from session_stitcher import aggregate_sessions, sessionize

        events = make_events(spark, [
            {"user_id": "u1", "session_id": "s1", "event_type": "view", "event_time": "2024-10-15 10:00:00", "arrival_time": "2024-10-15 10:00:01", "price": 0.0, "is_late_arrival": False},
            {"user_id": "u2", "session_id": "s2", "event_type": "view", "event_time": "2024-10-15 10:00:00", "arrival_time": "2024-10-15 10:00:01", "price": 0.0, "is_late_arrival": False},
        ])

        stitched   = sessionize(events)
        aggregated = aggregate_sessions(stitched)
        rows       = aggregated.collect()

        user_ids = {r["user_id"] for r in rows}
        assert user_ids == {"u1", "u2"}
        assert len(rows) == 2

    def test_cart_total_computed_correctly(self, spark):
        from session_stitcher import aggregate_sessions, sessionize

        events = make_events(spark, [
            {"user_id": "u1", "session_id": "s1", "event_type": "cart", "event_time": "2024-10-15 10:00:00", "arrival_time": "2024-10-15 10:00:01", "price": 29.99, "is_late_arrival": False},
            {"user_id": "u1", "session_id": "s1", "event_type": "cart", "event_time": "2024-10-15 10:01:00", "arrival_time": "2024-10-15 10:01:01", "price": 49.99, "is_late_arrival": False},
        ])

        stitched   = sessionize(events)
        aggregated = aggregate_sessions(stitched)
        rows       = aggregated.collect()

        assert rows[0]["cart_total"] == pytest.approx(79.98, rel=1e-3)

    def test_late_arrival_count_tracked(self, spark):
        from session_stitcher import aggregate_sessions, sessionize

        events = make_events(spark, [
            {"user_id": "u1", "session_id": "s1", "event_type": "view",  "event_time": "2024-10-15 10:00:00", "arrival_time": "2024-10-15 10:00:01", "price": 0.0,  "is_late_arrival": False},
            {"user_id": "u1", "session_id": "s1", "event_type": "cart",  "event_time": "2024-10-15 09:55:00", "arrival_time": "2024-10-15 10:08:00",  "price": 29.99, "is_late_arrival": True},
        ])

        stitched   = sessionize(events)
        aggregated = aggregate_sessions(stitched)
        rows       = aggregated.collect()

        assert rows[0]["late_arrival_count"] == 1
        assert rows[0]["had_restatement"]    is True

    def test_null_event_time_falls_back_to_arrival_time(self, spark):
        from session_stitcher import sessionize

        events = make_events(spark, [
            {"user_id": "u1", "session_id": "s1", "event_type": "view", "event_time": None, "arrival_time": "2024-10-15 10:00:01", "price": 0.0, "is_late_arrival": True},
        ])

        # Should not throw — effective_time falls back to arrival_time
        stitched = sessionize(events)
        assert stitched.filter(F.col("effective_time").isNull()).count() == 0


# ─── late_arrival_handler tests ──────────────────────────────────────────────

class TestComputeSessionDeltas:
    """Tests for the restatement delta computation."""

    def test_matching_sessions_no_restatement(self, spark):
        from late_arrival_handler import compute_session_deltas

        batch_df = make_events(spark, [{
            "batch_session_id": "u1_1",
            "user_id": "u1",
            "cart_total": 29.99,
            "conversion_value": 0.0,
            "event_count": 3,
            "converted": False,
            "duration_seconds": 300,
            "late_arrival_count": 0,
            "had_restatement": False,
            "original_session_ids": ["s1"],
        }])

        realtime_df = make_events(spark, [{
            "session_id": "s1",
            "rt_event_count": 3,
            "rt_cart_total": 29.99,
            "rt_conversion_value": 0.0,
            "rt_converted": False,
            "rt_duration_seconds": 300,
            "session_start": "2024-10-15 10:00:00",
            "last_event_time": "2024-10-15 10:05:00",
            "date_partition": "2024-10-15",
        }])

        deltas = compute_session_deltas(batch_df, realtime_df)
        rows   = deltas.collect()

        assert len(rows) == 1
        assert rows[0]["restatement_type"] == "no_restatement"
        assert abs(rows[0]["cart_total_abs_delta"]) < 0.01

    def test_revenue_discrepancy_flagged(self, spark):
        from late_arrival_handler import compute_session_deltas

        batch_df = make_events(spark, [{
            "batch_session_id": "u1_1",
            "user_id": "u1",
            "cart_total": 79.98,   # Correct value — includes late arrival
            "conversion_value": 0.0,
            "event_count": 4,
            "converted": False,
            "duration_seconds": 400,
            "late_arrival_count": 1,
            "had_restatement": True,
            "original_session_ids": ["s1"],
        }])

        realtime_df = make_events(spark, [{
            "session_id": "s1",
            "rt_event_count": 3,
            "rt_cart_total": 29.99,  # Missing late arrival item
            "rt_conversion_value": 0.0,
            "rt_converted": False,
            "rt_duration_seconds": 300,
            "session_start": "2024-10-15 10:00:00",
            "last_event_time": "2024-10-15 10:05:00",
            "date_partition": "2024-10-15",
        }])

        deltas = compute_session_deltas(batch_df, realtime_df)
        rows   = deltas.collect()

        assert rows[0]["restatement_type"] == "revenue_restatement"
        assert rows[0]["cart_total_abs_delta"] == pytest.approx(49.99, rel=1e-2)

    def test_conversion_flip_detected(self, spark):
        from late_arrival_handler import compute_session_deltas

        batch_df = make_events(spark, [{
            "batch_session_id": "u1_1",
            "user_id": "u1",
            "cart_total": 49.99,
            "conversion_value": 49.99,
            "event_count": 4,
            "converted": True,    # Batch: purchase arrived (late)
            "duration_seconds": 400,
            "late_arrival_count": 1,
            "had_restatement": True,
            "original_session_ids": ["s1"],
        }])

        realtime_df = make_events(spark, [{
            "session_id": "s1",
            "rt_event_count": 3,
            "rt_cart_total": 49.99,
            "rt_conversion_value": 0.0,
            "rt_converted": False,  # Speed layer: purchase not yet arrived
            "rt_duration_seconds": 300,
            "session_start": "2024-10-15 10:00:00",
            "last_event_time": "2024-10-15 10:05:00",
            "date_partition": "2024-10-15",
        }])

        deltas = compute_session_deltas(batch_df, realtime_df)
        rows   = deltas.collect()

        assert rows[0]["conversion_flipped"]  is True
        assert rows[0]["restatement_type"]    == "conversion_flip"
