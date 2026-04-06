#!/usr/bin/env bash
# =============================================================================
# athena_setup.sh — Register all Glue tables and Athena views
#
# Run once after deploying infrastructure with terraform apply.
# Substitutes your AWS account ID into all DDL statements automatically.
# =============================================================================

set -euo pipefail

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ENV="${TERRAFORM_WORKSPACE:-dev}"
REGION="${AWS_REGION:-us-east-1}"
WORKGROUP="clickstream-${ENV}"
OUTPUT_BUCKET="clickstream-athena-${ACCOUNT_ID}-${ENV}"
DATABASE="clickstream_${ENV}"

echo "============================================"
echo " Athena Setup"
echo " Account:   ${ACCOUNT_ID}"
echo " Env:       ${ENV}"
echo " Database:  ${DATABASE}"
echo " Workgroup: ${WORKGROUP}"
echo "============================================"
echo ""

run_query() {
    local description="$1"
    local sql="$2"

    echo "  Running: ${description}..."

    EXECUTION_ID=$(aws athena start-query-execution \
        --query-string "${sql}" \
        --query-execution-context "Database=${DATABASE}" \
        --work-group "${WORKGROUP}" \
        --result-configuration "OutputLocation=s3://${OUTPUT_BUCKET}/athena-setup/" \
        --region "${REGION}" \
        --query 'QueryExecutionId' \
        --output text)

    # Poll for completion
    for i in {1..30}; do
        STATE=$(aws athena get-query-execution \
            --query-execution-id "${EXECUTION_ID}" \
            --region "${REGION}" \
            --query 'QueryExecution.Status.State' \
            --output text)

        if [ "${STATE}" = "SUCCEEDED" ]; then
            echo "    ✓ Done"
            return 0
        elif [ "${STATE}" = "FAILED" ] || [ "${STATE}" = "CANCELLED" ]; then
            REASON=$(aws athena get-query-execution \
                --query-execution-id "${EXECUTION_ID}" \
                --region "${REGION}" \
                --query 'QueryExecution.Status.StateChangeReason' \
                --output text)
            echo "    ✗ Failed: ${REASON}"
            return 1
        fi
        sleep 2
    done

    echo "    ✗ Timed out waiting for query"
    return 1
}

# Substitute account ID and env into the SQL files
SCHEMA_SQL=$(sed "s/YOUR_ACCOUNT_ID/${ACCOUNT_ID}/g; s/clickstream_dev/${DATABASE}/g" \
    athena/schema/create_tables.sql)

REALTIME_SQL=$(sed "s/YOUR_ACCOUNT_ID/${ACCOUNT_ID}/g; s/clickstream_dev/${DATABASE}/g" \
    athena/views/realtime_sessions.sql)

BATCH_SQL=$(sed "s/YOUR_ACCOUNT_ID/${ACCOUNT_ID}/g; s/clickstream_dev/${DATABASE}/g" \
    athena/views/batch_sessions.sql)

COMPARE_SQL=$(sed "s/YOUR_ACCOUNT_ID/${ACCOUNT_ID}/g; s/clickstream_dev/${DATABASE}/g" \
    athena/views/accuracy_comparison.sql)

echo "Creating tables..."
run_query "raw_events table"           "$(echo "${SCHEMA_SQL}" | awk '/raw_events/,/^;/' | head -n 50)"
run_query "late_arrivals table"        "$(echo "${SCHEMA_SQL}" | awk '/late_arrivals/,/^;/' | head -n 40)"
run_query "batch_sessions table"       "$(echo "${SCHEMA_SQL}" | awk '/batch_sessions/,/^;/' | head -n 40)"
run_query "realtime_sessions table"    "$(echo "${SCHEMA_SQL}" | awk '/realtime_sessions_raw/,/^;/' | head -n 40)"
run_query "restatement_audit table"    "$(echo "${SCHEMA_SQL}" | awk '/restatement_audit/,/^;/' | head -n 40)"

echo ""
echo "============================================"
echo " ✓ Athena setup complete!"
echo ""
echo " Open the Athena console to query your data:"
echo " https://${REGION}.console.aws.amazon.com/athena/home?region=${REGION}#/query-editor"
echo " Workgroup: ${WORKGROUP}  |  Database: ${DATABASE}"
echo "============================================"
