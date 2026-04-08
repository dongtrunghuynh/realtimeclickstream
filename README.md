# Real-Time Clickstream Pipeline — Streaming Analytics

A production-grade **Lambda Architecture** pipeline built on AWS. Ingests e-commerce
clickstream events in real-time via Kinesis + Lambda, batch-reconciles sessions nightly
with Spark on EMR Serverless, and quantifies the accuracy/latency tradeoff between the
speed and batch layers.

**Dataset:** [REES46 E-Commerce Behaviour Dataset](https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store) (~20M events, Kaggle)

---

## Architecture

```
[Python Event Simulator (REES46 dataset)]
        │  100 events/sec default, 5% late arrivals (2–15 min delay)
        ▼
[Kinesis Data Streams — on-demand]
        │  partition key: user_id (preserves session ordering)
        │
        ├──► [Lambda — Sessionizer (Python 3.12)]
        │          5-sec tumbling window, batch size 100
        │          30-min inactivity session boundary
        │          Running cart totals, idempotent DynamoDB writes
        │          ▼
        │    [DynamoDB — Speed Layer]    ←── Sub-minute latency
        │          single-table design, 2-hr TTL auto-cleanup
        │
        └──► [S3 — Raw Events (NDJSON, partitioned by hour)]
             [S3 — Late Arrivals (NDJSON, partitioned by hour)]
                    │
             [EMR Serverless — Spark 3.5 (emr-7.0.0)]
                  Nightly reconciliation (2 AM UTC)
                  Session stitching across late-arrival boundaries
                  Writes corrected sessions as Parquet + Snappy
                    │
             [S3 — Corrected Sessions (Parquet, partitioned by day)]
                    │
             [Athena + Glue — 5 external tables, 3 views]
             [accuracy_comparison view — full outer join speed vs batch]
                    │
        [Accuracy/Latency Dashboard — CSV + console report]
```

---

## Stack

| Layer | Service | Detail |
|-------|---------|--------|
| Ingestion | Amazon Kinesis Data Streams | On-demand mode, 24-hr retention |
| Speed processing | AWS Lambda | Python 3.12, 512 MB, 60 s timeout |
| Speed serving | Amazon DynamoDB | On-demand billing, 2-hr TTL, GSI on user_id |
| Batch processing | EMR Serverless | Spark 3.5 (emr-7.0.0), auto-stop 15 min |
| Batch storage | Amazon S3 + Apache Parquet | Snappy compression, partitioned by year/month/day |
| Batch query | Amazon Athena | Glue catalog, partition projection |
| Infrastructure | Terraform 1.7+ | Modular, dev/prod workspaces |
| CI/CD | GitHub Actions | Lint, test, deploy, nightly Spark, nightly teardown |
| Language | Python 3.11+ | boto3, pandas, pyarrow, pyspark 3.5 |

---

## Quick Start

### Prerequisites

- AWS CLI configured (`aws configure`)
- Terraform >= 1.7
- Python >= 3.11
- Java 11 (for local PySpark testing)
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Install

```bash
git clone <repo>
cd realtimeclickstream

# With uv (recommended)
uv sync

# Or with pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Deploy Infrastructure (dev)

```bash
cd terraform
terraform init
terraform workspace new dev        # first time only
terraform workspace select dev
terraform apply -var-file=environments/dev.tfvars
```

### Run the Pipeline

```bash
# 1. Ingest events into Kinesis (300 seconds, 100 events/sec)
python src/event_simulator/simulator.py \
  --rate 100 --duration 300 --late-arrival-pct 0.05

# 2. (Lambda triggers automatically from Kinesis)

# 3. Run nightly Spark batch reconciliation
bash scripts/submit_spark_job.sh session_stitcher
bash scripts/submit_spark_job.sh late_arrival_handler

# 4. Set up Athena tables and views
bash scripts/athena_setup.sh

# 5. View accuracy/latency dashboard
python src/dashboard/accuracy_latency_dashboard.py --output results.csv
```

Or run the full pipeline end-to-end:

```bash
bash scripts/run_full_pipeline.sh
# Use --quick for a fast smoke test
```

See [`docs/setup-guide.md`](docs/setup-guide.md) for the complete walkthrough.

---

## Key Deliverables

### 1. Event Simulator (`src/event_simulator/`)

Replays REES46 dataset into Kinesis with realistic behavior:
- Configurable rate (default 100 events/sec), duration, and event limit
- 5% of events held back 2–15 minutes to simulate late arrivals
- Partition key = `user_id` to preserve ordering across shards
- Exponential backoff for Kinesis throttling
- Optional CloudWatch metrics emission

```bash
python src/event_simulator/simulator.py \
  --rate 100 --duration 300 --late-arrival-pct 0.05 --no-cloudwatch
