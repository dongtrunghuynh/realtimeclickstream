"""Unit tests for the DynamoDB shared client."""

import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/lambda/shared"))

from dynamodb_client import DynamoDBClient, _convert_floats

# ---------------------------------------------------------------------------
# _convert_floats helper
# ---------------------------------------------------------------------------

class TestConvertFloats:
    def test_float_becomes_decimal(self):
        result = _convert_floats(3.14)
        assert isinstance(result, Decimal)
        assert result == Decimal("3.14")

    def test_dict_floats_converted_recursively(self):
        result = _convert_floats({"price": 9.99, "count": 5, "label": "test"})
        assert isinstance(result["price"], Decimal)
        assert result["count"] == 5          # int unchanged
        assert result["label"] == "test"     # str unchanged

    def test_list_floats_converted(self):
        result = _convert_floats([1.5, 2.5, "hello"])
        assert result[0] == Decimal("1.5")
        assert result[2] == "hello"

    def test_nested_structure(self):
        result = _convert_floats({"session": {"cart_total": 29.99, "items": [9.99, 19.99]}})
        assert isinstance(result["session"]["cart_total"], Decimal)
        assert isinstance(result["session"]["items"][0], Decimal)


# ---------------------------------------------------------------------------
# DynamoDBClient tests (mocked table)
# ---------------------------------------------------------------------------

class TestDynamoDBClient:

    @pytest.fixture
    def mock_table(self):
        with patch("dynamodb_client.boto3.resource") as mock_resource:
            mock_table = MagicMock()
            mock_resource.return_value.Table.return_value = mock_table
            yield mock_table

    def test_get_session_returns_item(self, mock_table):
        mock_table.get_item.return_value = {"Item": {"session_id": "sess_1", "event_count": 5}}
        client = DynamoDBClient(table_name="test-table")
        result = client.get_session("sess_1")
        assert result is not None
        assert result["session_id"] == "sess_1"

    def test_get_session_returns_none_when_missing(self, mock_table):
        mock_table.get_item.return_value = {}  # No "Item" key = item doesn't exist
        client = DynamoDBClient(table_name="test-table")
        result = client.get_session("sess_missing")
        assert result is None

    def test_put_session_writes_with_ttl(self, mock_table):
        client = DynamoDBClient(table_name="test-table")
        client.put_session("sess_1", {"event_count": 3, "cart_total": 29.99}, ttl_hours=2)

        call_args = mock_table.put_item.call_args
        item = call_args[1]["Item"]
        assert "session_id" in item
        assert "expires_at" in item
        assert isinstance(item["cart_total"], Decimal)  # float converted to Decimal

    def test_put_session_retries_on_throttle(self, mock_table):
        error = ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": ""}},
            "PutItem",
        )
        # Fail twice, succeed on third attempt
        mock_table.put_item.side_effect = [error, error, None]

        client = DynamoDBClient(table_name="test-table")
        # Should not raise — retries until success
        client.put_session("sess_1", {"event_count": 1})
        assert mock_table.put_item.call_count == 3

    def test_put_session_raises_after_max_retries(self, mock_table):
        error = ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": ""}},
            "PutItem",
        )
        mock_table.put_item.side_effect = error

        client = DynamoDBClient(table_name="test-table")
        with pytest.raises(ClientError):
            client.put_session("sess_1", {"event_count": 1})

    def test_put_session_raises_immediately_on_non_retryable_error(self, mock_table):
        error = ClientError(
            {"Error": {"Code": "ValidationException", "Message": "bad item"}},
            "PutItem",
        )
        mock_table.put_item.side_effect = error

        client = DynamoDBClient(table_name="test-table")
        with pytest.raises(ClientError):
            client.put_session("sess_1", {"event_count": 1})
        assert mock_table.put_item.call_count == 1  # no retry on validation errors
