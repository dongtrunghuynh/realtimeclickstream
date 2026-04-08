"""
Event Simulator — Replays REES46 clickstream data into Amazon Kinesis.

Usage:
    python simulator.py --rate 100 --duration 300
    python simulator.py --rate 50 --duration 600 --late-arrival-pct 0.08
    python simulator.py --help
"""

import argparse
import logging
import time
from pathlib import Path

import pandas as pd
from config import SimulatorConfig
from event_schema import ClickstreamEvent
from kinesis_producer import KinesisProducer
from late_arrival_injector import LateArrivalInjector
from metrics import SimulatorMetrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


class EventSimulator:
    """
    Reads REES46 CSV in chunks and replays events into Kinesis at a
    configurable rate. Optionally injects late-arriving events to simulate
    mobile clients with intermittent connectivity.
    """

    CHUNK_SIZE = 10_000  # rows per pandas chunk — avoids loading 2GB into memory

    def __init__(self, config: SimulatorConfig):
        self.config = config
        self.producer = KinesisProducer(config.stream_name, config.region)
        self.metrics  = SimulatorMetrics(config.stream_name, config.region, enabled=config.enable_cloudwatch)
        self.injector = LateArrivalInjector(
            late_arrival_pct=config.late_arrival_pct,
            min_delay_seconds=120,   # 2 min
            max_delay_seconds=900,   # 15 min
        )

    def stream(self, limit: int | None = None):
        """
        Generator: yields parsed ClickstreamEvent dicts from the CSV.
        Respects --limit for testing without processing the full 20M rows.
        """
        csv_path = Path(self.config.csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(
                f"Dataset not found at {csv_path}. "
                "Download from: https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store"
            )

        count = 0
        for chunk in pd.read_csv(csv_path, chunksize=self.CHUNK_SIZE):
            for _, row in chunk.iterrows():
                if limit and count >= limit:
                    return
                event = ClickstreamEvent.from_csv_row(row)
                if event:
                    yield event.to_dict()
                    count += 1

    def run(self):
        """
        Main loop: reads events, applies rate limiting, injects late arrivals,
        publishes to Kinesis. Runs until --duration seconds have elapsed.
        """
        logger.info(
            "Starting simulator: rate=%d/s duration=%ds late_arrival_pct=%.1f%%",
            self.config.rate,
            self.config.duration,
            self.config.late_arrival_pct * 100,
        )

        start = time.monotonic()
        batch: list[dict] = []
        sent_count = 0
        interval = 1.0 / self.config.rate  # seconds between events

        for event in self.stream():
            elapsed = time.monotonic() - start
            if elapsed >= self.config.duration:
                logger.info("Duration reached — stopping simulator")
                break

            # Apply late arrival injection.
            # maybe_delay() returns {"_held": True} for withheld events —
            # those go into the injector queue and must NOT be sent to Kinesis now.
            maybe = self.injector.maybe_delay(event)
            if not maybe.get("_held"):
                batch.append(maybe)

            # Flush late arrivals whose delay has elapsed and add them to batch.
            ready_late = self.injector.flush_ready()
            batch.extend(ready_late)

            # Publish in batches of 500 (Kinesis put_records limit)
            if len(batch) >= 500:
                result = self.producer.publish_batch(batch)
                sent_count += len(batch)
                self.metrics.record_sent(result.get("sent", 0))
                self.metrics.record_failed(result.get("failed", 0))
                self.metrics.set_late_pending(self.injector.pending_count)
                batch = []

                # Rate limiting
                time.sleep(interval * 500)

            # Periodic logging
            if sent_count > 0 and sent_count % 10_000 == 0:
                throughput = sent_count / (time.monotonic() - start)
                logger.info(
                    "Sent %d events | throughput=%.1f/s | elapsed=%.0fs",
                    sent_count,
                    throughput,
                    time.monotonic() - start,
                )

        # Flush remaining batch
        if batch:
            result = self.producer.publish_batch(batch)
            sent_count += len(batch)
            self.metrics.record_sent(result.get("sent", 0))

        self.metrics.stop()
        logger.info("Simulator complete. Total events sent: %d", sent_count)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="REES46 clickstream event simulator")
    parser.add_argument("--rate", type=int, default=100, help="Events per second")
    parser.add_argument("--duration", type=int, default=300, help="Duration in seconds")
    parser.add_argument("--late-arrival-pct", type=float, default=0.05, help="Late arrival fraction (0.0–1.0)")
    parser.add_argument("--csv-path", type=str, default="data/sample/2019-Oct.csv")
    parser.add_argument("--stream-name", type=str, default=None, help="Override KINESIS_STREAM_NAME env var")
    parser.add_argument("--region", type=str, default="us-east-1")
    parser.add_argument("--limit", type=int, default=None, help="Max events to read (for testing)")
    parser.add_argument("--no-cloudwatch", action="store_true", help="Disable CloudWatch metrics (useful in CI)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    config = SimulatorConfig.from_args(args)
    EventSimulator(config).run()