```

### 2. Lambda Sessionizer (`src/lambda/sessionizer/`)

Kinesis-triggered processor applying a 30-minute inactivity session boundary:
- Decodes Base64 Kinesis records, routes late arrivals to S3 only
- Groups events by `session_id`, sorts by `event_time`
- Updates DynamoDB: `event_count`, `cart_total`, `converted`, `last_event_time`, `expires_at` (TTL)
- Idempotent via conditional `put_item` (handles Kinesis at-least-once delivery)
- Failed records land in an SQS DLQ, reprocessed by `dlq_handler.py`

### 3. Spark Batch Reconciler (`src/spark/`)

Nightly EMR Serverless job re-sessionizing the full event history:
- Reads all raw events + late arrivals from S3
- Re-applies 30-min window using PySpark window functions
- Stitches sessions that were split by late arrivals
- Writes `batch_session_id`, `had_restatement`, `late_arrival_count`, etc.
- Output: Parquet, partitioned by `year/month/day`, Snappy-compressed

### 4. Athena Views (`athena/`)

Five Glue external tables and three SQL views:
- `realtime_sessions` — cleaned DynamoDB export
- `batch_sessions_v` — formatted Spark output
- `accuracy_comparison` — full outer join with per-session deltas (revenue, event count, duration)

### 5. Accuracy/Latency Dashboard (`src/dashboard/accuracy_latency_dashboard.py`)

The standout deliverable — quantifies the tradeoff:

| Metric | Speed Layer | Batch Layer |
|--------|-------------|-------------|
| Latency | < 30 seconds | ~8 hours |
| Restatement rate | — | % of sessions affected by late arrivals |
| Revenue error | absolute + % vs batch | ground truth |

```bash
python src/dashboard/accuracy_latency_dashboard.py --output results.csv
```

---

## Project Structure

```
realtimeclickstream/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                  # Lint + test + Terraform validate + secret scan
│   │   ├── deploy.yml              # Build Lambda → deploy dev (auto) / prod (manual)
│   │   ├── nightly_spark.yml       # Daily 2 AM UTC: DynamoDB export → Spark jobs
│   │   └── nightly_teardown.yml    # Daily 1 AM UTC: terraform destroy dev
│   ├── ISSUE_TEMPLATE/
│   └── PULL_REQUEST_TEMPLATE.md
├── docs/
│   ├── architecture.md             # Lambda Architecture deep-dive
│   ├── setup-guide.md              # Prerequisites and full walkthrough
│   ├── step-by-step.md             # Week-by-week build guide
│   ├── interview-prep.md           # Talking points for interviews
│   └── tradeoffs.md                # Accuracy/latency analysis template
├── terraform/
│   ├── main.tf                     # Root config, 6 modules wired together
│   ├── backend.tf                  # S3 state + DynamoDB locking
│   ├── variables.tf
│   ├── outputs.tf
│   ├── environments/
│   │   ├── dev.tfvars
│   │   └── prod.tfvars
│   └── modules/
│       ├── kinesis/                # On-demand stream, KMS encryption
│       ├── dynamodb/               # Single-table, TTL, GSI, PITR
│       ├── lambda/                 # Function + ESM + DLQ + IAM
│       ├── emr_serverless/         # Spark app, auto-stop, IAM
│       ├── s3_athena/              # 3 buckets + Athena workgroup + Glue DB
│       └── cloudwatch/             # Dashboard + optional alarms
├── src/
│   ├── event_simulator/
│   │   ├── simulator.py            # Main CLI entry point
│   │   ├── config.py               # Config dataclass + env overrides
│   │   ├── event_schema.py         # ClickstreamEvent dataclass
│   │   ├── kinesis_producer.py     # Batched Kinesis puts, retry logic
│   │   ├── late_arrival_injector.py# Holds back 5% of events
│   │   └── metrics.py              # CloudWatch metrics emission
│   ├── lambda/
│   │   ├── sessionizer/
│   │   │   ├── handler.py          # Lambda entry point
│   │   │   ├── session_state.py    # 30-min boundary logic
│   │   │   ├── cart_calculator.py  # Cart total aggregation
│   │   │   ├── dlq_handler.py      # Dead-letter queue reprocessing
│   │   │   └── requirements.txt
│   │   └── shared/
│   │       ├── dynamodb_client.py  # Singleton DynamoDB wrapper
│   │       └── utils.py            # S3 write utilities
│   ├── spark/
│   │   ├── session_stitcher.py     # Main batch reconciliation job
│   │   ├── late_arrival_handler.py # Late-arrival specific processing
│   │   └── spark_utils.py          # SparkSession, schema, path helpers
│   └── dashboard/
│       ├── accuracy_latency_dashboard.py  # Athena queries + comparison report
│       └── local_report.py         # Local CSV-based report renderer
├── athena/
│   ├── schema/
│   │   └── create_tables.sql       # 5 external Glue tables
│   └── views/
│       ├── realtime_sessions.sql
│       ├── batch_sessions.sql
│       └── accuracy_comparison.sql
├── data/
│   ├── sample/                     # 2019-Nov.csv sample (see DOWNLOAD_INSTRUCTIONS.txt)
│   └── schemas/
│       └── event_schema.json       # JSON schema for event validation
├── scripts/
│   ├── setup.sh                    # One-time init (state bucket + workspaces)
│   ├── build_lambda.sh             # Packages sessionizer.zip for deployment
│   ├── submit_spark_job.sh         # Uploads + submits EMR Serverless job
│   ├── export_dynamodb_snapshot.sh # Exports DynamoDB to S3 NDJSON
│   ├── athena_setup.sh             # Registers Glue tables + creates views
│   ├── run_full_pipeline.sh        # End-to-end orchestration script
│   └── teardown_dev.sh             # Wrapper for dev terraform destroy
├── tests/
│   ├── test_simulator.py
│   ├── test_lambda_handler.py
│   ├── test_sessionizer.py
│   ├── test_dynamodb_client.py
│   ├── test_spark.py
│   ├── test_metrics.py
│   ├── test_dlq_handler.py
│   ├── test_utils.py
│   ├── test_local_report.py
│   └── test_end_to_end.py          # Integration (requires live AWS dev env)
├── CLAUDE.md                       # AI assistant context file
├── CHANGELOG.md
├── Makefile                        # All common tasks (see `make help`)
├── pyproject.toml
├── requirements.txt                # boto3, pandas, pyarrow, tabulate
├── requirements-dev.txt            # pyspark, moto, mypy, boto3-stubs
└── ruff.toml                       # Linter config
```

---

## Make Targets

```bash
make setup          # One-time project initialization
make install        # Install all dependencies
make lint           # Run ruff linter
make test           # Run unit tests (skips integration)
make test-cov       # Run tests with coverage report (70% minimum)
make tf-plan        # terraform plan (dev workspace)
make tf-apply       # terraform apply (dev workspace)
make tf-destroy     # terraform destroy (dev workspace)
make build-lambda   # Package Lambda deployment artifact
make simulate       # Run event simulator
make spark-run      # Submit batch Spark job
make athena-setup   # Register Glue tables and views
make dashboard      # Run accuracy/latency comparison report
make cost-check     # Verify no active resources
make clean          # Remove build artifacts
```

---

## Estimated Cost

| Resource | Cost |
|----------|------|
| Kinesis on-demand | ~$0.08/GB ingested (stops when idle) |
| Lambda | Free tier (1M requests/month) |
| EMR Serverless | Pennies per Spark job run |
| DynamoDB | Free tier (<1 KB writes) |
| S3 | ~$0.023/GB/month |
| **Total (active dev day)** | **~$0.50–2.00/day** |

> **Cost control:** Nightly teardown workflow auto-destroys the dev environment at 1 AM UTC.
> Run `make tf-destroy` or `bash scripts/teardown_dev.sh` at end of day to be safe.

---

## Environment Variables

```bash
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=<your-account-id>
KINESIS_STREAM_NAME=clickstream-events-dev
DYNAMODB_TABLE_NAME=clickstream-sessions-dev
S3_BUCKET=clickstream-raw-<account-id>-dev
EMR_APPLICATION_ID=<from terraform output>
```

Use `.env` files locally (already in `.gitignore`). Use AWS SSM Parameter Store or
Secrets Manager for deployed values.

---

## Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Session timeout | 30 minutes | Industry standard (Google Analytics default) |
| Kinesis partition key | `user_id` | Preserves event ordering within sessions |
| DynamoDB billing | On-demand | No capacity planning, near-zero cost at low volume |
| DynamoDB TTL | 2 hours | Speed layer only needs hot sessions; auto-cleanup keeps costs near free tier |
| Late-arrival threshold | 5 minutes | Lambda skips these; Spark picks them up nightly |
| EMR initial capacity | 0 | Pay only during job execution; cold start ~90 s |
| S3 lifecycle (dev) | 7-day auto-delete | Prevents raw event accumulation costs |

See [`docs/tradeoffs.md`](docs/tradeoffs.md) for the full accuracy/latency analysis.

---

## References

- [REES46 Dataset (Kaggle)](https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store)
- [Lambda Architecture — Martin Fowler](https://martinfowler.com/bliki/LambdaArchitecture.html)
- [Kinesis Developer Guide](https://docs.aws.amazon.com/streams/latest/dev/introduction.html)
- [EMR Serverless Docs](https://docs.aws.amazon.com/emr/latest/EMR-Serverless-UserGuide/getting-started.html)
- [DynamoDB Single-Table Design](https://www.alexdebrie.com/posts/dynamodb-single-table/)

---

## License

MIT
