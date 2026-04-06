# Step-by-Step Project Guide

> Your week-by-week, task-by-task playbook. Read this before touching any code.
> Every task includes what you'll learn and how to verify it worked.

---

## Before You Start — One-Time Setup

### Prerequisites

```bash
# Check you have everything
python --version      # Need 3.11+
terraform --version   # Need 1.7+
aws --version         # Need 2.x
java -version         # Need 11+ (for local Spark testing)
gh --version          # GitHub CLI — install from https://cli.github.com

# AWS credentials configured
aws sts get-caller-identity   # Should return your account ID
```

### AWS Account Setup

1. Create an AWS account (or use existing)
2. Create an IAM user with programmatic access
3. Attach policies: `AmazonKinesisFullAccess`, `AWSLambda_FullAccess`,
   `AmazonDynamoDBFullAccess`, `AmazonS3FullAccess`, `AmazonAthenaFullAccess`,
   `AmazonEMRServerlessServiceRolePolicy`, `IAMFullAccess`
4. Run `aws configure` with your access key + secret
5. Set your default region: `us-east-1`

### GitHub Setup

```bash
gh auth login
git clone <your-repo>
cd clickstream-pipeline
pip install -r requirements.txt
```

### Download Dataset

1. Go to https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store
2. Download `2019-Oct.csv` (~2GB — this is your dev dataset)
3. Place it at `data/sample/2019-Oct.csv`
4. This file is in `.gitignore` — never commit it

---

## Week 1 — Infrastructure Foundation

### Goal: All AWS resources provisioned via Terraform. Zero manual clicking.

---

### Task 1.1 — Terraform Backend & Workspaces

**Branch:** `infra/terraform-backend`

```bash
git checkout -b infra/terraform-backend
```

**What to do:**

1. Create an S3 bucket manually (just once) for Terraform state:
   ```bash
   aws s3 mb s3://clickstream-tfstate-<your-account-id> --region us-east-1
   aws s3api put-bucket-versioning \
     --bucket clickstream-tfstate-<your-account-id> \
     --versioning-configuration Status=Enabled
   ```

2. Update `terraform/backend.tf` with your bucket name

3. Initialize and create workspaces:
   ```bash
   cd terraform
   terraform init
   terraform workspace new dev
   terraform workspace new prod
   terraform workspace select dev
   ```

**Verify:**
```bash
terraform workspace list
# Should show: * dev, prod
```

**Commit & PR:**
```bash
git add terraform/backend.tf terraform/environments/
git commit -m "infra(terraform): configure S3 backend and dev/prod workspaces"
gh pr create --title "infra(terraform): configure S3 backend and dev/prod workspaces"
```

---

### Task 1.2 — Kinesis Data Stream Module

**Branch:** `infra/kinesis-module`

**What to do:**

1. Fill in `terraform/modules/kinesis/main.tf` to create:
   - `aws_kinesis_stream` with `stream_mode = "ON_DEMAND"`
   - Appropriate tags: `env`, `project`

2. Wire it into `terraform/main.tf`

3. Apply in dev:
   ```bash
   terraform workspace select dev
   terraform apply -var-file=environments/dev.tfvars
   ```

**Verify:**
```bash
aws kinesis list-streams
aws kinesis describe-stream-summary --stream-name clickstream-events-dev
```

**What you learned:** Kinesis on-demand mode — no shard management, auto-scales,
charges per GB processed. ~$0.08/GB ingested.

---

### Task 1.3 — DynamoDB Module (Single-Table Design)

**Branch:** `infra/dynamodb-module`

**What to do:**

1. Fill in `terraform/modules/dynamodb/main.tf`:
   - Table name: `clickstream-sessions-<env>`
   - Partition key: `session_id` (String)
   - Sort key: `event_type` (String)
   - Billing: `PAY_PER_REQUEST`
   - TTL attribute: `expires_at`
   - GSI: `user_id-index` on `user_id` (for user-level queries)

2. Apply and verify:
   ```bash
   aws dynamodb describe-table --table-name clickstream-sessions-dev
   ```

**What you learned:** Single-table design — all session state in one table.
TTL auto-deletes cold sessions, keeping costs in free tier.

---

### Task 1.4 — S3 Buckets + Athena Module

**Branch:** `infra/s3-athena-module`

**What to do:**

1. Create two S3 buckets in `terraform/modules/s3_athena/main.tf`:
   - `clickstream-raw-<account-id>-<env>` — raw Parquet events
   - `clickstream-athena-results-<account-id>-<env>` — Athena query output

2. Create Athena workgroup with output location pointing to results bucket

3. Create Glue Data Catalog database: `clickstream_<env>`

