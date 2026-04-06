#!/usr/bin/env bash
# =============================================================================
# check_env.sh — Verify all required environment variables are set
#
# Run before starting any pipeline component to catch missing config early.
# Usage:
#   bash scripts/check_env.sh               # check all vars
#   bash scripts/check_env.sh --simulator   # check simulator vars only
#   bash scripts/check_env.sh --lambda      # check lambda vars only
#   bash scripts/check_env.sh --spark       # check spark vars only
#   bash scripts/check_env.sh --dashboard   # check dashboard vars only
# =============================================================================

set -euo pipefail

GREEN="\033[32m"
RED="\033[31m"
YELLOW="\033[33m"
BOLD="\033[1m"
RESET="\033[0m"

COMPONENT="${1:-}"
ERRORS=0

check() {
    local var="$1"
    local description="$2"
    local value="${!var:-}"

    if [ -n "$value" ]; then
        printf "  ${GREEN}✓${RESET} %-40s = %s\n" "$var" "$value"
    else
        printf "  ${RED}✗${RESET} %-40s ${RED}NOT SET${RESET}  ($description)\n" "$var"
        ERRORS=$((ERRORS + 1))
    fi
}

check_aws_credentials() {
    echo ""
    echo "${BOLD}AWS Credentials${RESET}"
    if aws sts get-caller-identity > /dev/null 2>&1; then
        ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
        REGION="${AWS_REGION:-us-east-1}"
        printf "  ${GREEN}✓${RESET} AWS credentials valid  (account=%s region=%s)\n" "$ACCOUNT" "$REGION"
    else
        printf "  ${RED}✗${RESET} AWS credentials INVALID — run: aws configure\n"
        ERRORS=$((ERRORS + 1))
    fi
}

print_header() {
    echo ""
    echo "${BOLD}============================================${RESET}"
    echo "${BOLD} Environment Check: $1${RESET}"
    echo "${BOLD}============================================${RESET}"
}

check_simulator() {
    print_header "Event Simulator"
    check "KINESIS_STREAM_NAME"  "Kinesis stream name (terraform output kinesis_stream_name)"
    check "AWS_REGION"           "AWS region (default: us-east-1)"
    echo ""
    echo "  ${YELLOW}Optional:${RESET}"
    printf "  ${YELLOW}?${RESET} %-40s = %s\n" "SIMULATOR_DEFAULT_RATE" "${SIMULATOR_DEFAULT_RATE:-100 (default)}"
    printf "  ${YELLOW}?${RESET} %-40s = %s\n" "SIMULATOR_LATE_ARRIVAL_PCT" "${SIMULATOR_LATE_ARRIVAL_PCT:-0.05 (default)}"
}

check_lambda() {
    print_header "Lambda Sessionizer (deployed env vars)"
    check "DYNAMODB_TABLE_NAME"  "DynamoDB session table (terraform output dynamodb_table_name)"
    check "S3_BUCKET"            "Raw events S3 bucket (terraform output raw_s3_bucket)"
    check "AWS_REGION"           "AWS region"
    echo ""
    echo "  ${YELLOW}Note: Lambda env vars are set by Terraform, not locally.${RESET}"
    echo "  ${YELLOW}Run: terraform output  to see all deployed values.${RESET}"
}

check_spark() {
    print_header "Spark / EMR Serverless"
    check "EMR_APPLICATION_ID"      "EMR Serverless app ID (terraform output emr_application_id)"
    check "EMR_EXECUTION_ROLE_ARN"  "EMR IAM role ARN (terraform output emr_execution_role_arn)"
    check "S3_BUCKET"               "S3 bucket for Spark input/output"
    check "AWS_REGION"              "AWS region"
}

check_dashboard() {
    print_header "Accuracy/Latency Dashboard"
    check "ATHENA_DATABASE"       "Athena database name (clickstream_dev)"
    check "ATHENA_WORKGROUP"      "Athena workgroup (clickstream-dev)"
    check "ATHENA_OUTPUT_BUCKET"  "Athena query results bucket (terraform output)"
    check "AWS_REGION"            "AWS region"
}

check_terraform() {
    print_header "Terraform"
    if command -v terraform &> /dev/null; then
        TF_VERSION=$(terraform version -json | python3 -c "import json,sys; print(json.load(sys.stdin)['terraform_version'])" 2>/dev/null || terraform version | head -1)
        printf "  ${GREEN}✓${RESET} terraform found: %s\n" "$TF_VERSION"
    else
        printf "  ${RED}✗${RESET} terraform NOT FOUND — install from https://developer.hashicorp.com/terraform/install\n"
        ERRORS=$((ERRORS + 1))
    fi

    if [ -d "terraform" ]; then
        WS=$(cd terraform && terraform workspace show 2>/dev/null || echo "not initialised")
        printf "  ${GREEN}✓${RESET} %-40s = %s\n" "Active workspace" "$WS"
        if [ "$WS" = "prod" ]; then
            printf "  ${YELLOW}⚠${RESET}  You are in PROD workspace. Be careful.\n"
        fi
    fi
}

# ─── Run checks ──────────────────────────────────────────────────────────────

check_aws_credentials

case "$COMPONENT" in
    --simulator) check_simulator ;;
    --lambda)    check_lambda    ;;
    --spark)     check_spark     ;;
    --dashboard) check_dashboard ;;
    *)
        check_simulator
        check_spark
        check_dashboard
        check_terraform
        ;;
esac

echo ""
echo "${BOLD}============================================${RESET}"
if [ "$ERRORS" -eq 0 ]; then
    echo "${GREEN}${BOLD} ✓ All checks passed${RESET}"
else
    echo "${RED}${BOLD} ✗ $ERRORS issue(s) found${RESET}"
    echo ""
    echo "  Populate missing vars by running:"
    echo "    source .env"
    echo "  Or copy from Terraform outputs:"
    echo "    cd terraform && terraform output"
fi
echo "${BOLD}============================================${RESET}"
echo ""

exit "$ERRORS"
