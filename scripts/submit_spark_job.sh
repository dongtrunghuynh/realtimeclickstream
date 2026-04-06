#!/usr/bin/env bash
# =============================================================================
# submit_spark_job.sh — Submit a Spark job to EMR Serverless
#
# Usage:
#   bash scripts/submit_spark_job.sh session_stitcher 2024-10-15
#   bash scripts/submit_spark_job.sh session_stitcher        # defaults to yesterday
#
# Prerequisites:
#   - terraform output emr_application_id → set as EMR_APPLICATION_ID env var
#   - terraform output emr_execution_role_arn → set as EMR_EXECUTION_ROLE_ARN env var
#   - terraform output raw_s3_bucket → set as S3_BUCKET env var
# =============================================================================

set -euo pipefail

JOB_NAME="${1:-session_stitcher}"
DATE="${2:-$(date -d yesterday +%Y-%m-%d 2>/dev/null || date -v -1d +%Y-%m-%d)}"

# Required env vars
: "${EMR_APPLICATION_ID:?Set EMR_APPLICATION_ID from terraform output}"
: "${EMR_EXECUTION_ROLE_ARN:?Set EMR_EXECUTION_ROLE_ARN from terraform output}"
: "${S3_BUCKET:?Set S3_BUCKET from terraform output}"
REGION="${AWS_REGION:-us-east-1}"

SCRIPT_S3_PATH="s3://${S3_BUCKET}/spark-scripts/${JOB_NAME}.py"
RAW_PATH="s3://${S3_BUCKET}/events/"
OUTPUT_PATH="s3://${S3_BUCKET}-corrected/sessions/"

echo "================================================"
echo " Submitting Spark Job: ${JOB_NAME}"
echo " Date:        ${DATE}"
echo " Application: ${EMR_APPLICATION_ID}"
echo " Input:       ${RAW_PATH}"
echo " Output:      ${OUTPUT_PATH}"
echo "================================================"

# Upload the Spark script to S3
echo "Uploading Spark script to S3..."
aws s3 cp "src/spark/${JOB_NAME}.py" "${SCRIPT_S3_PATH}"
echo "  ✓ Uploaded to ${SCRIPT_S3_PATH}"

# Submit the job
echo "Submitting job to EMR Serverless..."
JOB_RUN_ID=$(aws emr-serverless start-job-run \
    --application-id "${EMR_APPLICATION_ID}" \
    --execution-role-arn "${EMR_EXECUTION_ROLE_ARN}" \
    --name "${JOB_NAME}-${DATE}" \
    --region "${REGION}" \
    --job-driver '{
        "sparkSubmit": {
            "entryPoint": "'"${SCRIPT_S3_PATH}"'",
            "entryPointArguments": [
                "--date", "'"${DATE}"'",
                "--raw-path", "'"${RAW_PATH}"'",
                "--output-path", "'"${OUTPUT_PATH}"'"
            ],
            "sparkSubmitParameters": "--conf spark.executor.cores=4 --conf spark.executor.memory=16g --conf spark.driver.cores=2 --conf spark.driver.memory=8g"
        }
    }' \
    --query jobRunId \
    --output text)

echo "  ✓ Job submitted: ${JOB_RUN_ID}"
echo ""
echo "Monitor with:"
echo "  aws emr-serverless get-job-run --application-id ${EMR_APPLICATION_ID} --job-run-id ${JOB_RUN_ID}"
echo ""
echo "View logs:"
echo "  aws logs tail /aws/emr-serverless/clickstream-reconciler-dev --follow"
echo ""

# Poll for job completion
echo "Polling for job completion (Ctrl+C to stop polling — job continues in background)..."
while true; do
    STATE=$(aws emr-serverless get-job-run \
        --application-id "${EMR_APPLICATION_ID}" \
        --job-run-id "${JOB_RUN_ID}" \
        --region "${REGION}" \
        --query 'jobRun.state' \
        --output text)

    echo "  Status: ${STATE} ($(date '+%H:%M:%S'))"

    case "${STATE}" in
        SUCCESS)
            echo ""
            echo "✓ Spark job completed successfully!"
            break
            ;;
        FAILED|CANCELLED|CANCELLING)
            echo ""
            echo "✗ Spark job ${STATE}. Check logs:"
            echo "  aws logs tail /aws/emr-serverless/clickstream-reconciler-dev"
            exit 1
            ;;
        *)
            sleep 15
            ;;
    esac
done
