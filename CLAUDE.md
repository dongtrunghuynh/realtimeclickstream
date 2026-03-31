# CLAUDE.md — Clickstream Analytics Pipeline

This file is the single source of truth for Claude when reviewing code, triaging issues,
answering PR questions, and assisting with development. Read this fully before any action.

---

## 🎯 What This Project Is

A **production-grade, real-time clickstream analytics pipeline** built on AWS. It ingests
user interaction events (page views, clicks, purchases, searches) from web and mobile clients,
processes them in near-real-time, and delivers structured, queryable data to a partitioned
data lake — enabling downstream analytics, dashboards, and ML feature engineering.

**Primary stakeholders:** Data Engineers, Analytics Engineers, and Data Scientists.  
**Business goal:** Reduce time-to-insight on user behaviour from hours (batch ETL) to minutes.

---

## 🏗️ Architecture

```
Clients (web/mobile)
        │  HTTPS POST /events
        ▼
  [API Gateway]  ──── rate limiting, auth, schema validation
        │
        ▼
[Kinesis Data Streams]  ──── sharded by user_id for ordering guarantees
        │  trigger (batch)
        ▼
  [AWS Lambda]           ──── decode → validate → enrich → transform
   stream_processor       ──── writes raw + processed in parallel
        │
   ┌────┴────┐
   ▼         ▼
[S3 Raw]  [S3 Processed]   ──── Hive-partitioned NDJSON (processed)
               │
               ▼
       [AWS Glue Crawler]   ──── auto-discovers schema, updates catalog daily
               │
               ▼
       [Glue Data Catalog]  ──── single source of schema truth
               │
               ▼
          [Athena]          ──── SQL query layer for analysts & dashboards
               │
               ▼
        [QuickSight / BI]   ──── business dashboards (out of scope for this repo)
```

**Dead-letter path:** Failed Lambda batches → SQS DLQ → CloudWatch alarm → PagerDuty.

---

## 📁 Repository Layout

```
.
├── CLAUDE.md                    ← you are here
├── README.md                    ← public-facing docs
├── Makefile                     ← all dev tasks (make help)
├── pyproject.toml               ← Python tooling config
├── terraform.tfvars.example     ← copy to terraform.tfvars for local work
│
├── .github/
│   ├── CLAUDE.md                ← GitHub-workflow-specific Claude context
│   ├── CODEOWNERS               ← auto-assign reviewers
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.yml
│   │   ├── feature_request.yml
│   │   └── data_quality.yml
│   └── workflows/
│       ├── ci-python.yml        ← lint, type-check, test on every push
│       ├── terraform-plan.yml   ← plan on every PR
│       ├── terraform-apply.yml  ← apply on merge to main
│       ├── claude-pr-review.yml ← AI code review on every PR
│       ├── claude-issue-triage.yml ← auto-label & summarise new issues
│       └── claude-pr-comment.yml   ← answer @claude questions in PR comments
│
├── infra/                       ← all Terraform
│   ├── providers.tf
│   ├── variables.tf
│   ├── main.tf
│   ├── outputs.tf
│   ├── environments/
│   │   ├── dev.tfvars
│   │   ├── staging.tfvars
│   │   └── prod.tfvars
│   └── modules/
│       ├── kinesis/             ← data stream + enhanced fan-out
│       ├── lambda/              ← function + event source mapping
│       ├── s3/                  ← raw + processed buckets
│       ├── glue/                ← crawler + catalog database
│       ├── iam/                 ← least-privilege roles
│       └── monitoring/          ← CloudWatch dashboards + alarms + DLQ
│
└── src/
    └── stream_processor/
        ├── handler.py           ← Lambda entry point
        ├── models.py            ← Pydantic event schemas
        ├── transformer.py       ← enrichment & normalisation logic
        └── requirements.txt
```

---

## 🧠 Event Schema

Every clickstream event MUST conform to this shape (enforced by Pydantic in `models.py`):

```json
{
  "event_id":    "uuid4",
  "event_type":  "page_view | click | purchase | search | session_start | session_end",
  "session_id":  "uuid4",
  "user_id":     "string (anonymous or authenticated)",
  "anonymous_id":"string (pre-auth identifier)",
  "timestamp":   "ISO-8601 UTC",
  "page": {
    "url":      "string",
    "referrer": "string | null",
    "title":    "string | null"
  },
  "device": {
    "type":       "desktop | mobile | tablet",
    "os":         "string",
    "browser":    "string",
    "user_agent": "string"
  },
  "geo": {
    "country_code": "ISO 3166-1 alpha-2 | null",
    "region":       "string | null",
    "city":         "string | null"
  },
  "properties": {}
}
```

**S3 output partition scheme:**
`s3://<bucket>/processed/event_type=<type>/year=<Y>/month=<M>/day=<D>/<uuid>.ndjson`

---

