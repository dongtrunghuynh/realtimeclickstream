# Architecture Deep Dive

## Lambda Architecture — Why It Exists

Lambda Architecture solves a fundamental tension in data systems:

- **Speed layer** (real-time): low latency, approximate answers
- **Batch layer** (historical): high latency, correct answers

Neither alone is sufficient for business analytics. A retailer needs:
- Sub-minute session tracking for live A/B tests → speed layer
- Accurate revenue reporting for finance → batch layer

This pipeline makes the tradeoff **explicit and measurable**.

---

## Data Flow

### Speed Path (sub-minute latency)

```
CSV → Simulator → Kinesis → Lambda → DynamoDB
  └─ late arrivals bypassed to S3 only
```

1. Simulator reads REES46 CSV, publishes events to Kinesis
2. Lambda is triggered every ~5 seconds (Kinesis polling interval)
3. Lambda sessionizes events in the batch using 30-min inactivity rule
4. Session state written to DynamoDB (TTL = 2 hours)
5. Late arrivals (`is_late_arrival=True`) written to S3 but NOT DynamoDB

### Batch Path (~8 hour latency)

```
S3 (raw Parquet) → EMR Serverless Spark → S3 (corrected Parquet) → Athena
```

1. Lambda also writes ALL events to S3 as Parquet
2. Nightly Spark job reads full day's events from S3
3. Spark re-sessionizes with complete data (including late arrivals)
4. Corrected sessions written to separate S3 prefix
5. Athena views compare speed vs batch layer outputs

---

## Session Boundary Logic

**Rule:** If a user is inactive for >30 minutes, the next event starts a new session.

```
[view] -5min- [view] -2min- [cart] -35min- [view]  ← NEW SESSION
 ↑_____________SESSION 1__________↑            ↑___SESSION 2___
```

**Implementation challenge:** Events arrive out of order in Kinesis.

- Lambda sorts each batch by `event_time` before sessionizing
- But late arrivals (>5 min late) may arrive in a future Lambda batch
- Real-time DynamoDB state will be wrong until Spark corrects it

---

## DynamoDB Schema (Single-Table Design)

| Attribute | Type | Description |
|-----------|------|-------------|
| `session_id` (PK) | String | user_session from REES46 |
| `user_id` (SK) | String | user_id from REES46 |
| `event_count` | Number | Rolling count |
| `cart_total` | Number | Running sum of cart prices |
| `converted` | Boolean | Purchase event seen |
| `session_start` | String | ISO8601 first event time |
| `last_event_time` | String | ISO8601 most recent event |
| `expires_at` | Number | Unix epoch TTL (2 hours after last event) |

**GSI:** `user_id-index` — partition key `user_id` for user-level queries.

---

## S3 Layout

```
s3://clickstream-raw-<account>-<env>/
├── events/
│   └── year=2024/month=10/day=15/hour=09/
│       └── part-00000.parquet
│       └── part-00001.parquet
└── late-arrivals/
    └── year=2024/month=10/day=15/hour=09/
        └── part-00000.parquet

s3://clickstream-corrected-<account>-<env>/
└── sessions/
    └── year=2024/month=10/day=15/
        └── part-00000.parquet
```

---

## Kinesis Ordering Guarantees

- **Within a shard:** Records are ordered by arrival time
- **Partition key = `user_id`:** All events from one user go to the same shard
- **Implication:** Events from the same user are ordered in Lambda — but only if they arrive on time. Late arrivals break this guarantee.

This is why Lambda sessionization is approximate.

---

## IAM Design (Least Privilege)

| Role | Permissions |
|------|-------------|
| Lambda execution | Kinesis:GetRecords, DynamoDB:PutItem/UpdateItem/GetItem, S3:PutObject, CloudWatch:PutMetricData |
| EMR Serverless job | S3:GetObject/PutObject (specific buckets only), Glue:GetTable/CreateTable |
| Terraform | Only used locally — uses your IAM user credentials |

---

## Cost Architecture

| Resource | Billing Model | Dev Daily Cost |
|----------|--------------|---------------|
| Kinesis on-demand | $0.08/GB ingested | ~$0.02 (100k events) |
| Lambda | 1M free/month | $0 |
| DynamoDB | First 25GB free | $0 |
| EMR Serverless | Per vCPU-hour + GB-hour | ~$0.05 per job run |
| S3 | $0.023/GB stored | <$0.01 |
| Athena | $5/TB scanned | <$0.01 |
| **Total** | | **~$0.10/day** |

Key cost controls:
- Kinesis on-demand (not provisioned)
- DynamoDB TTL prevents unbounded storage growth  
- EMR auto-stop after 15 min idle
- Terraform destroy at end of each day
