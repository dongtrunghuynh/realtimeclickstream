#!/usr/bin/env bash
# =============================================================================
# setup.sh — One-time project setup
# Run this once after cloning the repo.
# =============================================================================

set -euo pipefail

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="${AWS_REGION:-us-east-1}"
STATE_BUCKET="clickstream-tfstate-${ACCOUNT_ID}"

echo "============================================"
echo " Clickstream Pipeline — One-Time Setup"
echo " Account: ${ACCOUNT_ID} | Region: ${REGION}"
echo "============================================"
echo ""

# 1. Install Python dependencies
echo "[1/5] Installing Python dependencies..."
pip install -r requirements.txt
echo "  ✓ Done"

# 2. Create Terraform state bucket (if not exists)
echo "[2/5] Creating Terraform state bucket: ${STATE_BUCKET}"
if aws s3 ls "s3://${STATE_BUCKET}" 2>&1 | grep -q 'NoSuchBucket'; then
    aws s3 mb "s3://${STATE_BUCKET}" --region "${REGION}"
    aws s3api put-bucket-versioning \
        --bucket "${STATE_BUCKET}" \
        --versioning-configuration Status=Enabled
    aws s3api put-bucket-encryption \
        --bucket "${STATE_BUCKET}" \
        --server-side-encryption-configuration \
        '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
    echo "  ✓ Created ${STATE_BUCKET}"
else
    echo "  ✓ Already exists — skipping"
fi

# 3. Patch Terraform backend config
echo "[3/5] Configuring Terraform backend..."
BACKEND_FILE="terraform/backend.tf"
cat > "${BACKEND_FILE}" <<EOF
terraform {
  backend "s3" {
    bucket  = "${STATE_BUCKET}"
    key     = "clickstream-pipeline/terraform.tfstate"
    region  = "${REGION}"
    encrypt = true
  }
}
EOF
echo "  ✓ Written to ${BACKEND_FILE}"

# 4. Terraform init + workspaces
echo "[4/5] Initialising Terraform and creating workspaces..."
cd terraform
terraform init -reconfigure
terraform workspace new dev  2>/dev/null || echo "  workspace 'dev' already exists"
terraform workspace new prod 2>/dev/null || echo "  workspace 'prod' already exists"
terraform workspace select dev
cd ..
echo "  ✓ Terraform ready — current workspace: dev"

# 5. Create data/sample directory
echo "[5/5] Preparing data directory..."
mkdir -p data/sample
cat > data/sample/DOWNLOAD_INSTRUCTIONS.txt <<EOF
Download the REES46 dataset from Kaggle:
https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store

Download: 2019-Oct.csv (approx 2GB)
Place it here: data/sample/2019-Oct.csv

This file is in .gitignore — do NOT commit it.
EOF
echo "  ✓ Instructions written to data/sample/DOWNLOAD_INSTRUCTIONS.txt"

echo ""
echo "============================================"
echo " Setup complete!"
echo ""
echo " Next steps:"
echo "   1. Download dataset: data/sample/DOWNLOAD_INSTRUCTIONS.txt"
echo "   2. Deploy dev infra: cd terraform && terraform apply -var-file=environments/dev.tfvars"
echo "   3. Read: docs/step-by-step.md"
echo "============================================"
