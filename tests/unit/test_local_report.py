"""Unit tests for the local report generator."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/dashboard"))

from local_report import LayerMetrics, RestatementMetrics, _sample_data, render


class TestLayerMetrics:

    def test_conversion_rate_zero_sessions(self):
        m = LayerMetrics(total_sessions=0, converted_sessions=0)
        assert m.conversion_rate_pct == 0.0

    def test_conversion_rate_correct(self):
        m = LayerMetrics(total_sessions=1000, converted_sessions=35)
        assert m.conversion_rate_pct == pytest.approx(3.5)

    def test_avg_duration_label_format(self):
        m = LayerMetrics(avg_duration_s=252)
        assert m.avg_duration_label == "4m 12s"

    def test_avg_duration_label_zero(self):
        m = LayerMetrics(avg_duration_s=0)
        assert m.avg_duration_label == "0m 00s"


class TestRestatementMetrics:

    def test_restatement_pct_zero_compared(self):
        r = RestatementMetrics(total_compared=0, sessions_restated=0)
        assert r.restatement_pct == 0.0

    def test_restatement_pct_correct(self):
        r = RestatementMetrics(total_compared=1000, sessions_restated=30)
        assert r.restatement_pct == pytest.approx(3.0)


class TestRender:

    def test_render_contains_date(self):
        speed, batch, audit = _sample_data()
        report = render(speed, batch, audit, "2024-10-15")
        assert "2024-10-15" in report

    def test_render_contains_both_layers(self):
        speed, batch, audit = _sample_data()
        report = render(speed, batch, audit, "2024-10-15")
        assert "Speed Layer" in report
        assert "Batch Layer" in report
        assert "DynamoDB" in report
        assert "Athena" in report

    def test_render_contains_restatement_section(self):
        speed, batch, audit = _sample_data()
        report = render(speed, batch, audit, "2024-10-15")
        assert "RESTATEMENT ANALYSIS" in report
        assert "Sessions restated:" in report
        assert "Revenue error" in report

    def test_render_contains_interpretation(self):
        speed, batch, audit = _sample_data()
        report = render(speed, batch, audit, "2024-10-15")
        assert "INTERPRETATION" in report

    def test_render_session_counts_present(self):
        speed = LayerMetrics(total_sessions=18_432, total_revenue=284_120.50,
                             converted_sessions=590, avg_duration_s=252, latency_label="< 30 seconds")
        batch = LayerMetrics(total_sessions=17_891, total_revenue=291_445.25,
                             converted_sessions=643, avg_duration_s=278, latency_label="~ 8 hours")
        audit = RestatementMetrics(total_compared=18_432, sessions_restated=541,
                                   avg_revenue_disc=13.52, max_revenue_disc=299.00,
                                   total_revenue_restated=7_324.82)
        report = render(speed, batch, audit, "2024-10-15")
        assert "18,432" in report
        assert "17,891" in report
        assert "541" in report

    def test_render_revenue_error_calculated(self):
        # batch=100, speed=90 → 10% error
        speed = LayerMetrics(total_sessions=100, total_revenue=90.0, latency_label="fast")
        batch = LayerMetrics(total_sessions=100, total_revenue=100.0, latency_label="slow")
        audit = RestatementMetrics(total_compared=100, sessions_restated=10)
        report = render(speed, batch, audit, "2024-10-15")
        assert "10.00%" in report
