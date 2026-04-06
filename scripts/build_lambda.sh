#!/usr/bin/env bash
# =============================================================================
# build_lambda.sh — Package the Lambda sessionizer for Terraform deployment
#
# Creates: src/lambda/sessionizer.zip
# Run before: terraform apply
# =============================================================================

set -euo pipefail

LAMBDA_SRC="src/lambda/sessionizer"
SHARED_SRC="src/lambda/shared"
BUILD_DIR="src/lambda/_build"
OUTPUT_ZIP="src/lambda/sessionizer.zip"
# Store absolute path so we can zip correctly after cd-ing into BUILD_DIR
ABS_OUTPUT_ZIP="$(pwd)/${OUTPUT_ZIP}"

echo "Building Lambda package..."

# Clean previous build
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

# Copy handler and sessionizer modules
cp "${LAMBDA_SRC}/handler.py"          "${BUILD_DIR}/"
cp "${LAMBDA_SRC}/session_state.py"    "${BUILD_DIR}/"
cp "${LAMBDA_SRC}/cart_calculator.py"  "${BUILD_DIR}/"

# Copy shared utilities (Lambda Layer would be cleaner — this is simpler for dev)
cp "${SHARED_SRC}/dynamodb_client.py"  "${BUILD_DIR}/"
cp "${SHARED_SRC}/utils.py"            "${BUILD_DIR}/"

# Install runtime dependencies into the package
# boto3 is provided by the Lambda runtime — don't bundle it (adds 30MB)
pip install --quiet \
    --target "${BUILD_DIR}" \
    --platform manylinux2014_x86_64 \
    --python-version 3.12 \
    --only-binary=:all: \
    pyarrow>=14.0.0

# Create the zip
rm -f "${ABS_OUTPUT_ZIP}"
cd "${BUILD_DIR}"
zip -r -q "${ABS_OUTPUT_ZIP}" .
cd -

ZIP_SIZE=$(du -sh "${OUTPUT_ZIP}" | cut -f1)
echo "  ✓ Built ${OUTPUT_ZIP} (${ZIP_SIZE})"

# Clean up build dir
rm -rf "${BUILD_DIR}"
echo "  ✓ Build complete — deploy with: terraform apply -var-file=environments/dev.tfvars"
