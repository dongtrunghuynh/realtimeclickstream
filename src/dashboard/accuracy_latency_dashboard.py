"""
Accuracy / Latency Tradeoff Dashboard — the ⭐ standout deliverable.

Queries both the speed layer (DynamoDB export via Athena) and the batch
layer (corrected Parquet via Athena) and prints a side-by-side comparison.

This script is what you demo in interviews. Run it after:
1. The event simulator has run for at least 1 hour
2. The nightly Spark batch reconciler has completed

Usage:
    python src/dashboard/accuracy_latency_dashboard.py --date 2024-10-15
    python src/dashboard/accuracy_latency_dashboard.py --date 2024-10-15 --output dashboard_results.csv
"""

import argparse
import csv
import logging
import os
import sys
import time

import boto3

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

ATHENA_DATABASE = os.environ.get("ATHENA_DATABASE", "clickstream_dev")
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "clickstream-dev")
ATHENA_OUTPUT = os.environ.get("ATHENA_OUTPUT_BUCKET", "")  # set in env


class AthenaQueryRunner:
    """Runs Athena queries synchronously and returns results as list of dicts."""

    POLL_INTERVAL = 2  # seconds
    TIMEOUT = 300       # seconds

    def __init__(self, workgroup: str, output_location: str, region: str = "us-east-1"):
        self.workgroup = workgroup
        self.output_location = output_location
        self.client = boto3.client("athena", region_name=region)

    def run(self, query: str) -> list[dict]:
        """Execute a query and return all rows as list of dicts."""
        execution_id = self._start(query)
        self._wait(execution_id)
        return self._fetch_results(execution_id)

    def _start(self, query: str) -> str:
        response = self.client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": ATHENA_DATABASE},
            WorkGroup=self.workgroup,
            ResultConfiguration={"OutputLocation": self.output_location},
        )
        return response["QueryExecutionId"]

    def _wait(self, execution_id: str) -> None:
        start = time.monotonic()
        while True:
            response = self.client.get_query_execution(QueryExecutionId=execution_id)
            state = response["QueryExecution"]["Status"]["State"]
            if state in ("SUCCEEDED",):
                return
            if state in ("FAILED", "CANCELLED"):
                reason = response["QueryExecution"]["Status"].get("StateChangeReason", "unknown")
                raise RuntimeError(f"Athena query {state}: {reason}")
            if time.monotonic() - start > self.TIMEOUT:
                raise TimeoutError(f"Athena query timed out after {self.TIMEOUT}s")
            time.sleep(self.POLL_INTERVAL)

    def _fetch_results(self, execution_id: str) -> list[dict]:
        rows = []
        paginator = self.client.get_paginator("get_query_results")
        pages = paginator.paginate(QueryExecutionId=execution_id)

        columns = None
        for page in pages:
            result_rows = page["ResultSet"]["Rows"]
            if columns is None:
                columns = [col["VarCharValue"] for col in result_rows[0]["Data"]]
                result_rows = result_rows[1:]  # skip header row

            for row in result_rows:
                values = [cell.get("VarCharValue", "") for cell in row["Data"]]
                rows.append(dict(zip(columns, values, strict=False)))

        return rows


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

SPEED_LAYER_QUERY = """
-- Real-time session metrics from the speed layer (DynamoDB → S3 export)
SELECT
    COUNT(DISTINCT session_id)                          AS total_sessions,
    SUM(CAST(cart_total AS DOUBLE))                     AS total_cart_value,
    SUM(CAST(conversion_value AS DOUBLE))               AS total_revenue,
    SUM(CAST(event_count AS BIGINT))                    AS total_events,
    COUNT(DISTINCT CASE WHEN converted = 'true'
          THEN session_id END)                          AS converted_sessions,
    AVG(CAST(duration_seconds AS DOUBLE))               AS avg_session_duration_seconds
FROM realtime_sessions
WHERE date_partition = '{date}'
"""

BATCH_LAYER_QUERY = """
-- Corrected session metrics from the batch layer (Spark reconciled)
SELECT
    COUNT(DISTINCT batch_session_id)                    AS total_sessions,
    SUM(cart_total)                                     AS total_cart_value,
    SUM(conversion_value)                               AS total_revenue,
    SUM(CAST(event_count AS BIGINT))                    AS total_events,
    COUNT(DISTINCT CASE WHEN converted THEN batch_session_id END) AS converted_sessions,
    AVG(CAST(duration_seconds AS DOUBLE))               AS avg_session_duration_seconds
FROM batch_sessions
WHERE year = CAST(SPLIT('{date}', '-')[1] AS INT)
  AND month = CAST(SPLIT('{date}', '-')[2] AS INT)
  AND day = CAST(SPLIT('{date}', '-')[3] AS INT)
"""

RESTATEMENT_QUERY = """
-- How many sessions were affected by late arrivals?
SELECT
    COUNT(*)                                            AS total_sessions_compared,
    SUM(CASE WHEN had_restatement THEN 1 ELSE 0 END)   AS sessions_restated,
    AVG(revenue_discrepancy)                            AS avg_revenue_discrepancy,
    MAX(revenue_discrepancy)                            AS max_revenue_discrepancy,
    SUM(revenue_discrepancy)                            AS total_revenue_restated,
    AVG(event_count_discrepancy)                        AS avg_event_count_discrepancy
FROM restatement_audit
WHERE year = CAST(SPLIT('{date}', '-')[1] AS INT)
  AND month = CAST(SPLIT('{date}', '-')[2] AS INT)
  AND day = CAST(SPLIT('{date}', '-')[3] AS INT)
"""


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def _safe_float(val: str, default: float = 0.0) -> float:
    try:
        return float(val) if val else default
    except ValueError:
        return default


