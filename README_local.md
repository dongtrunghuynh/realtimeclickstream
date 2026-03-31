# Clickstream Analytics Pipeline

> **Real-time user behaviour analytics on AWS** — event ingestion to queryable data lake in under 60 seconds.

[![CI](https://github.com/your-org/clickstream-analytics-pipeline/actions/workflows/ci-python.yml/badge.svg)](https://github.com/your-org/clickstream-analytics-pipeline/actions)
[![Terraform Plan](https://github.com/your-org/clickstream-analytics-pipeline/actions/workflows/terraform-plan.yml/badge.svg)](https://github.com/your-org/clickstream-analytics-pipeline/actions)
[![Coverage](https://codecov.io/gh/your-org/clickstream-analytics-pipeline/branch/main/graph/badge.svg)](https://codecov.io/gh/your-org/clickstream-analytics-pipeline)

---

## What This Is

A production-grade, serverless data pipeline that captures user interaction events (page views, clicks, purchases, searches) from web and mobile clients, processes them in real-time, and delivers structured data to a partitioned S3 data lake — queryable via Athena with schema managed by AWS Glue.

**Core capabilities:**
- Sub-60-second end-to-end latency from event emission to Athena-queryable output
- Exactly-once delivery semantics via Kinesis ordering and idempotent S3 writes
- Automatic schema discovery and partition management via Glue crawler
- Full observability: structured logs, X-Ray traces, CloudWatch dashboard, and alarms
- AI-assisted development workflow: Claude reviews every PR, triages every issue, and answers questions in PR comments

---

## Architecture

```
Web / Mobile Clients
        │  HTTPS POST /events
        ▼
  ┌─────────────┐
  │ API Gateway │  — rate limiting, auth, request validation
  └──────┬──────┘
         │  PutRecord
         ▼
  ┌──────────────────────┐
  │ Kinesis Data Streams │  — sharded by user_id, 168-hour replay window (prod)
  └──────────┬───────────┘
             │  trigger (batch, batchItemFailures enabled)
             ▼
  ┌──────────────────────────┐
  │  Lambda: stream_processor│  — decode → validate (Pydantic) → enrich → transform
  └────────┬─────────────────┘
           │                  └── failed records → SQS DLQ → CloudWatch alarm
    ┌──────┴──────┐
    ▼             ▼
┌───────┐  ┌────────────┐
│ S3    │  │ S3         │  — processed: Hive-partitioned NDJSON
│ Raw   │  │ Processed  │    event_type/year/month/day
└───────┘  └─────┬──────┘
                 │  daily crawler (or on-demand)
                 ▼
          ┌─────────────┐
          │ AWS Glue    │  — auto-discovers schema + partitions
          │ Catalog     │
          └──────┬──────┘
                 │  SQL
                 ▼
            ┌────────┐
            │ Athena │  — serverless queries, pay-per-scan
            └────────┘
```

### Design Decisions

| Decision | Rationale |
|---|---|
| Kinesis over SQS | Ordered delivery per user, multi-consumer fan-out, replayable |
| Python + Pydantic v2 | Fast validation, excellent error messages, auto-generates JSON schema |
| NDJSON over Parquet | Lambda can write directly; Athena queries both equally well at this scale |
| Hive partitioning by event_type + date | Optimal partition pruning for the most common Athena query patterns |
| Glue Crawler over manual schema | Zero-maintenance schema evolution; handles new event types automatically |
| ON_DEMAND Kinesis in prod | Variable traffic profile; ~3× cost reduction vs over-provisioned PROVISIONED mode |

---

## Repository Structure

```
├── CLAUDE.md                    ← AI context: architecture, standards, review criteria
├── README.md
├── Makefile                     ← make help
├── pyproject.toml               ← Python tooling (ruff, mypy, pytest, coverage)
├── terraform.tfvars.example
│
├── .github/
│   ├── CLAUDE.md                ← GitHub-workflow AI behaviour
│   ├── CODEOWNERS
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.yml
│   │   ├── feature_request.yml
│   │   └── data_quality.yml     ← dedicated template for data issues
│   └── workflows/
│       ├── ci-python.yml        ← lint + typecheck + test (Python 3.11 & 3.12 matrix)
│       ├── terraform-plan.yml   ← plan on every PR (dev + staging matrix)
│       ├── terraform-apply.yml  ← apply on merge (dev auto, staging/prod gated)
│       ├── claude-pr-review.yml ← AI code review on every PR
│       ├── claude-issue-triage.yml  ← auto-label + triage new issues
│       └── claude-pr-comment.yml    ← @claude answers questions in PR threads
│
├── infra/                       ← Terraform
│   ├── providers.tf / variables.tf / main.tf / outputs.tf
│   ├── environments/
│   │   ├── dev.tfvars
│   │   ├── staging.tfvars
│   │   └── prod.tfvars
│   └── modules/
│       ├── kinesis/             ← stream + optional enhanced fan-out
│       ├── lambda/              ← function + ESM + log group
│       ├── s3/                  ← versioned, encrypted, lifecycle
│       ├── glue/                ← database + crawler + Athena workgroup
│       ├── iam/                 ← least-privilege execution role
│       └── monitoring/          ← DLQ + SNS + 5 CloudWatch alarms + dashboard
│
└── src/
    └── stream_processor/
        ├── handler.py           ← Lambda entry point
        ├── models.py            ← Pydantic v2 event schema (single source of truth)
        ├── transformer.py       ← S3 key generation, batch grouping, NDJSON writer
        └── requirements.txt
```

---

## Event Schema

```json
{
  "event_id":   "uuid4",
  "event_type": "page_view | click | purchase | search | session_start | session_end | add_to_cart",
  "session_id": "uuid4",
  "user_id":    "string",
  "timestamp":  "ISO-8601 UTC",
  "page":   { "url": "string", "referrer": "string|null", "title": "string|null" },
  "device": { "type": "desktop|mobile|tablet", "os": "string", "browser": "string" },
  "geo":    { "country_code": "AU", "region": "QLD", "city": "Brisbane" },
  "properties": {}
}
```

S3 output partition: `processed/event_type=<type>/year=<Y>/month=<M>/day=<D>/<uuid>.ndjson`

---

## Getting Started

### Prerequisites
- Python 3.11+
- Terraform ≥ 1.7
- AWS CLI configured (or OIDC in CI)
- `make`

### Local development

```bash
# Install Python dependencies
make install

# Run linting, type checking, and tests
make ci

# Build Lambda deployment package
make build

# Deploy to dev
make deploy-dev
```

### Running tests

```bash
make test
# or directly:
pytest tests/unit/ -v --cov=src --cov-report=term-missing
```

Coverage must remain ≥90%. CI enforces this.

### Deploying

```bash
# Plan changes (review before applying)
make tf-plan ENV=staging

# Apply (staging requires manual approval in GitHub Actions)
make tf-apply ENV=staging
```

Prod deployments require a PR merged to `main` + 2 approvals in the GitHub `prod` environment.

---

## AI-Powered GitHub Workflow

This project uses Claude (via Anthropic API) for three automation workflows:

**1. PR Reviews** — Claude reviews every pull request automatically, checking for:
- Security issues (hardcoded credentials, IAM over-permissions)
- Missing error handling or type annotations
- Test coverage gaps
- Schema and architecture alignment with `CLAUDE.md`

**2. Issue Triage** — When a new issue is opened, Claude reads it, applies appropriate labels, assesses priority, and posts a triage comment pointing to the relevant codebase area.

**3. PR Q&A** — Mention `@claude` in any PR comment and Claude will answer your question in context of the actual code changes.

### Setup (one-time)

1. Add `ANTHROPIC_API_KEY` to **Settings → Secrets and variables → Actions**
2. Add AWS OIDC secrets: `AWS_ROLE_ARN_DEV`, `AWS_ROLE_ARN_STAGING`, `AWS_ROLE_ARN_PROD`
3. Add Terraform backend secrets: `TF_STATE_BUCKET`, `TF_LOCK_TABLE`
4. Enable GitHub Actions in your repo settings
5. Set up GitHub Environments (`dev`, `staging`, `prod`) with required reviewers for staging/prod

---

## Observability

The pipeline ships with a pre-built CloudWatch dashboard and 5 alarms:

| Alarm | Threshold | Meaning |
|---|---|---|
| Lambda Errors | ≥5 in 5 min | Processing failures — check DLQ |
| Lambda Duration p95 | >80% of timeout | Risk of function timeouts |
| DLQ Depth | ≥1 message | Events failing permanently |
| Kinesis Iterator Age p99 | >5 minutes | Lambda falling behind the stream |
| Lambda Throttles | ≥10 in 5 min | Concurrency limit hit |

All alarms notify via SNS → email. The dashboard URL is emitted as a Terraform output.

---

## Environments

| Environment | Kinesis Mode | Lambda Memory | Data Retention | Deploy Gate |
|---|---|---|---|---|
| dev | PROVISIONED (1 shard) | 256 MB | 7 days | Auto on merge |
| staging | PROVISIONED (2 shards) | 512 MB | 90 days | 1 approval |
| prod | ON_DEMAND | 1024 MB | 365 days | 2 approvals |

---

## Contributing

1. Branch from `main`: `feat/your-feature` or `fix/your-fix`
2. Commits follow Conventional Commits: `feat(lambda): add geo-enrichment`
3. Fill the PR template completely — Claude will review within minutes
4. CI must pass: `make ci`
5. Coverage must be ≥90%
6. Update `CLAUDE.md` if you change the architecture or event schema

See [CLAUDE.md](./CLAUDE.md) for full coding standards and review criteria.

---

## Tech Stack

**AWS:** Kinesis Data Streams · Lambda · S3 · Glue · Athena · CloudWatch · X-Ray · SQS · SNS · IAM

**Python:** 3.12 · Pydantic v2 · aws-xray-sdk · boto3

**IaC:** Terraform ≥ 1.7 · Remote state (S3 + DynamoDB)

**CI/CD:** GitHub Actions · OIDC auth · Environment gates

**AI:** Claude (Anthropic) · claude-code-action

**Quality:** ruff · mypy (strict) · pytest · codecov
