"""
Dead Letter Queue (DLQ) Handler — recovers events that failed Lambda processing.

When Lambda fails to process a Kinesis record after `maximum_retry_attempts`
retries, the record is sent to an SQS DLQ (configured in Terraform).
This handler re-processes those records manually after the root cause is fixed.

Usage:
    # List DLQ messages (without deleting them)
    python src/lambda/sessionizer/dlq_handler.py --list

    # Re-process and delete from DLQ (dry-run first)
    python src/lambda/sessionizer/dlq_handler.py --reprocess --dry-run
    python src/lambda/sessionizer/dlq_handler.py --reprocess

Architecture note:
    In a production system you would trigger this Lambda automatically via
    EventBridge or a CloudWatch alarm. For this project, it's a manual script
    you run after investigating a Lambda failure.
"""

import argparse
import base64
import json
import logging
import os
import sys

import boto3

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Environment
DLQ_URL       = os.environ.get("DLQ_URL", "")
KINESIS_STREAM = os.environ.get("KINESIS_STREAM_NAME", "clickstream-events-dev")
REGION        = os.environ.get("AWS_REGION", "us-east-1")
MAX_MESSAGES  = 10  # SQS max per receive call


class DLQHandler:
    """
    Reads failed Kinesis records from SQS DLQ, parses them, and
    either logs them (--list) or re-publishes them to Kinesis (--reprocess).
    """

    def __init__(self, queue_url: str, stream_name: str, region: str):
        self.queue_url   = queue_url
        self.stream_name = stream_name
        self.sqs         = boto3.client("sqs",     region_name=region)
        self.kinesis     = boto3.client("kinesis",  region_name=region)

    def list_messages(self, max_messages: int = 50) -> list[dict]:
        """
        Peek at DLQ messages without deleting them.
        Returns parsed event dicts.
        """
        messages = []
        fetched  = 0

        while fetched < max_messages:
            batch = min(MAX_MESSAGES, max_messages - fetched)
            response = self.sqs.receive_message(
                QueueUrl            = self.queue_url,
                MaxNumberOfMessages = batch,
                WaitTimeSeconds     = 1,
                AttributeNames      = ["All"],
                MessageAttributeNames = ["All"],
            )
            raw_messages = response.get("Messages", [])
            if not raw_messages:
                break

            for msg in raw_messages:
                parsed = self._parse_dlq_message(msg)
                if parsed:
                    messages.extend(parsed)
            fetched += len(raw_messages)

        return messages

    def reprocess(self, dry_run: bool = True) -> dict:
        """
        Re-publish DLQ events back to Kinesis, then delete them from the queue.

        Args:
            dry_run: If True, log what would happen but make no changes.

        Returns:
            Dict with counts: replayed, skipped, deleted.
        """
        replayed = 0
        skipped  = 0
        deleted  = 0

        response = self.sqs.receive_message(
            QueueUrl            = self.queue_url,
            MaxNumberOfMessages = MAX_MESSAGES,
            WaitTimeSeconds     = 5,
            AttributeNames      = ["All"],
        )

        for msg in response.get("Messages", []):
            events = self._parse_dlq_message(msg)
            if not events:
                skipped += 1
                continue

            logger.info(
                "[%s] Would re-publish %d events from DLQ message %s",
                "DRY RUN" if dry_run else "LIVE",
                len(events),
                msg["MessageId"],
            )

            if not dry_run:
                kinesis_records = [
                    {
                        "Data": json.dumps(e).encode(),
                        "PartitionKey": str(e.get("user_id", "unknown")),
                    }
                    for e in events
                ]
                self.kinesis.put_records(
                    StreamName = self.stream_name,
                    Records    = kinesis_records,
                )
                replayed += len(events)

                # Delete from DLQ after successful re-publish
                self.sqs.delete_message(
                    QueueUrl      = self.queue_url,
                    ReceiptHandle = msg["ReceiptHandle"],
                )
                deleted += 1
                logger.info("Deleted DLQ message %s", msg["MessageId"])
            else:
                replayed += len(events)  # count in dry run too

        return {"replayed": replayed, "skipped": skipped, "deleted": deleted}

    def _parse_dlq_message(self, msg: dict) -> list[dict]:
        """
        Parse an SQS DLQ message body back into a list of event dicts.

        SQS DLQ messages from Lambda look like:
        {
          "requestContext": { "condition": "RetryAttemptsExhausted", ... },
          "responseContext": { "statusCode": 200 },
          "version": "1.0",
          "timestamp": "2024-10-15T10:00:00.000Z",
          "KinesisBatchInfo": {
              "shardId": "shardId-000000000000",
              "startSequenceNumber": "...",
              "endSequenceNumber": "...",
              "approximateArrivalOfFirstRecord": "...",
              "batchSize": 3,
              "streamArn": "arn:aws:kinesis:..."
          }
        }
        The actual event data is NOT in the DLQ message body — the DLQ records
        the failure metadata. You need to re-read from Kinesis using the sequence
        numbers in KinesisBatchInfo.

        For simplicity in this project, if the event data IS embedded (e.g. in
        a test or via a custom DLQ format), we parse it directly.
        """
        try:
            body = json.loads(msg.get("Body", "{}"))
        except json.JSONDecodeError:
            logger.warning("Could not parse DLQ message body: %s", msg.get("MessageId"))
            return []

        # Handle embedded Kinesis records (from bisected batches or test DLQ)
        if "Records" in body:
            events = []
            for record in body["Records"]:
                try:
                    kinesis_data = record["kinesis"]["data"]
                    payload = base64.b64decode(kinesis_data).decode("utf-8")
                    event   = json.loads(payload)
                    events.append(event)
                except (KeyError, json.JSONDecodeError, ValueError, Exception):
                    continue
            return events

        # Standard Lambda DLQ format — log the batch info for manual recovery
        if "KinesisBatchInfo" in body:
            batch_info = body["KinesisBatchInfo"]
            logger.warning(
                "Standard Lambda DLQ record — use Kinesis GetRecords to re-fetch:\n"
                "  Stream:  %s\n"
                "  Shard:   %s\n"
                "  From:    %s\n"
                "  To:      %s\n"
                "  Size:    %d\n"
                "  Failed:  %s",
                batch_info.get("streamArn"),
                batch_info.get("shardId"),
                batch_info.get("startSequenceNumber"),
                batch_info.get("endSequenceNumber"),
                batch_info.get("batchSize", 0),
                body.get("requestContext", {}).get("condition"),
            )
        return []