def _safe_int(val: str, default: int = 0) -> int:
    try:
        return int(float(val)) if val else default
    except ValueError:
        return default


def render_report(
    speed: dict,
    batch: dict,
    restatement: dict,
    date: str,
) -> str:
    """Render the side-by-side comparison table as a string."""

    rt_sessions = _safe_int(speed.get("total_sessions", "0"))
    batch_sessions = _safe_int(batch.get("total_sessions", "0"))
    rt_revenue = _safe_float(speed.get("total_revenue", "0"))
    batch_revenue = _safe_float(batch.get("total_revenue", "0"))
    rt_conv_rate = (
        _safe_int(speed.get("converted_sessions", "0")) / rt_sessions * 100
        if rt_sessions else 0.0
    )
    batch_conv_rate = (
        _safe_int(batch.get("converted_sessions", "0")) / batch_sessions * 100
        if batch_sessions else 0.0
    )
    rt_duration = _safe_float(speed.get("avg_session_duration_seconds", "0"))
    batch_duration = _safe_float(batch.get("avg_session_duration_seconds", "0"))

    restated = _safe_int(restatement.get("sessions_restated", "0"))
    total_compared = _safe_int(restatement.get("total_sessions_compared", "0"))
    restate_pct = (restated / total_compared * 100) if total_compared else 0.0
    avg_rev_disc = _safe_float(restatement.get("avg_revenue_discrepancy", "0"))
    total_rev_restated = _safe_float(restatement.get("total_revenue_restated", "0"))

    lines = [
        "",
        "=" * 70,
        "  LAMBDA ARCHITECTURE — ACCURACY / LATENCY REPORT",
        f"  Date: {date}",
        "=" * 70,
        f"  {'Metric':<30} {'Speed Layer':>15} {'Batch Layer':>15}",
        f"  {'':─<30} {'(DynamoDB)':>15} {'(Athena — corrected)':>20}",
        f"  {'Total Sessions':<30} {rt_sessions:>15,} {batch_sessions:>15,}",
        f"  {'Total Revenue':<30} {f'${rt_revenue:,.2f}':>15} {f'${batch_revenue:,.2f}':>15}",
        f"  {'Conversion Rate':<30} {f'{rt_conv_rate:.1f}%':>15} {f'{batch_conv_rate:.1f}%':>15}",
        f"  {'Avg Session Duration':<30} {f'{rt_duration:.0f}s':>15} {f'{batch_duration:.0f}s':>15}",
        f"  {'Latency':<30} {'< 30 seconds':>15} {'~8 hours':>15}",
        "",
        "  RESTATEMENT ANALYSIS",
        f"  {'':─<60}",
        f"  Sessions requiring restatement: {restated:,} / {total_compared:,} ({restate_pct:.1f}%)",
        f"  Avg revenue discrepancy per restated session: ${avg_rev_disc:.2f}",
        f"  Total revenue restated: ${total_rev_restated:,.2f}",
        f"  Revenue error in speed layer: {abs(rt_revenue - batch_revenue) / batch_revenue * 100:.2f}%"
        if batch_revenue else "  Revenue error: N/A",
        "",
        "  INTERPRETATION",
        f"  {'':─<60}",
        f"  The speed layer had a {restate_pct:.1f}% session restatement rate.",
        f"  This means {100 - restate_pct:.1f}% of sessions were accurately captured",
        "  in real-time — good enough for live dashboards and A/B tests.",
        "  The batch layer provides ground truth for financial reporting.",
        "=" * 70,
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Date to analyse (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default=None, help="Save results to CSV")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    output_bucket = f"s3://{ATHENA_OUTPUT}/athena-results/"
    if not ATHENA_OUTPUT:
        logger.error("Set ATHENA_OUTPUT_BUCKET environment variable")
        sys.exit(1)

    runner = AthenaQueryRunner(ATHENA_WORKGROUP, output_bucket, args.region)

    logger.info("Querying speed layer...")
    speed_rows = runner.run(SPEED_LAYER_QUERY.format(date=args.date))
    speed = speed_rows[0] if speed_rows else {}

    logger.info("Querying batch layer...")
    batch_rows = runner.run(BATCH_LAYER_QUERY.format(date=args.date))
    batch = batch_rows[0] if batch_rows else {}

    logger.info("Querying restatement audit...")
    restatement_rows = runner.run(RESTATEMENT_QUERY.format(date=args.date))
    restatement = restatement_rows[0] if restatement_rows else {}

    report = render_report(speed, batch, restatement, args.date)
    print(report)

    if args.output:
        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["metric", "speed_layer", "batch_layer"])
            writer.writeheader()
            for key in speed:
                writer.writerow({
                    "metric": key,
                    "speed_layer": speed.get(key, ""),
                    "batch_layer": batch.get(key, ""),
                })
        logger.info("Results saved to %s", args.output)


if __name__ == "__main__":
    main()
