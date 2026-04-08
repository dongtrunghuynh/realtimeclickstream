# Interview Preparation Guide — Clickstream Pipeline

> This project is designed to make you dangerous in data engineering interviews.
> Use this guide to prepare answers before any technical screen or onsite.
> Every answer maps directly to code you wrote — never bluff.

---

## The 60-Second Project Pitch

> Memorise a version of this. Deliver it confidently in 60 seconds flat.

"I built a real-time clickstream analytics pipeline on AWS using Lambda Architecture.
The pipeline ingests e-commerce browse events from a Kinesis stream, sessionises them
in real-time with a Lambda function, and writes session state to DynamoDB — giving
sub-30-second latency. In parallel, all events land in S3 as Parquet. A nightly Spark
job on EMR Serverless re-processes everything including late-arriving events that the
real-time path couldn't handle, producing a corrected batch view in S3.

The standout piece is a quantitative dashboard that compares the two layers — showing
exactly how many sessions the real-time path got wrong and what the revenue discrepancy
was. That analysis demonstrates I understand *why* Lambda Architecture exists, not just
how to wire it together."

---

## Core Concepts — Be Ready to Explain These

### 1. What is Lambda Architecture?

**One-sentence answer:** A data system design that runs a real-time speed layer for
low-latency approximate results alongside a batch layer for high-latency accurate results,
then merges them in a serving layer.

**Follow-up: "Why not just use one or the other?"**
- Speed layer alone: you'll miss late-arriving events and have incorrect session counts
- Batch layer alone: you have 8-hour latency — useless for live A/B tests or fraud detection
- Lambda Architecture: get both. Pay for accuracy with latency; pay for latency with accuracy.

**Point to your code:** `src/dashboard/accuracy_latency_dashboard.py` — this is the serving
layer. It queries both DynamoDB (speed) and Athena (batch) and shows the tradeoff in numbers.

---

### 2. What is sessionization?

**One-sentence answer:** The process of grouping raw user events into logical "sessions" using
an inactivity timeout — if a user is idle for >30 minutes, the next event starts a new session.

**The streaming challenge:** Events don't always arrive in order. A purchase event that
arrived 8 minutes late might belong to a session that Lambda already closed.

**Point to your code:**
- `src/lambda/sessionizer/session_state.py` — real-time sessionization
- `src/spark/session_stitcher.py` — batch re-sessionization with Spark window functions

---

### 3. What is Kinesis at-least-once delivery and why does it matter?

**Answer:** Kinesis guarantees every record will be delivered at least once to consumers.
During shard re-balancing or Lambda retries, the same record can be processed twice.
If your Lambda handler isn't idempotent — if it blindly increments a counter — you'll
double-count events.

**How you handled it:** DynamoDB `put_item` with a conditional expression checks that the
incoming `event_count` isn't already present before writing. If a record is replayed, the
write is a no-op.

**Point to your code:** `src/lambda/shared/dynamodb_client.py` — `put_session()`.

---

### 4. Why does partition key choice matter in Kinesis?

**Answer:** Kinesis ordering is only guaranteed within a shard. If you use a random
partition key, the same user's events can land on different shards and arrive at Lambda
out of order. By using `user_id` as the partition key, all of one user's events go to
the same shard, preserving ordering.

**The tradeoff:** If one user generates disproportionate traffic (a celebrity, a bot),
they can saturate a single shard. Mitigate with per-shard limits or a composite key.

**Point to your code:** `src/event_simulator/kinesis_producer.py` — `_build_records()`.

---

### 5. Explain DynamoDB single-table design

**Answer:** In single-table design, all entities in an application live in one DynamoDB
table. Access patterns are modelled up front and encoded in the primary key structure.
This avoids joins (DynamoDB has none) and enables efficient lookups.

