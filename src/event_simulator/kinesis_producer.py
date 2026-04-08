"""
Kinesis producer with batching, partition-key routing, and retry logic.

Key design decisions:
- Partition key = user_id: guarantees all events from one user land on the
  same shard, preserving ordering within a user's session.
- Batch size = 500: Kinesis put_records maximum per API call.
- Exponential backoff on ProvisionedThroughputExceededException — although
  on-demand mode rarely throttles, the retry logic is good practice.
"""

import json
import logging
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class KinesisProducer:
    """Publishes event dicts to a Kinesis Data Stream in batches."""

    MAX_BATCH_SIZE = 500          # Kinesis put_records hard limit
    MAX_RECORD_SIZE_BYTES = 1_048_576  # 1MB per record
    MAX_RETRIES = 5
    BASE_BACKOFF_SECONDS = 0.5

    def __init__(self, stream_name: str, region: str = "us-east-1"):
        self.stream_name = stream_name
        self.client = boto3.client("kinesis", region_name=region)
        logger.info("KinesisProducer initialised — stream: %s", stream_name)

    def publish_batch(self, events: list[dict]) -> dict:
        """
        Publish a list of event dicts to Kinesis.
        Automatically splits into <=500 record chunks.
        Returns a summary dict with sent/failed counts.
        """
        total_sent = 0
        total_failed = 0

        for chunk_start in range(0, len(events), self.MAX_BATCH_SIZE):
            chunk = events[chunk_start : chunk_start + self.MAX_BATCH_SIZE]
            records = self._build_records(chunk)
            sent, failed = self._put_records_with_retry(records)
            total_sent += sent
            total_failed += failed

        return {"sent": total_sent, "failed": total_failed}

    def _build_records(self, events: list[dict]) -> list[dict]:
        """Convert event dicts to Kinesis PutRecords format."""
        records = []
        for event in events:
            payload = json.dumps(event).encode("utf-8")
            if len(payload) > self.MAX_RECORD_SIZE_BYTES:
                logger.warning("Event %s exceeds 1MB — skipping", event.get("event_id"))
                continue
            records.append({
                "Data": payload,
                "PartitionKey": str(event.get("user_id", "unknown")),
            })
        return records

    def _put_records_with_retry(
        self, records: list[dict], attempt: int = 0
    ) -> tuple[int, int]:
        """
        Call put_records, retry failed records with exponential backoff.
        Returns (sent_count, failed_count).
        """
        if not records:
            return 0, 0

        try:
            response = self.client.put_records(
                StreamName=self.stream_name,
                Records=records,
            )
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("ProvisionedThroughputExceededException", "ThrottlingException"):
                if attempt >= self.MAX_RETRIES:
                    logger.error("Max retries exceeded — dropping %d records", len(records))
                    return 0, len(records)
                backoff = self.BASE_BACKOFF_SECONDS * (2 ** attempt)
                logger.warning("Throttled — retrying in %.1fs (attempt %d)", backoff, attempt + 1)
                time.sleep(backoff)
                return self._put_records_with_retry(records, attempt + 1)
            raise

        failed_records = [
            records[i]
            for i, r in enumerate(response["Records"])
            if r.get("ErrorCode")
        ]

        if failed_records and attempt < self.MAX_RETRIES:
            backoff = self.BASE_BACKOFF_SECONDS * (2 ** attempt)
            time.sleep(backoff)
            retry_sent, retry_failed = self._put_records_with_retry(failed_records, attempt + 1)
            return (len(records) - len(failed_records) + retry_sent), retry_failed

        return len(records) - len(failed_records), len(failed_records)
