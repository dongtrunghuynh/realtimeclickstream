"""Unit tests for the CloudWatch metrics publisher."""

import os
import sys
import time
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/event_simulator"))

from metrics import SimulatorMetrics


class TestSimulatorMetrics:

    @patch("metrics.boto3.client")
    def test_disabled_metrics_makes_no_api_calls(self, mock_boto3):
        m = SimulatorMetrics("test-stream", enabled=False)
        m.record_sent(100)
        m.record_failed(5)
        m.stop()
        mock_boto3.assert_not_called()

    @patch("metrics.boto3.client")
    def test_stop_triggers_final_publish(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.return_value = mock_client

        m = SimulatorMetrics("test-stream", enabled=True)
        m.record_sent(50)
        m.stop()

        # stop() calls _publish() once for final flush
        mock_client.put_metric_data.assert_called()
        call_kwargs = mock_client.put_metric_data.call_args[1]
        assert call_kwargs["Namespace"] == "ClickstreamPipeline/Simulator"

    @patch("metrics.boto3.client")
    def test_sent_counter_is_thread_safe(self, mock_boto3):
        import threading
        mock_boto3.return_value = MagicMock()
        m = SimulatorMetrics("test-stream", enabled=False)

        def increment():
            for _ in range(1000):
                m.record_sent(1)

        threads = [threading.Thread(target=increment) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert m._sent == 5000

    @patch("metrics.boto3.client")
    def test_cloudwatch_failure_does_not_raise(self, mock_boto3):
        from botocore.exceptions import ClientError
        mock_client = MagicMock()
        mock_boto3.return_value = mock_client
        mock_client.put_metric_data.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": ""}}, "PutMetricData"
        )

        m = SimulatorMetrics("test-stream", enabled=True)
        m.record_sent(10)
        # Should NOT raise even though CloudWatch call fails
        m.stop()

    @patch("metrics.boto3.client")
    def test_metrics_contain_correct_dimension(self, mock_boto3):
        mock_client = MagicMock()
        mock_boto3.return_value = mock_client

        m = SimulatorMetrics("my-stream-dev", enabled=True)
        m.record_sent(42)
        m.stop()

        call_kwargs = mock_client.put_metric_data.call_args[1]
        metric_data = call_kwargs["MetricData"]
        for metric in metric_data:
            dim_names = [d["Name"] for d in metric["Dimensions"]]
            dim_vals  = [d["Value"] for d in metric["Dimensions"]]
            assert "StreamName" in dim_names
            assert "my-stream-dev" in dim_vals
