# Setup Guide — Real-Time Clickstream Pipeline

> Follow this guide top-to-bottom the first time. After that, use `make help`
> for day-to-day commands.

---

## Prerequisites Checklist

Before starting, verify every item below:

```bash
# 1. Python 3.11+
python --version          # Need 3.11.x or 3.12.x

# 2. Terraform 1.7+
terraform --version       # Need >= 1.7.0
# Install: https://developer.hashicorp.com/terraform/install

# 3. AWS CLI v2
aws --version             # Need aws-cli/2.x
# Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html

# 4. Java 11+ (needed for local PySpark testing only)
java -version             # Need 11+

# 5. GitHub CLI
gh --version              # Need >= 2.x
# Install: https://cli.github.com

# 6. GNU Make
make --version
```

---

## Step 1 — AWS Account Setup

### 1a. Create IAM user for the project

In the AWS Console:
1. Navigate to **IAM → Users → Create user**
2. Name: `clickstream-pipeline-dev`
3. Select **"Provide user access to the AWS Management Console"** → No (CLI only)
4. Click through to **Permissions → Attach policies directly**
5. Attach these managed policies:

```
AmazonKinesisFullAccess
AWSLambda_FullAccess
AmazonDynamoDBFullAccess
AmazonS3FullAccess
AmazonAthenaFullAccess
AmazonEMRServerlessServiceRolePolicy
AWSGlueConsoleFullAccess
CloudWatchFullAccess
IAMFullAccess
```

6. **Create user** → **Create access key** → CLI → Download CSV

> ⚠️ In production, scope IAM policies to specific ARNs. `FullAccess` policies are
> acceptable for a dev project where you control the environment.

### 1b. Configure AWS CLI

```bash
aws configure
# AWS Access Key ID:     [paste from downloaded CSV]
# AWS Secret Access Key: [paste from downloaded CSV]
# Default region name:   us-east-1
# Default output format: json

# Verify
aws sts get-caller-identity
# Should return your account ID, user ARN, and user ID
```

### 1c. Set a billing alarm

So you never get a surprise bill:

```bash
# Create a $15/month alarm (CloudWatch → Alarms → Billing)
aws cloudwatch put-metric-alarm \
    --alarm-name "clickstream-pipeline-budget-alert" \
    --alarm-description "Alert if clickstream pipeline exceeds $15/month" \
    --metric-name EstimatedCharges \
    --namespace AWS/Billing \
    --statistic Maximum \
    --period 86400 \
    --threshold 15 \
    --comparison-operator GreaterThanThreshold \
    --dimensions Name=Currency,Value=USD \
    --evaluation-periods 1 \
    --alarm-actions arn:aws:sns:us-east-1:$(aws sts get-caller-identity --query Account --output text):clickstream-billing-alert \
    --treat-missing-data notBreaching
```

---

## Step 2 — GitHub Setup

```bash
# Authenticate GitHub CLI
gh auth login
# Follow prompts — choose HTTPS, paste your GitHub token

# Create a new GitHub repository
gh repo create clickstream-pipeline \
    --private \
    --description "Real-time clickstream analytics — Lambda Architecture on AWS"

# Clone it
git clone https://github.com/YOUR_USERNAME/clickstream-pipeline
cd clickstream-pipeline
```

---

## Step 3 — Project Initialisation

```bash
# Install Python dependencies
make install

# Run one-time setup (creates TF state bucket + workspaces)
make setup

# This script will:
#   1. Create S3 bucket for Terraform state (clickstream-tfstate-ACCOUNT_ID)
#   2. Enable versioning + encryption on the bucket
#   3. Patch terraform/backend.tf with your account ID
#   4. Run terraform init + create dev/prod workspaces
#   5. Create data/sample/ directory with download instructions
```

---

## Step 4 — Download the Dataset

1. Create a Kaggle account at https://kaggle.com (free)
2. Go to https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store
3. Click **Download** → Download `2019-Oct.csv` (~2GB compressed)
4. Place the extracted CSV at: `data/sample/2019-Oct.csv`

```bash
# Verify
wc -l data/sample/2019-Oct.csv
# Should print: ~42,448,764 (42M lines including header)

head -3 data/sample/2019-Oct.csv
# Should show: event_time,event_type,product_id,category_id,...
```

---

## Step 5 — Deploy Dev Infrastructure

```bash
# Always confirm you're in the dev workspace
cd terraform && terraform workspace show  # should print: dev
cd ..

# Review what will be created (no cost yet)
make tf-plan

# Deploy everything (~2 minutes)
make tf-apply

# Print all resource names/ARNs
make tf-outputs
```

### Expected outputs