## 🛠️ Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Ingestion | Kinesis Data Streams | Ordered, replayable, exactly-once semantics |
| Compute | Python 3.12 Lambda | Serverless, auto-scales with shard count |
| Schema | Pydantic v2 | Fast validation, clear error messages |
| Storage | S3 + Parquet-compatible NDJSON | Cost-effective, Athena-queryable |
| Catalog | AWS Glue | Schema discovery, partition management |
| Query | Amazon Athena | Serverless SQL, pay-per-query |
| IaC | Terraform ≥ 1.7 | Reproducible, state-managed infra |
| CI/CD | GitHub Actions | Native integration, matrix testing |
| AI | Claude via Anthropic API | PR review, issue triage, Q&A |
| Observability | CloudWatch + X-Ray | Metrics, traces, structured logs |

---

## ✅ Coding Standards

### Python
- **Style:** PEP 8, enforced by `ruff` (line length 100)
- **Types:** All functions must have type annotations. `mypy --strict` must pass.
- **Validation:** Use Pydantic models — never `dict` access without validation
- **Error handling:** Specific exceptions, never bare `except`. Log before re-raising.
- **Logging:** Structured JSON only. Use `logger.info("msg", extra={...})`. No f-strings in log calls.
- **Tests:** ≥90% coverage required. Unit tests mock AWS. Integration tests use `moto`.
- **Imports:** stdlib → third-party → local. Separated by blank lines.

### Terraform
- **Version:** `required_version = ">= 1.7"`
- **Naming:** `<project>-<environment>-<resource-type>-<descriptor>` e.g. `clickstream-dev-kinesis-events`
- **Variables:** Every variable must have `description` and `type`. Sensitive vars must have `sensitive = true`.
- **Modules:** All reusable infra lives in `infra/modules/`. No inline resource blocks in `main.tf`.
- **Outputs:** Every module must expose `arn`, `id`, and `name` for every major resource.
- **State:** Remote state in S3 + DynamoDB lock. Never commit `.tfstate`.

### Git
- **Branches:** `feat/`, `fix/`, `chore/`, `docs/` prefixes
- **Commits:** Conventional Commits format: `feat(lambda): add geo-enrichment step`
- **PRs:** Fill the PR template fully. Link the related issue. One concern per PR.

---

## 🔍 What Claude Should Focus on During PR Reviews

### Critical (block merge)
- Any hardcoded AWS credentials, secrets, or API keys
- Missing IAM least-privilege (e.g. `*` actions or resources)
- Missing error handling in Lambda (uncaught exceptions kill the batch)
- Schema validation bypassed or weakened
- S3 bucket missing public access block or TLS-only policy
- Tests missing for new business logic
- Terraform resources missing tags

### Important (request changes)
- Missing type annotations
- Bare `except` clauses
- CloudWatch alarms not added for new Lambda functions
- New variables without descriptions
- Functions longer than 50 lines (suggest splitting)
- Missing docstrings on public functions

### Suggestions (non-blocking)
- Performance improvements (e.g. batch S3 puts vs individual)
- Cost optimisation opportunities
- Readability improvements
- Additional test cases for edge cases

---

## 🏷️ Issue Labels (for triage)

| Label | When to apply |
|---|---|
| `bug` | Something broken in production or tests |
| `data-quality` | Events dropped, schema violations, bad output |
| `infrastructure` | Terraform / AWS resource changes |
| `lambda` | Stream processor code changes |
| `pipeline` | End-to-end data flow issues |
| `security` | IAM, encryption, access control |
| `performance` | Latency, cost, throughput |
| `documentation` | README, CLAUDE.md, docstrings |
| `good-first-issue` | Small, well-defined task for new contributors |
| `priority: high` | Impacts data freshness or correctness in prod |
| `priority: low` | Nice-to-have, no production impact |

---

## 🌍 Environments

| Env | AWS Account | Kinesis Mode | Lambda Concurrency | Data Retention |
|---|---|---|---|---|
| dev | shared-dev | PROVISIONED (1 shard) | unreserved | 7 days S3 |
| staging | shared-staging | PROVISIONED (2 shards) | 20 | 30 days S3 |
| prod | prod-dedicated | ON_DEMAND | 100 | 365 days S3 |

---

## 🚀 Common Tasks

```bash
make help           # all available commands
make install        # install Python deps
make test           # run tests with coverage
make build          # package Lambda zip
make tf-plan ENV=dev        # plan dev changes
make tf-apply ENV=dev       # apply dev changes
make deploy-dev             # full build + deploy to dev
```

---

## ⚠️ Known Constraints / Gotchas

1. **Kinesis ordering:** Records are ordered per shard. Multi-shard consumers must not assume global order.
2. **Lambda retries:** The event source mapping retries on error. Always return `batchItemFailures` for partial failures — never raise an unhandled exception unless the whole batch should retry.
3. **Glue crawler lag:** Schema changes appear in Athena only after the next crawler run (~daily). For urgent schema changes, trigger the crawler manually or via Lambda.
4. **S3 eventual consistency:** S3 is now strongly consistent for new objects, but Athena partition projection requires the Glue catalog to be current.
5. **Cold starts:** Lambda cold starts are ~800ms on first invocation. Kinesis batching absorbs this. Do not optimise prematurely.
6. **Cost:** Kinesis charges per shard-hour + PUT payload unit. ON_DEMAND mode is ~3× cheaper for variable throughput. Review monthly.
