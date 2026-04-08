"""
Integration test fixtures — require a live AWS dev environment.

These fixtures are ONLY loaded when running tests/integration/.
They use real boto3 clients with credentials from the environment.

Prerequisites:
    export KINESIS_STREAM_NAME  (from: terraform output -raw kinesis_stream_name)
    export DYNAMODB_TABLE_NAME  (from: terraform output -raw dynamodb_table_name)
    export S3_BUCKET            (from: terraform output -raw raw_s3_bucket)
    export AWS_REGION=us-east-1

Run:
    pytest tests/integration/ -v -m integration
"""

import os

import boto3
import pytest


def _require_env(var: str) -> str:
    """Return env var value or skip the test with a clear message."""
    val = os.environ.get(var)
    if not val:
        pytest.skip(
            f"Integration test requires {var} environment variable. "
            f"Run 'terraform output {var.lower()}' and export it."
        )
    return val


# ─── AWS client fixtures ──────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def aws_region() -> str:
    return os.environ.get("AWS_REGION", "us-east-1")


@pytest.fixture(scope="session")
def kinesis_stream_name() -> str:
    return _require_env("KINESIS_STREAM_NAME")


@pytest.fixture(scope="session")
def dynamodb_table_name() -> str:
    return _require_env("DYNAMODB_TABLE_NAME")


@pytest.fixture(scope="session")
def s3_bucket() -> str:
    return _require_env("S3_BUCKET")


@pytest.fixture(scope="session")
def kinesis_client(aws_region):
    return boto3.client("kinesis", region_name=aws_region)


@pytest.fixture(scope="session")
def dynamodb_table(dynamodb_table_name, aws_region):
    resource = boto3.resource("dynamodb", region_name=aws_region)
    return resource.Table(dynamodb_table_name)


@pytest.fixture(scope="session")
def s3_client(aws_region):
    return boto3.client("s3", region_name=aws_region)


# ─── Smoke check ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def verify_infrastructure(kinesis_client, kinesis_stream_name, dynamodb_table):
    """
    Verify the dev infrastructure is actually running before any integration test.
    Skips the entire session if resources aren't deployed.
    """
    try:
        response = kinesis_client.describe_stream_summary(StreamName=kinesis_stream_name)
        status = response["StreamDescriptionSummary"]["StreamStatus"]
        if status != "ACTIVE":
            pytest.skip(f"Kinesis stream {kinesis_stream_name} is {status}, not ACTIVE. Deploy with: make tf-apply")
    except Exception as exc:
        pytest.skip(f"Cannot reach Kinesis: {exc}. Deploy with: make tf-apply")

    try:
        dynamodb_table.load()
    except Exception as exc:
        pytest.skip(f"Cannot reach DynamoDB: {exc}. Deploy with: make tf-apply")