**Verify:**
```bash
aws s3 ls | grep clickstream
aws athena list-work-groups
```

---

### Task 1.5 — Lambda Module (Skeleton)

**Branch:** `infra/lambda-module`

**What to do:**

1. Create Lambda function in `terraform/modules/lambda/main.tf`:
   - Runtime: `python3.12`
   - Handler: `handler.lambda_handler`
   - Memory: 512MB, Timeout: 60s
   - Environment variables: `DYNAMODB_TABLE_NAME`, `S3_BUCKET`, `AWS_REGION`
   - IAM role with Kinesis read, DynamoDB write, S3 write, CloudWatch logs

2. Add Kinesis event source mapping:
   - Batch size: 100
   - Starting position: `LATEST`
   - Bisect on error: `true`

3. Deploy placeholder `handler.py` (just `print("hello")`)

**Verify:**
```bash
aws lambda list-functions | grep clickstream
aws lambda invoke --function-name clickstream-sessionizer-dev /tmp/out.json
cat /tmp/out.json
```

---

### Task 1.6 — EMR Serverless Module

**Branch:** `infra/emr-module`

**What to do:**

1. Create EMR Serverless application in `terraform/modules/emr_serverless/main.tf`:
   - Release: `emr-7.0.0`
   - Type: `SPARK`
   - Auto-stop idle application after 15 minutes
   - Initial capacity: 0 (don't pre-warm — pay only when running)

2. Create IAM execution role for Spark jobs with S3 read/write + CloudWatch

**Verify:**
```bash
aws emr-serverless list-applications
```

**Week 1 Done ✅** — All infrastructure exists. Single `terraform destroy` tears it all down.

---

## Week 2 — Event Simulator

### Goal: A Python script that replays REES46 events into Kinesis with configurable rate and intentional late arrivals.

---

### Task 2.1 — Event Schema

**Branch:** `feat/event-schema`

**What to do:**

1. Study the REES46 CSV columns:
   `event_time, event_type, product_id, category_id, category_code, brand, price, user_id, user_session`

2. Define your canonical event schema in `data/schemas/event_schema.json`:
   ```json
   {
     "event_id": "uuid4 — generated by simulator",
     "event_time": "ISO8601 — from dataset",
     "arrival_time": "ISO8601 — when simulator sends to Kinesis",
     "event_type": "view | cart | purchase",
     "product_id": "string",
     "category_code": "string | null",
     "brand": "string | null",
     "price": "float",
     "user_id": "string",
     "session_id": "string — from dataset user_session",
     "is_late_arrival": "bool — injected by simulator",
     "late_arrival_delay_seconds": "int | null"
   }
   ```

3. Update `src/event_simulator/event_schema.py` with a Pydantic model

**Commit:** `feat(simulator): define canonical clickstream event schema`

---

### Task 2.2 — CSV Reader & Event Parser

**Branch:** `feat/simulator-csv-reader`

**What to do:**

Fill in `src/event_simulator/simulator.py`:
- Read `2019-Oct.csv` in chunks (don't load 2GB into memory)
- Parse each row into your event schema
- Yield validated event dicts
- Handle `None`/NaN gracefully (category_code, brand are often null)

```python
# Target API
for event in EventSimulator("data/sample/2019-Oct.csv").stream(limit=10_000):
    print(event)
```

**Test:**
```bash
pytest tests/unit/test_simulator.py::test_csv_parsing -v
```

---

### Task 2.3 — Kinesis Producer

**Branch:** `feat/kinesis-producer`

**What to do:**

Fill in `src/event_simulator/kinesis_producer.py`:
- Use `boto3` Kinesis `put_records` (batch up to 500 records per call)
- Partition key: `user_id` (keeps one user's events on the same shard)
- Configurable `--rate` events/second with `time.sleep` throttling
- Retry with exponential backoff on `ProvisionedThroughputExceededException`
- Log throughput every 10 seconds

```bash
# Run it
python src/event_simulator/simulator.py --rate 50 --duration 60
# Watch records arrive
aws kinesis get-shard-iterator \
  --stream-name clickstream-events-dev \
  --shard-id shardId-000000000000 \
  --shard-iterator-type LATEST
```

**What you learned:** Kinesis producer patterns — batching, partition keys, backpressure.

---

### Task 2.4 — Late Arrival Injector

**Branch:** `feat/late-arrival-injector`

**What to do:**

Fill in `src/event_simulator/late_arrival_injector.py`:
- With probability `p` (default 5%), hold back an event
- Release it after a random delay: 2–15 minutes
- Set `is_late_arrival = True` and `late_arrival_delay_seconds` in the event
- This simulates mobile clients with intermittent connectivity

```bash
python src/event_simulator/simulator.py --rate 50 --late-arrival-pct 0.05
```

**Verify:** After 5 minutes of running, check CloudWatch Logs for your Lambda —
you should see events with `is_late_arrival: true` being received.

---

## Week 3 — Lambda Sessionizer

### Goal: Lambda function that maintains real-time session state in DynamoDB.

---

### Task 3.1 — DynamoDB Client (Shared)

**Branch:** `feat/dynamodb-shared-client`

**What to do:**

Fill in `src/lambda/shared/dynamodb_client.py`:
- Singleton pattern — one client per Lambda execution environment
- Exponential backoff retry decorator
- Helper: `put_session_state(session_id, state_dict, ttl_hours=2)`
- Helper: `get_session_state(session_id) -> dict | None`
- Helper: `update_cart_total(session_id, price_delta) -> None` (atomic increment)

**Test:**
```bash
pytest tests/unit/test_dynamodb_client.py -v
```

---

### Task 3.2 — Session State Logic

**Branch:** `feat/session-state-logic`

**What to do:**

Fill in `src/lambda/sessionizer/session_state.py`:

```python
class SessionState:
    SESSION_TIMEOUT_MINUTES = 30

    def is_new_session(self, last_event_time, current_event_time) -> bool:
        """True if gap > 30 minutes."""

    def update(self, session: dict, event: dict) -> dict:
        """Apply a new event to session state. Returns updated session."""

    def compute_cart_total(self, events: list[dict]) -> float:
        """Sum prices of add_to_cart events, subtract removals."""
```

Edge cases to handle:
- `event_time` is None (use `arrival_time`)
- Events arrive out of order within a batch (sort by `event_time`)
- `purchase` event should close the session

**Test:** Write tests for all three edge cases above.

---

### Task 3.3 — Lambda Handler

**Branch:** `feat/lambda-handler`

**What to do:**

Fill in `src/lambda/sessionizer/handler.py`:

```python
def lambda_handler(event, context):
    records = event["Records"]
    # 1. Decode Kinesis records (base64 → JSON)
    # 2. Sort by event_time within the batch
    # 3. Skip late arrivals (is_late_arrival=True) — persist to S3, don't update DynamoDB
    # 4. For each event: get/create session in DynamoDB, update state
    # 5. Log: session_id, event_count, cart_total, processing_latency_ms
```

**Key decisions to make (document in code comments):**
- Do you process late arrivals or skip them? Why?
- How do you handle DynamoDB write failures — fail the batch or continue?

**Verify:**
```bash
# Invoke Lambda manually with a test event
aws lambda invoke \
  --function-name clickstream-sessionizer-dev \
  --payload file://tests/fixtures/kinesis_batch.json \
  /tmp/response.json
cat /tmp/response.json
```

---

### Task 3.4 — Cart Total Calculator

**Branch:** `feat/cart-calculator`

**What to do:**

Fill in `src/lambda/sessionizer/cart_calculator.py`:
- Accumulate `price` for `cart` events
- Subtract for `remove_from_cart` if present in dataset
- Final `purchase` event: record as converted session
- Write `conversion_value`, `item_count`, `session_duration_seconds` to DynamoDB

---

## Week 4 — Spark Batch Reconciler

### Goal: Nightly Spark job that corrects real-time sessions using late-arriving events.

---

### Task 4.1 — Raw Event Writer (S3)

**Branch:** `feat/s3-raw-writer`

**What to do:**

Update Lambda handler to also write ALL events (including late arrivals) to S3 as Parquet:
- Path: `s3://clickstream-raw-<account>/events/year=YYYY/month=MM/day=DD/hour=HH/`
- Format: Parquet (use `pyarrow` in a Lambda Layer)
- Batch writes — accumulate records, write at end of Lambda invocation

---

### Task 4.2 — Spark Session Stitcher

**Branch:** `feat/spark-session-stitcher`

**What to do:**

Fill in `src/spark/session_stitcher.py`:

```python
# Pseudocode
events = spark.read.parquet("s3://raw/events/year=.../")

# Sessionize with a 30-min window using Spark's session window
sessions = (
    events
    .groupBy("user_id", session_window("event_time", "30 minutes"))
    .agg(
        count("*").alias("event_count"),
        sum(when(col("event_type") == "cart", col("price")).otherwise(0)).alias("cart_total"),
        max(when(col("event_type") == "purchase", lit(1)).otherwise(0)).alias("converted"),
    )
)

sessions.write.partitionBy("year", "month", "day").parquet("s3://corrected/sessions/")
```

**Submit to EMR Serverless:**
```bash
bash scripts/submit_spark_job.sh session_stitcher
```

---

### Task 4.3 — Late Arrival Handler

**Branch:** `feat/late-arrival-handler`

**What to do:**

Fill in `src/spark/late_arrival_handler.py`:
- Read events where `is_late_arrival = true`
- Join with existing sessions by `session_id` and `user_id`
- Determine if the late event belongs to an existing session or creates a restatement
- Write restatement audit records: `session_id, restatement_type, revenue_delta`

---

### Task 4.4 — Athena Views

**Branch:** `feat/athena-views`

**What to do:**

Create the three SQL files in `athena/views/`:

1. `realtime_sessions.sql` — reads from DynamoDB export or a Lambda that dumps to S3
2. `batch_sessions.sql` — reads from corrected Parquet in S3
3. `accuracy_comparison.sql` — joins both, computes:
   - Session count delta (real-time vs batch)
   - Revenue discrepancy per session
   - % of sessions requiring restatement due to late arrivals

Run via Athena console or `aws athena start-query-execution`.

---

## Week 5 — Accuracy/Latency Dashboard (⭐ Standout)

### Goal: Quantitative proof you understand Lambda Architecture tradeoffs.

---

### Task 5.1 — Data Collection Run

**Branch:** `feat/dashboard-data-collection`

**What to do:**

Run a full simulated day:
```bash
# Start simulator for 1 hour at 200 events/sec with 8% late arrivals
python src/event_simulator/simulator.py \
  --rate 200 \
  --duration 3600 \
  --late-arrival-pct 0.08

# After run: trigger the nightly Spark reconciliation
bash scripts/submit_spark_job.sh batch_reconciler
```

---

### Task 5.2 — Dashboard Script

**Branch:** `feat/accuracy-latency-dashboard`

**What to do:**

Fill in `src/dashboard/accuracy_latency_dashboard.py`:

```
Output (printed + saved to CSV):

┌─────────────────────────────────────────────────────────────┐
│          LAMBDA ARCHITECTURE ACCURACY/LATENCY REPORT        │
├─────────────────────┬──────────────┬────────────────────────┤
│ Metric              │ Speed Layer  │ Batch Layer            │
│                     │ (DynamoDB)   │ (Athena — corrected)   │
├─────────────────────┼──────────────┼────────────────────────┤
│ Total Sessions      │ 18,432       │ 17,891                 │
│ Total Revenue       │ $284,120     │ $291,445               │
│ Avg Session Duration│ 4m 12s       │ 4m 38s                 │
│ Conversion Rate     │ 3.2%         │ 3.6%                   │
├─────────────────────┼──────────────┼────────────────────────┤
│ Sessions Restated   │ —            │ 541 (2.9%)             │
│ Revenue Restated    │ —            │ $7,325 (2.5%)          │
│ Avg Latency         │ <30s         │ ~8 hours               │
└─────────────────────┴──────────────┴────────────────────────┘
```

---

### Task 5.3 — Write Your Analysis

**Branch:** `docs/tradeoff-analysis`

Create `docs/tradeoffs.md`:
- What % of sessions needed restatement?
- What was the average revenue error in the speed layer?
- Under what business conditions would you accept more latency for more accuracy?
- Under what conditions is the speed layer "good enough"?

This document is what you show in interviews. It demonstrates you're not just
a Terraform/Spark engineer — you're an **analytical** data engineer.

---

## Final Checklist Before Sharing With Employers

```
Infrastructure:
  [ ] Single terraform apply in dev works end-to-end
  [ ] Single terraform destroy tears everything to $0
  [ ] No hardcoded account IDs or region names

Code Quality:
  [ ] All unit tests pass
  [ ] Ruff linting passes with 0 errors
  [ ] All functions have docstrings

Documentation:
  [ ] README.md explains the project clearly
  [ ] CLAUDE.md has accurate architecture description
  [ ] docs/tradeoffs.md has quantitative analysis
  [ ] Athena views are commented

GitHub:
  [ ] All work was done in feature branches
  [ ] All PRs used the PR template
  [ ] PR titles follow conventional commit format
  [ ] No credentials ever committed (check with: git log -p | grep -i "aws_secret")

The Standout Piece:
  [ ] Accuracy/latency dashboard produces real numbers
  [ ] Numbers tell an interesting story (some restatements, not zero)
  [ ] You can explain the numbers in plain English
```

---

## Cost Control — Non-Negotiable Rules

1. **Daily:** `terraform workspace select dev && terraform destroy -var-file=environments/dev.tfvars`
2. **Never leave EMR Serverless applications running** — they auto-stop after 15 min idle
3. **Never use Kinesis provisioned mode** — on-demand only
4. **Set AWS billing alert at $15/month** in CloudWatch
5. **Use `--duration` flag in simulator** — never let it run unbounded
