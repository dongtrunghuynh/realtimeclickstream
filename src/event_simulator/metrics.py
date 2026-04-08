"""
CloudWatch metrics publisher — tracks simulator throughput and health.

Publishes custom metrics every 30 seconds while the simulator runs:
  - EventsSentTotal       (count)
  - EventsFailedTotal     (count)
  - LateArrivalsPending   (count)
  - ThroughputPerSecond   (count/s)

View in CloudWatch:  Metrics → Custom Namespaces → ClickstreamPipeline/Simulator
"""

import logging
import threading
import time
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

NAMESPACE = "ClickstreamPipeline/Simulator"
PUBLISH_INTERVAL_SECONDS = 30


class SimulatorMetrics:
    """
    Thread-safe metrics collector. The simulator increments counters via
    record_sent() / record_failed(). A background thread publishes to
    CloudWatch every 30 seconds.
    """

    def __init__(
        self,
        stream_name: str,
        region: str = "us-east-1",
        enabled: bool = True,
    ):
        self.stream_name = stream_name
        self.enabled = enabled
        self._client = boto3.client("cloudwatch", region_name=region) if enabled else None

        # Thread-safe counters
        self._lock = threading.Lock()
        self._sent = 0
        self._failed = 0
        self._late_pending = 0
        self._start_time = time.monotonic()

        # Background publisher
        self._stop_event = threading.Event()
        if enabled:
            self._thread = threading.Thread(target=self._publish_loop, daemon=True)
            self._thread.start()
            logger.info("CloudWatch metrics enabled — namespace: %s", NAMESPACE)
        else:
            logger.info("CloudWatch metrics disabled")

    # ─── Public API ──────────────────────────────────────────────────────────

    def record_sent(self, count: int = 1) -> None:
        with self._lock:
            self._sent += count

    def record_failed(self, count: int = 1) -> None:
        with self._lock:
            self._failed += count

    def set_late_pending(self, count: int) -> None:
        with self._lock:
            self._late_pending = count

    def stop(self) -> None:
        """Stop the background publisher and do a final flush."""
        self._stop_event.set()
        if self.enabled:
            self._publish()   # Final flush

    # ─── Internal ────────────────────────────────────────────────────────────

    def _publish_loop(self) -> None:
        while not self._stop_event.wait(PUBLISH_INTERVAL_SECONDS):
            self._publish()

    def _publish(self) -> None:
        if not self.enabled:
            return
        try:
            with self._lock:
                sent   = self._sent
                failed = self._failed
                late   = self._late_pending
            elapsed = max(time.monotonic() - self._start_time, 1)
            throughput = sent / elapsed

            dimensions = [{"Name": "StreamName", "Value": self.stream_name}]
            now = datetime.now(tz=UTC)

            self._client.put_metric_data(
                Namespace=NAMESPACE,
                MetricData=[
                    {
                        "MetricName": "EventsSentTotal",
                        "Value": sent,
                        "Unit": "Count",
                        "Timestamp": now,
                        "Dimensions": dimensions,
                    },
                    {
                        "MetricName": "EventsFailedTotal",
                        "Value": failed,
                        "Unit": "Count",
                        "Timestamp": now,
                        "Dimensions": dimensions,
                    },
                    {
                        "MetricName": "LateArrivalsPending",
                        "Value": late,
                        "Unit": "Count",
                        "Timestamp": now,
                        "Dimensions": dimensions,
                    },
                    {
                        "MetricName": "ThroughputPerSecond",
                        "Value": round(throughput, 2),
                        "Unit": "Count/Second",
                        "Timestamp": now,
                        "Dimensions": dimensions,
                    },
                ],
            )
            logger.debug(
                "Metrics published — sent=%d failed=%d late_pending=%d throughput=%.1f/s",
                sent, failed, late, throughput,
            )
        except ClientError as exc:
            # Never let metric publishing crash the simulator
            logger.warning("CloudWatch publish failed (non-fatal): %s", exc)
