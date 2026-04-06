#!/usr/bin/env bash
# =============================================================================
# teardown_dev.sh — Destroy all dev resources (bring cost to $0)
#
# RUN THIS AT THE END OF EVERY DEV SESSION.
#
# What gets destroyed:
#   - Kinesis Data Stream
#   - Lambda function + event source mapping
#   - DynamoDB table (data lost — that's fine in dev)
#   - S3 buckets + all objects (force_destroy = true in dev)
#   - EMR Serverless application
#   - Athena workgroup
#   - Glue database
#   - CloudWatch log groups
#   - IAM roles and policies
#
# What SURVIVES:
#   - Terraform state bucket (created manually in setup.sh)
#   - Your local code and data
# =============================================================================

set -euo pipefail

echo "============================================"
echo " DEV TEARDOWN — Destroying all dev resources"
echo " This will delete ALL data in dev environment"
echo "============================================"
echo ""
read -p "Are you sure? Type 'yes' to confirm: " CONFIRM
if [ "${CONFIRM}" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

cd terraform

# Ensure we're in dev workspace
CURRENT_WS=$(terraform workspace show)
if [ "${CURRENT_WS}" != "dev" ]; then
    echo "Switching to dev workspace (currently: ${CURRENT_WS})..."
    terraform workspace select dev
fi

echo ""
echo "Running terraform destroy..."
terraform destroy -var-file=environments/dev.tfvars -auto-approve

echo ""
echo "============================================"
echo " ✓ Dev teardown complete. Cost = \$0."
echo ""
echo " Verify nothing is running:"
echo "   aws kinesis list-streams"
echo "   aws lambda list-functions | grep clickstream"
echo "   aws dynamodb list-tables | grep clickstream"
echo "   aws emr-serverless list-applications"
echo "============================================"
