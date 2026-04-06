#!/usr/bin/env bash
# =============================================================================
# run_full_pipeline.sh — Complete end-to-end pipeline demo
#
# This script runs all five stages of the pipeline in sequence and produces
# the accuracy/latency dashboard at the end. Use this to generate the numbers
# for docs/tradeoffs.md and for live demos in interviews.
#
# Expected runtime: ~75 minutes total (1hr simulation + ~10min Spark + ~5min dashboard)
# Expected cost:    ~$0.30–0.50 for a full run
#
# Usage:
#   bash scripts/run_full_pipeline.sh
#   bash scripts/run_full_pipeline.sh --rate 500 --duration 1800  # 30min at 500/s
#   bash scripts/run_full_pipeline.sh --quick                      # 5min smoke test
#
# Prerequisites (all env vars set — see .env.example):
#   source .env
#   terraform apply -var-file=environments/dev.tfvars (infra must be deployed)
# =============================================================================

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
RATE=200
DURATION=3600       # 1 hour — generates a realistic day's worth of data
LATE_PCT=0.08       # 8% late arrivals — produces visible restatements
QUICK=false
DATE=$(date +%Y-%m-%d)

# ── Args ────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rate)     RATE="$2";     shift 2 ;;
    --duration) DURATION="$2"; shift 2 ;;
    --late-pct) LATE_PCT="$2"; shift 2 ;;
    --quick)    QUICK=true; RATE=100; DURATION=300; LATE_PCT=0.10; shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# ── Env checks ──────────────────────────────────────────────────────────────
: "${KINESIS_STREAM_NAME:?Set KINESIS_STREAM_NAME (from terraform output)}"
: "${DYNAMODB_TABLE_NAME:?Set DYNAMODB_TABLE_NAME (from terraform output)}"
: "${S3_BUCKET:?Set S3_BUCKET (from terraform output)}"
: "${EMR_APPLICATION_ID:?Set EMR_APPLICATION_ID (from terraform output)}"
: "${EMR_EXECUTION_ROLE_ARN:?Set EMR_EXECUTION_ROLE_ARN (from terraform output)}"
: "${ATHENA_OUTPUT_BUCKET:?Set ATHENA_OUTPUT_BUCKET (from terraform output)}"

REGION="${AWS_REGION:-us-east-1}"

# ── Helpers ─────────────────────────────────────────────────────────────────
step() { echo ""; echo "══════════════════════════════════════════════════════"; echo "  STEP $1: $2"; echo "══════════════════════════════════════════════════════"; }
ok()   { echo "  ✓ $*"; }
ts()   { date '+%H:%M:%S'; }

# ── START ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Clickstream Pipeline — Full End-to-End Run         ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Date:       ${DATE}                              ║"
printf "║  Rate:       %-10s events/sec                  ║\n" "${RATE}"
printf "║  Duration:   %-10s seconds                      ║\n" "${DURATION}"
printf "║  Late %%:     %-10s%%                            ║\n" "$(echo "$LATE_PCT * 100" | bc)"
printf "║  Quick mode: %-10s                              ║\n" "${QUICK}"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

PIPELINE_START=$(date +%s)

# ─────────────────────────────────────────────────────────────────────────────
step 1 "Verify infrastructure is deployed"
# ─────────────────────────────────────────────────────────────────────────────
echo "  Checking Kinesis stream..."
aws kinesis describe-stream-summary \
    --stream-name "$KINESIS_STREAM_NAME" \
    --query 'StreamDescriptionSummary.StreamStatus' \
    --output text | grep -q ACTIVE && ok "Kinesis stream ACTIVE" || { echo "  ✗ Stream not active"; exit 1; }

echo "  Checking Lambda function..."
aws lambda get-function \
    --function-name "clickstream-sessionizer-dev" \
    --query 'Configuration.State' \
    --output text | grep -q Active && ok "Lambda ACTIVE" || { echo "  ✗ Lambda not active"; exit 1; }

echo "  Checking DynamoDB table..."
aws dynamodb describe-table \
    --table-name "$DYNAMODB_TABLE_NAME" \
    --query 'Table.TableStatus' \
    --output text | grep -q ACTIVE && ok "DynamoDB ACTIVE" || { echo "  ✗ DynamoDB not active"; exit 1; }

ok "All infrastructure ready"

# ─────────────────────────────────────────────────────────────────────────────
step 2 "Run event simulator (${DURATION}s at ${RATE} events/s, ${LATE_PCT} late)"
# ─────────────────────────────────────────────────────────────────────────────
echo "  Started at $(ts) — will finish at $(date -d "+${DURATION} seconds" '+%H:%M:%S' 2>/dev/null || date -v +${DURATION}S '+%H:%M:%S')"
echo "  Watch Lambda logs in another terminal: make lambda-logs"
echo ""

python src/event_simulator/simulator.py \
    --rate       "$RATE" \
    --duration   "$DURATION" \
    --late-arrival-pct "$LATE_PCT"

ok "Simulator complete at $(ts)"

# Wait for Lambda to finish processing the last batch (1 polling interval)
echo "  Waiting 10s for Lambda to process final batch..."
sleep 10

# ─────────────────────────────────────────────────────────────────────────────
step 3 "Export DynamoDB speed-layer snapshot to S3"
# ─────────────────────────────────────────────────────────────────────────────
echo "  Scanning DynamoDB sessions and writing to S3..."
bash scripts/export_dynamodb_snapshot.sh "$DATE"
ok "Snapshot written to s3://${S3_BUCKET}/realtime-sessions/date_partition=${DATE}/"

# ─────────────────────────────────────────────────────────────────────────────
step 4 "Run Spark batch reconciler"
# ─────────────────────────────────────────────────────────────────────────────
echo "  Submitting session_stitcher to EMR Serverless..."
bash scripts/submit_spark_job.sh session_stitcher "$DATE"
ok "Session stitcher complete"

echo "  Submitting late_arrival_handler to EMR Serverless..."
bash scripts/submit_spark_job.sh late_arrival_handler "$DATE"
ok "Late arrival handler complete"

# ─────────────────────────────────────────────────────────────────────────────
step 5 "Generate accuracy/latency dashboard"
# ─────────────────────────────────────────────────────────────────────────────
OUTPUT_CSV="dashboard_${DATE}.csv"
python src/dashboard/accuracy_latency_dashboard.py \
    --date   "$DATE" \
    --output "$OUTPUT_CSV"

ok "Dashboard saved to ${OUTPUT_CSV}"

# ─────────────────────────────────────────────────────────────────────────────
PIPELINE_END=$(date +%s)
ELAPSED=$(( PIPELINE_END - PIPELINE_START ))
MINUTES=$(( ELAPSED / 60 ))
SECONDS=$(( ELAPSED % 60 ))

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║   Pipeline run complete!                             ║"
printf "║   Total time: %dm %ds                               ║\n" "$MINUTES" "$SECONDS"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Next steps:                                         ║"
echo "║  1. Open dashboard_${DATE}.csv                 ║"
echo "║  2. Fill in docs/tradeoffs.md with the numbers      ║"
echo "║  3. Run: make tf-destroy  (bring cost to \$0)        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
