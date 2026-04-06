#!/usr/bin/env bash
# =============================================================================
# export_dynamodb_snapshot.sh — Dump DynamoDB session state to S3 for Athena
#
# The speed layer (DynamoDB) can't be queried directly by Athena. This script
# scans the DynamoDB table and writes a daily NDJSON snapshot to S3, which
# the realtime_sessions Athena table then reads.
#
# Usage:
#   bash scripts/export_dynamodb_snapshot.sh              # today's snapshot
#   bash scripts/export_dynamodb_snapshot.sh 2024-10-15   # specific date
#
# Run this BEFORE running the accuracy/latency dashboard for a given day.
# In production, this would be triggered by EventBridge at 23:55 each day.
# =============================================================================

set -euo pipefail

DATE="${1:-$(date +%Y-%m-%d)}"
TABLE_NAME="${DYNAMODB_TABLE_NAME:-clickstream-sessions-dev}"
S3_BUCKET="${S3_BUCKET:-}"
REGION="${AWS_REGION:-us-east-1}"

if [ -z "${S3_BUCKET}" ]; then
    echo "Error: Set S3_BUCKET environment variable"
    exit 1
fi

S3_KEY="realtime-sessions/date_partition=${DATE}/snapshot.ndjson"
TMP_FILE="/tmp/dynamodb_snapshot_${DATE}.ndjson"

echo "============================================"
echo " DynamoDB → S3 Snapshot"
echo " Table:  ${TABLE_NAME}"
echo " Date:   ${DATE}"
echo " Target: s3://${S3_BUCKET}/${S3_KEY}"
echo "============================================"
echo ""

# Scan DynamoDB table and convert to NDJSON
# Uses --max-items with pagination for large tables
echo "Scanning DynamoDB table..."

> "${TMP_FILE}"  # Create/truncate temp file
LAST_EVALUATED_KEY=""
SCAN_COUNT=0

while true; do
    if [ -n "${LAST_EVALUATED_KEY}" ]; then
        RESULT=$(aws dynamodb scan \
            --table-name "${TABLE_NAME}" \
            --region "${REGION}" \
            --exclusive-start-key "${LAST_EVALUATED_KEY}" \
            --output json)
    else
        RESULT=$(aws dynamodb scan \
            --table-name "${TABLE_NAME}" \
            --region "${REGION}" \
            --output json)
    fi

    # Convert DynamoDB JSON format to plain JSON using Python
    echo "${RESULT}" | python3 -c "
import json, sys
from decimal import Decimal

data = json.load(sys.stdin)
for item in data.get('Items', []):
    # Convert DynamoDB type descriptors to plain values
    record = {}
    for k, v in item.items():
        if 'S' in v:
            record[k] = v['S']
        elif 'N' in v:
            record[k] = v['N']  # Keep as string — Athena handles the cast
        elif 'BOOL' in v:
            record[k] = str(v['BOOL']).lower()
        elif 'SS' in v:
            record[k] = v['SS']
        elif 'L' in v:
            record[k] = [list(x.values())[0] for x in v['L']]
        else:
            record[k] = str(v)
    print(json.dumps(record))
" >> "${TMP_FILE}"

    SCAN_COUNT=$((SCAN_COUNT + $(echo "${RESULT}" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('Items',[])))")))

    # Check for more pages
    LAST_EVALUATED_KEY=$(echo "${RESULT}" | python3 -c "
import json, sys
d = json.load(sys.stdin)
if 'LastEvaluatedKey' in d:
    print(json.dumps(d['LastEvaluatedKey']))
" 2>/dev/null || echo "")

    echo "  Scanned ${SCAN_COUNT} sessions..."

    if [ -z "${LAST_EVALUATED_KEY}" ]; then
        break
    fi
done

echo "  ✓ Total sessions scanned: ${SCAN_COUNT}"

# Upload to S3
echo "Uploading to S3..."
aws s3 cp "${TMP_FILE}" "s3://${S3_BUCKET}/${S3_KEY}" \
    --content-type "application/x-ndjson" \
    --region "${REGION}"

echo "  ✓ Uploaded to s3://${S3_BUCKET}/${S3_KEY}"

# Clean up temp file
rm -f "${TMP_FILE}"

echo ""
echo "============================================"
echo " ✓ Snapshot complete — ${SCAN_COUNT} sessions"
echo " Run dashboard: make dashboard DATE=${DATE}"
echo "============================================"