**In this project:**
- PK: `session_id` — fast lookup by session (Lambda's main access pattern)
- GSI: `user_id-index` — fast lookup of all sessions for a user (dashboard queries)
- TTL: `expires_at` — auto-deletes hot session records after 2 hours, keeping costs ~$0

**Why not use RDS?** Session writes happen at up to 10,000/sec. DynamoDB scales
horizontally with consistent single-digit millisecond latency at any scale. RDS would
require read replicas and connection pooling just to handle Lambda concurrency.

**Point to your code:** `terraform/modules/dynamodb/main.tf`.

---

### 6. How does Spark sessionization differ from Lambda sessionization?

| | Lambda (speed layer) | Spark (batch layer) |
|---|---|---|
| Input | One Kinesis polling batch (~5s) | Full day's events from S3 |
| Late arrivals | Skipped — written to S3 only | Included — full dataset |
| Ordering | Within-shard only | Global sort across all events |
| Window function | Manual 30-min inactivity check | `session_window()` / lag-based |
| Output | DynamoDB (per session) | Parquet on S3 (all sessions) |
| Accuracy | Approximate | Ground truth |

**Point to your code:** `src/spark/session_stitcher.py` — `sessionize()` and `aggregate_sessions()`.

---

### 7. What is Terraform and why use it?

**Answer:** Terraform is an Infrastructure-as-Code tool that lets you define AWS
resources in declarative `.tf` files and apply them reproducibly. Every resource in this
project — the Kinesis stream, Lambda, DynamoDB table, S3 buckets, EMR application — was
created with `terraform apply` and can be deleted with `terraform destroy`.

**Why it matters for employers:** A pipeline that can't be torn down safely is a
liability. `terraform destroy` brings cost to exactly $0 in 2 minutes.

**Workspaces:** `dev` and `prod` workspaces share the same modules but use different
variable files (`dev.tfvars`, `prod.tfvars`). The state is isolated per workspace.

**Point to your code:** `terraform/modules/` — each AWS service has its own module.

---

## Behavioural Questions — Data Engineering Specific

### "Tell me about a technical tradeoff you made."

"In the Lambda sessionizer, I had a choice: process late-arriving events in real-time
and risk incorrect session state, or skip them and let Spark correct them later. I chose
to skip them — `is_late_arrival=True` events are written to S3 but not to DynamoDB.

The concrete tradeoff: the speed layer is faster to build, cheaper to run, and easier
to reason about. The accuracy hit is quantified in my dashboard — in a typical run with
8% late arrivals, about 3% of sessions needed restatement and the average revenue
discrepancy was $X. For live dashboards and A/B tests, that's acceptable. For financial
reporting, you use the batch-reconciled Athena view."

---

### "How would you handle a sudden 10x spike in event volume?"

"Kinesis on-demand mode handles this automatically — it scales write capacity
without intervention and charges per GB ingested rather than per shard. Lambda
scales concurrently up to the account limit (1000 by default, requestable higher).

The only bottleneck would be DynamoDB. I've configured it with on-demand billing
(PAY_PER_REQUEST), so it also scales automatically. If I expected sustained high
volume I'd increase the provisioned capacity or add a write buffer with SQS."

---

### "What would you change if this needed to process 1 billion events per day?"

"At that scale I'd replace Kinesis with Apache Kafka on MSK — more consumer groups,
better replay, lower cost per GB. I'd replace the Lambda sessionizer with Apache Flink
for stateful streaming with exactly-once semantics. The batch layer stays as Spark but
I'd move to Databricks or Apache Iceberg for better incremental processing and ACID
transactions on S3."

---

## Numbers to Know (fill in after running `make dashboard`)

| Metric | Your Result |
|--------|------------|
| Total events simulated | |
| Events per second sustained | |
| Lambda average duration | |
| Lambda p99 duration | |
| DynamoDB write latency p99 | |
| Sessions in speed layer | |
| Sessions in batch layer | |
| Sessions requiring restatement | % |
| Avg revenue discrepancy | $ |
| Total revenue restated | $ |
| Pipeline end-to-end latency (speed) | |
| Pipeline end-to-end latency (batch) | |

---

## Things NOT to Say

❌ "I used Lambda Architecture because it's best practice."
✅ "I used Lambda Architecture because the business needs both sub-minute latency
for live dashboards AND accurate revenue figures for finance, and those requirements
conflict. Lambda Architecture is the explicit tradeoff mechanism."

❌ "Kinesis is like Kafka."
✅ "Kinesis and Kafka solve the same problem — durable, ordered event streaming —
but differ in operational model: Kinesis is fully managed and simpler to operate;
Kafka gives more control over retention, consumer groups, and connectors."

❌ "DynamoDB is a NoSQL database."
✅ "DynamoDB is a key-value / document store optimised for single-digit millisecond
latency at any scale. The design constraint is that you must model access patterns
up front — there are no joins and no ad-hoc queries without a GSI."

❌ "Terraform is like CloudFormation."
✅ "Both are IaC tools. Terraform is cloud-agnostic, has a richer module ecosystem,
and a cleaner state management model. CloudFormation is AWS-native and integrates
more deeply with IAM. For a project that might expand beyond AWS, Terraform is the
better default."

---

## Quick-Reference Architecture Diagram

```
[REES46 CSV]
     │
[simulator.py] ──────────────────── 8% late arrivals (held, then released)
     │ user_id partition key
     ▼
[Kinesis Data Streams — on-demand]
     │                        │
     │ (on-time events)       │ (ALL events)
     ▼                        ▼
[Lambda — Sessionizer]    [S3 — Raw Events]
 30-min inactivity             │
 Cart total running sum        │ (nightly)
     │                   [EMR Serverless — Spark]
     ▼                    session_stitcher.py
[DynamoDB]                late_arrival_handler.py
 Speed Layer ◄─────────────────┼──────── [S3 — Corrected Sessions]
 <30s latency                  │
                          [Athena Views]
                               │
                    [accuracy_latency_dashboard.py]
                    side-by-side: speed vs batch
```
