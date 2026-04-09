# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## What This Project Is

A **Lambda Architecture** pipeline on AWS: e-commerce clickstream events flow into Kinesis → Lambda sessionizer (speed layer, DynamoDB) and simultaneously to S3, where a nightly Spark job on EMR Serverless reconciles late arrivals (batch layer). An Athena-backed dashboard quantifies the accuracy/latency tradeoff between the two layers.

**Dataset:** REES46 E-Commerce Behaviour Dataset (Kaggle, ~20M events). Sample at `data/sample/2019-Nov.csv`.

---

## Common Commands

```bash
# Install
pip install -r requirements.txt -r requirements-dev.txt

# Lint
ruff check src/ tests/
ruff check --fix src/ tests/    # auto-fix

# Test
pytest tests/unit/ -v                                          # all unit tests
pytest tests/unit/test_sessionizer.py -v                       # single file
pytest tests/unit/test_sessionizer.py::TestSessionState -v     # single class
pytest tests/unit/ -v --cov=src --cov-report=term-missing      # with coverage

# Terraform (always use dev workspace)
cd terraform
terraform workspace select dev
terraform plan  -var-file=environments/dev.tfvars
terraform apply -var-file=environments/dev.tfvars
terraform destroy -var-file=environments/dev.tfvars   # always destroy at end of day

# Run simulator
python src/event_simulator/simulator.py --rate 100 --duration 300 --late-arrival-pct 0.05
python src/event_simulator/simulator.py --rate 200 --duration 60   # quick smoke test

# Submit Spark batch job (requires deployed EMR Serverless)
bash scripts/submit_spark_job.sh session_stitcher
bash scripts/submit_spark_job.sh late_arrival_handler

# Local dashboard (no AWS needed)
python src/dashboard/local_report.py --sample

# DLQ inspection
python src/lambda/sessionizer/dlq_handler.py --list
python src/lambda/sessionizer/dlq_handler.py --reprocess --dry-run

# Full pipeline end-to-end
bash scripts/run_full_pipeline.sh --quick   # fast smoke test
```

Or use `make help` to see all Makefile targets.

---

## Architecture: How Data Flows

```
simulator.py
  └─► Kinesis (partition key = user_id, preserves ordering per session)
        ├─► Lambda sessionizer (batch=100, 5-sec tumbling window)
        │     ├─► on-time events → DynamoDB (speed layer, 2-hr TTL)
        │     └─► ALL events → S3 events/year=Y/month=M/day=D/hour=H/
        │         late arrivals → S3 late-arrivals/year=Y/...
        └─► (same S3 writes above)

Nightly:
  DynamoDB export → S3 (NDJSON)
  EMR Serverless Spark:
    session_stitcher.py    ← re-sessionizes full history including late arrivals
    late_arrival_handler.py
    → S3 corrected-sessions/ (Parquet, partitioned by year/month/day)

Athena (Glue catalog):
  5 external tables (raw_events, late_arrivals, batch_sessions,
                     realtime_sessions_raw, restatement_audit)
  3 views: realtime_sessions, batch_sessions_v, accuracy_comparison
  → accuracy_latency_dashboard.py (the key deliverable)
```

**Critical data-flow facts that aren't obvious from any single file:**
- Lambda writes EVERY event to S3 (including late arrivals), but only on-time events to DynamoDB. Spark reads from S3 — not from DynamoDB.
- `user_id` is the Kinesis partition key (not `session_id`) so all events from the same user land on the same shard, preserving ordering needed by the sessionizer.
- Lambda sorts events within each batch by `event_time` before sessionizing, because Kinesis delivery order ≠ event timestamp order.
- Spark re-creates session IDs from scratch (`batch_session_id`). These are different identifiers than Lambda's `session_id`. The `accuracy_comparison` view joins them via `user_id` + time overlap.

---

## Key Design Decisions

**Session boundary:** 30-minute inactivity. If gap between consecutive events (by `event_time`) > 30 min, a new session begins. Same logic in both Lambda (`session_state.py`) and Spark (`session_stitcher.py`) — they must stay in sync.

**Late arrivals:** Events where `is_late_arrival=True` (held back 2–15 min by the simulator). Lambda skips DynamoDB writes for these but still writes to S3 under the `late-arrivals/` prefix. Spark picks them up and may stitch them into an existing session or create a restatement.

**DynamoDB idempotency:** Lambda uses conditional `put_item` to handle Kinesis at-least-once delivery. The condition checks `last_event_time` to avoid stale overwrites.

**Terraform workspaces:** `dev` and `prod`. The backend state bucket (`real-time-streaming-1`) must exist before `terraform init`. Run `bash scripts/setup.sh` once to create it.

---

## Coverage Configuration

Spark and dashboard files are excluded from coverage measurement (they require live AWS services):

```toml
# pyproject.toml
[tool.coverage.run]
omit = [
    "src/spark/*",
    "src/dashboard/*",
    "src/event_simulator/simulator.py",
    "src/event_simulator/config.py",
]
```

The CI gate is `--cov-fail-under=70`. Integration tests (marked `@pytest.mark.integration`) are skipped by default — they require a live AWS dev environment.

---

## Infrastructure Modules

Six Terraform modules in `terraform/modules/`:

| Module | Key facts |
|--------|-----------|
| `kinesis` | ON_DEMAND mode, 24-hr retention, KMS encryption |
| `dynamodb` | Single-table, PK=`session_id`, GSI on `user_id`, TTL=2hr, PITR enabled |
| `lambda` | Python 3.12, 512MB, 60s timeout, bisect-on-error, SQS DLQ |
| `emr_serverless` | emr-7.0.0 (Spark 3.5), 0 initial capacity, auto-stop 15min |
| `s3_athena` | 3 buckets (raw, corrected, athena-results), Athena workgroup, Glue DB |
| `cloudwatch` | Dashboard + optional alarms, 7-day log retention |

---

## CI/CD

Four workflows in `.github/workflows/`:

- **ci.yml** — ruff lint → pytest (70% cov) → terraform validate/fmt → TruffleHog secret scan
- **deploy.yml** — unit tests gate → build Lambda zip → terraform apply dev (auto on push to main) / prod (manual)
- **nightly_spark.yml** — daily 2 PM UTC: DynamoDB export → Spark session_stitcher + late_arrival_handler
- **nightly_teardown.yml** — daily 1 PM UTC: `terraform destroy` dev (cost control)

GitHub secrets required: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (dev), `AWS_ACCESS_KEY_ID_PROD`, `AWS_SECRET_ACCESS_KEY_PROD` (prod).

---

## Common Gotchas

| Problem | Cause | Fix |
|---------|-------|-----|
| Lambda timeout | Kinesis batch too large | Already capped at 100 + bisect-on-error enabled |
| EMR job fails silently | IAM permissions | Check CloudWatch `/aws/emr-serverless/` |
| Athena slow queries | Missing partition pruning | Spark writes use `partitionBy("year","month","day")` — check partition projection in `create_tables.sql` |
| `terraform init` fails | State bucket missing | Run `bash scripts/setup.sh` first |
| Coverage below 70% | Spark/CLI files included | Check `[tool.coverage.run].omit` in `pyproject.toml` |
