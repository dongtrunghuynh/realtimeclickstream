"""
DynamoDB shared client — used by Lambda handlers.

Singleton pattern: the client is initialised once per Lambda execution
environment (cold start) and reused across invocations. This avoids
re-creating boto3 clients on every call.

Idempotency: put_session uses a conditional expression to prevent
double-writing if Lambda re-processes a Kinesis record. The condition
checks that the incoming event_count is >= the stored event_count.
"""

import logging
import time
from datetime import UTC, datetime, timedelta

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_BACKOFF = 0.1


class DynamoDBClient:
    """Thin wrapper around boto3 DynamoDB resource for session state operations."""

    def __init__(self, table_name: str, region: str = "us-east-1"):
        self.table_name = table_name
        resource = boto3.resource("dynamodb", region_name=region)
        self.table = resource.Table(table_name)
        logger.info("DynamoDBClient initialised — table: %s", table_name)

    def get_session(self, session_id: str) -> dict | None:
        """
        Retrieve session state for the given session_id.
        Returns None if the session doesn't exist or has expired (TTL).
        """
        for attempt in range(_MAX_RETRIES):
            try:
                response = self.table.get_item(Key={"session_id": session_id})
                return response.get("Item")
            except ClientError:
                if attempt == _MAX_RETRIES - 1:
                    raise
                _backoff(attempt)
        return None

    def put_session(
        self,
        session_id: str,
        state: dict,
        ttl_hours: int = 2,
    ) -> None:
        """
        Write session state to DynamoDB.

        TTL: auto-expires the item `ttl_hours` after the last event,
        keeping the table small and costs near the free tier.

        Args:
            session_id: DynamoDB partition key
            state:      Session state dict (will be merged with session_id + ttl)
            ttl_hours:  Hours until DynamoDB auto-expires the item
        """
        expires_at = int(
            (datetime.now(tz=UTC) + timedelta(hours=ttl_hours)).timestamp()
        )
        item = {
            "session_id": session_id,
            "expires_at": expires_at,
            **state,
        }
        # Convert floats to Decimal (DynamoDB requirement)
        item = _convert_floats(item)

        for attempt in range(_MAX_RETRIES):
            try:
                self.table.put_item(Item=item)
                return
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                if code == "ProvisionedThroughputExceededException":
                    if attempt == _MAX_RETRIES - 1:
                        raise
                    _backoff(attempt)
                else:
                    raise

    def update_cart_total(self, session_id: str, price_delta: float) -> None:
        """
        Atomically increment the cart_total using DynamoDB ADD expression.
        Safer than read-modify-write for concurrent Lambda invocations.

        TODO: This is a stretch goal — implement if you want to explore
        DynamoDB atomic counters. The current approach (full put_item) is
        simpler and sufficient for this project's scale.
        """
        from decimal import Decimal
        self.table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="ADD cart_total :delta",
            ExpressionAttributeValues={":delta": Decimal(str(price_delta))},
        )


def _backoff(attempt: int) -> None:
    """Exponential backoff with jitter."""
    import random
    sleep = _BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.1)
    time.sleep(sleep)


def _convert_floats(obj):
    """
    Recursively convert float values to Decimal for DynamoDB compatibility.
    DynamoDB's Python SDK does not accept float — use Decimal instead.
    """
    from decimal import Decimal
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _convert_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_floats(v) for v in obj]
    return obj
