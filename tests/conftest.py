"""
Pytest configuration and shared fixtures.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def mock_aws_credentials(monkeypatch, request):
    """
    Prevent accidental real AWS API calls during unit tests.
    Skipped automatically for integration tests (marked with @pytest.mark.integration)
    so they can use real credentials from the environment.
    """
    if request.node.get_closest_marker("integration"):
        # Integration tests use real AWS credentials from the environment
        return
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def sample_event():
    """A valid on-time clickstream event dict."""
    return {
        "event_id": "evt-test-001",
        "event_time": "2024-10-15T10:00:00+00:00",
        "arrival_time": "2024-10-15T10:00:01+00:00",
        "event_type": "view",
        "product_id": "p123",
        "category_id": "999",
        "category_code": "electronics.phone",
        "brand": "samsung",
        "price": 49.99,
        "user_id": "user_001",
        "session_id": "sess_abc",
        "is_late_arrival": False,
        "late_arrival_delay_seconds": None,
    }


@pytest.fixture
def sample_late_event(sample_event):
    """A late-arriving clickstream event dict."""
    return {
        **sample_event,
        "event_id": "evt-test-002",
        "is_late_arrival": True,
        "late_arrival_delay_seconds": 300,
    }


@pytest.fixture
def cart_session_events():
    """A sequence of events forming a complete session: view → cart → purchase."""
    base_time = "2024-10-15T10:{}:00+00:00"
    return [
        {"event_type": "view",     "price": 99.99, "event_time": base_time.format("00"), "user_id": "u1", "session_id": "s1"},
        {"event_type": "view",     "price": 49.99, "event_time": base_time.format("02"), "user_id": "u1", "session_id": "s1"},
        {"event_type": "cart",     "price": 99.99, "event_time": base_time.format("05"), "user_id": "u1", "session_id": "s1"},
        {"event_type": "cart",     "price": 49.99, "event_time": base_time.format("06"), "user_id": "u1", "session_id": "s1"},
        {"event_type": "purchase", "price": 149.98,"event_time": base_time.format("10"), "user_id": "u1", "session_id": "s1"},
    ]
