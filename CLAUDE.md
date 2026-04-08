# CLAUDE.md — Real-Time Clickstream Pipeline

> This file gives Claude (and any AI assistant) full context on this project so it can
> provide accurate, relevant help without re-explaining the stack every session.

---

## Project Summary

A **Lambda Architecture** streaming analytics pipeline that ingests e-commerce clickstream
events, processes them in real-time via AWS Lambda + Kinesis, batch-reconciles them
nightly with Spark on EMR Serverless, and surfaces an accuracy/latency tradeoff dashboard.

**Dataset:** REES46 E-Commerce Behaviour Dataset (~20M events, Kaggle)
**Goal:** Demonstrate you understand *why* Lambda Architecture exists, not just how to build it.

---

## Architecture Overview

```
[Python Event Simulator]
        │
        ▼ (Kinesis Data Streams — on-demand)
[AWS Lambda — Sessionizer]
        │  5-second tumbling windows
        │  30-min inactivity session boundary
        ▼
[DynamoDB — Real-Time Session State]       ←── Speed Layer
        │
        │                    [S3 — Raw Events (Parquet)]
        │                           │
        │                    [EMR Serverless — Spark Batch]
        │                    nightly reconciliation
        │                           │
        │                    [S3 — Corrected Sessions]   ←── Batch Layer
        │                           │
        └──────────────────────────►▼
                         [Athena Views — Accuracy/Latency Dashboard]
```

---

## Skills Being Built

| Skill | Where |
|-------|-------|
| Kinesis producer/consumer patterns | `src/event_simulator/`, `src/lambda/sessionizer/` |
| Lambda event processing | `src/lambda/` |
| Spark sessionization | `src/spark/` |
| DynamoDB single-table design | `terraform/modules/dynamodb/`, `src/lambda/shared/` |
| Terraform modules + workspaces | `terraform/` |
| Lambda Architecture tradeoffs | `src/dashboard/`, `athena/views/` |

---

## Repo Layout (Quick Reference)

```
clickstream-pipeline/
├── CLAUDE.md               ← You are here
├── SKILL.md                ← Git/PR/code-review workflow guide
├── README.md               ← Project intro for humans/employers
├── .github/                ← PR templates, CI workflows, CODEOWNERS
├── docs/                   ← Architecture deep-dives, setup guide, step-by-step
├── terraform/              ← All IaC — modules + dev/prod workspaces
├── src/
│   ├── event_simulator/    ← Python: replays REES46 into Kinesis
│   ├── lambda/             ← Lambda handlers + shared utilities
│   ├── spark/              ← EMR Serverless Spark jobs
│   └── dashboard/          ← Accuracy/latency comparison scripts
├── athena/                 ← SQL views for speed vs batch layer comparison
├── data/schemas/           ← JSON schemas for event validation
├── tests/                  ← Unit + integration tests
└── scripts/                ← Shell helpers (setup, teardown, run)
```

---

## Key Design Decisions (Ask Claude About These)

1. **Session boundary:** 30-minute inactivity window (industry standard). If a user is
   idle >30 min, the next event starts a new session.

2. **Late-arrival handling:** Events arriving >5 minutes late are flagged in the raw
   Kinesis record. Lambda ignores them for real-time state but persists them to S3.
   Spark picks them up during nightly reconciliation.

3. **DynamoDB single-table design:** Session ID is the partition key. A `TTL` attribute
   auto-expires hot session records after 2 hours, keeping costs near free tier.

4. **Terraform workspaces:** `dev` and `prod`. Always `terraform workspace select dev`
   before experimenting. `terraform destroy` in dev = $0.

5. **Cost guard:** Kinesis on-demand turns off automatically when no records are produced.
   EMR Serverless charges only for vCPU/memory during job execution — pennies per run.

---

## Environment Variables (Never Commit These)

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

## How to Ask Claude for Help

**Good prompts in this project:**
- "Review this Lambda sessionizer for edge cases in session boundary detection"
- "Help me write a Spark job that partitions late-arrival events by hour"
- "Write a Terraform module for DynamoDB with TTL and on-demand billing"
- "Explain why my Kinesis shard iterator might be returning empty records"
- "Help me write an Athena view that compares real-time vs batch session counts"

**Include context when asking:**
- Paste the relevant function/module
- Mention which workspace (dev/prod)
- Mention the event type (view, cart, purchase)

---

## Common Gotchas

| Problem | Cause | Fix |
|---------|-------|-----|
| Lambda timeout | Kinesis batch too large | Reduce `BisectBatchOnFunctionError`, cap batch size at 100 |
| DynamoDB throttling | Burst writes | Switch to on-demand billing mode |
| EMR job fails silently | Missing IAM role permissions | Check CloudWatch Logs under `/aws/emr-serverless/` |
| Out-of-order events in Lambda | Kinesis ordering per shard | Use `ApproximateArrivalTimestamp` not `event_time` for windowing |
| Athena slow queries | No partitioning on S3 | Ensure Spark writes with `partitionBy("year","month","day","hour")` |

---

## Teardown (Critical — Cost Control)

```bash
# Always destroy dev resources when done for the day
cd terraform
terraform workspace select dev
terraform destroy -var-file=environments/dev.tfvars

# Verify $0 cost
aws kinesis list-streams
aws dynamodb list-tables
```

---

## References

- [REES46 Dataset (Kaggle)](https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store)
- [Kinesis Developer Guide](https://docs.aws.amazon.com/streams/latest/dev/introduction.html)
- [EMR Serverless Docs](https://docs.aws.amazon.com/emr/latest/EMR-Serverless-UserGuide/getting-started.html)
- [Lambda Architecture (Martin Fowler)](https://martinfowler.com/bliki/LambdaArchitecture.html)
- [DynamoDB Single-Table Design](https://www.alexdebrie.com/posts/dynamodb-single-table/)