def main():
    parser = argparse.ArgumentParser(description="DLQ Handler — re-process failed Lambda events")
    parser.add_argument("--list",        action="store_true",  help="List DLQ messages without deleting")
    parser.add_argument("--reprocess",   action="store_true",  help="Re-publish DLQ events to Kinesis")
    parser.add_argument("--dry-run",     action="store_true",  help="Simulate reprocess without making changes")
    parser.add_argument("--queue-url",   default=DLQ_URL,      help="SQS DLQ URL (or set DLQ_URL env var)")
    parser.add_argument("--stream-name", default=KINESIS_STREAM)
    parser.add_argument("--region",      default=REGION)
    args = parser.parse_args()

    if not args.queue_url:
        logger.error("Set DLQ_URL environment variable or pass --queue-url")
        sys.exit(1)

    handler = DLQHandler(args.queue_url, args.stream_name, args.region)

    if args.list:
        messages = handler.list_messages()
        logger.info("Found %d events in DLQ:", len(messages))
        for i, event in enumerate(messages, 1):
            print(f"  [{i}] session={event.get('session_id')} "
                  f"type={event.get('event_type')} "
                  f"late={event.get('is_late_arrival')} "
                  f"time={event.get('event_time')}")

    elif args.reprocess:
        result = handler.reprocess(dry_run=args.dry_run)
        mode = "DRY RUN" if args.dry_run else "LIVE"
        logger.info("[%s] Reprocess complete: %s", mode, result)
        if args.dry_run:
            logger.info("Run without --dry-run to actually re-publish and delete")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