```
kinesis_stream_name   = "clickstream-events-dev"
dynamodb_table_name   = "clickstream-sessions-dev"
raw_s3_bucket         = "clickstream-raw-123456789012-dev"
emr_application_id    = "00abcdef12345678"
emr_execution_role_arn = "arn:aws:iam::123456789012:role/clickstream-reconciler-dev-execution-role"
athena_workgroup      = "clickstream-dev"
```

### Set environment variables

```bash
# Add to your shell profile (~/.bashrc or ~/.zshrc):
export KINESIS_STREAM_NAME="clickstream-events-dev"
export DYNAMODB_TABLE_NAME="clickstream-sessions-dev"
export S3_BUCKET="clickstream-raw-YOUR_ACCOUNT_ID-dev"
export EMR_APPLICATION_ID="$(cd terraform && terraform output -raw emr_application_id)"
export EMR_EXECUTION_ROLE_ARN="$(cd terraform && terraform output -raw emr_execution_role_arn)"
export ATHENA_DATABASE="clickstream_dev"
export ATHENA_WORKGROUP="clickstream-dev"
export ATHENA_OUTPUT_BUCKET="clickstream-athena-YOUR_ACCOUNT_ID-dev"
export AWS_REGION="us-east-1"
```

---

## Step 6 — Deploy Lambda

```bash
# Build the Lambda zip
make build-lambda
# Creates: src/lambda/sessionizer.zip (~15MB with pyarrow)

# Deploy
make deploy-lambda

# Verify the Lambda is connected to Kinesis
aws lambda list-event-source-mappings \
    --function-name clickstream-sessionizer-dev \
    --query 'EventSourceMappings[].{State:State,BatchSize:BatchSize}'
# Should show State: Enabled, BatchSize: 100
```

---

## Step 7 — Set up Athena Tables

```bash
# Create all Glue tables and Athena views
make athena-setup

# This runs scripts/athena_setup.sh which executes:
#   - athena/schema/create_tables.sql  (table DDL)
#   - athena/views/realtime_sessions.sql
#   - athena/views/batch_sessions.sql
#   - athena/views/accuracy_comparison.sql
```

---

## Step 8 — Smoke Test

```bash
# 1. Run the simulator for 60 seconds at 200 events/second
make simulate-fast

# 2. Watch Lambda processing in real-time (open a second terminal)
make lambda-logs

# 3. Verify events in DynamoDB
aws dynamodb scan \
    --table-name clickstream-sessions-dev \
    --max-items 3 \
    --query 'Items[*].{session:session_id.S,events:event_count.N,total:cart_total.N}'

# 4. Verify raw events landed in S3
aws s3 ls s3://$S3_BUCKET/events/ --recursive | tail -5

# 5. Run a quick Athena query
aws athena start-query-execution \
    --query-string "SELECT COUNT(*) as session_count FROM clickstream_dev.realtime_sessions_raw LIMIT 1" \
    --work-group clickstream-dev \
    --query-execution-context Database=clickstream_dev \
    --result-configuration OutputLocation=s3://$ATHENA_OUTPUT_BUCKET/query-results/
```

---

## Daily Workflow

```bash
# Morning: sync and pick up where you left off
git fetch origin && git rebase origin/main

# Evening: ALWAYS destroy dev resources
make tf-destroy
```

---

## Troubleshooting

### Lambda not processing records

```bash
# Check event source mapping state
aws lambda list-event-source-mappings \
    --function-name clickstream-sessionizer-dev

# Check for Lambda errors
aws logs filter-log-events \
    --log-group-name /aws/lambda/clickstream-sessionizer-dev \
    --filter-pattern "ERROR" \
    --start-time $(date -d "1 hour ago" +%s000)
```

### Kinesis records not appearing

```bash
# Check stream status
aws kinesis describe-stream-summary --stream-name clickstream-events-dev

# Get a shard iterator and read a record manually
ITER=$(aws kinesis get-shard-iterator \
    --stream-name clickstream-events-dev \
    --shard-id shardId-000000000000 \
    --shard-iterator-type LATEST \
    --query ShardIterator --output text)

aws kinesis get-records --shard-iterator $ITER --limit 1
```

### EMR Serverless job fails

```bash
# Check job status
aws emr-serverless get-job-run \
    --application-id $EMR_APPLICATION_ID \
    --job-run-id YOUR_JOB_RUN_ID

# View Spark driver logs
aws logs tail /aws/emr-serverless/clickstream-reconciler-dev --follow
```

### Athena query returns no data

1. Check S3 partition paths match the table definition exactly
2. Run `MSCK REPAIR TABLE table_name` in Athena to refresh partitions
3. For partition projection tables, verify the partition range in the DDL covers your dates

### DynamoDB writes slow

Switch to `PAY_PER_REQUEST` billing (already configured). If writes are still slow, check:
- Lambda concurrency is not hitting the account limit (default 1000)
- DynamoDB table is in the same region as Lambda
