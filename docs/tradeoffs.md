# Lambda Architecture — Accuracy / Latency Tradeoff Analysis

> Complete this document after running the pipeline for a simulated day.
> This is your primary interview deliverable — the quantitative proof that you
> understand WHY Lambda Architecture exists, not just how to build it.

---

## Executive Summary

> Fill in after running the pipeline. Example structure:

After running the event simulator for [X hours] at [Y events/second] with
[Z%] late-arrival injection, the real-time (speed) layer achieved [A%] session
accuracy compared to the ground-truth batch layer. The [B%] restatement rate
and [$C] revenue discrepancy demonstrate the concrete cost of trading latency
for approximate correctness.

---

## Experiment Configuration

| Parameter | Value |
|-----------|-------|
| Simulation duration | ___ hours |
| Event rate | ___ events/second |
| Late arrival % | ___ % |
| Late arrival delay range | 2–15 minutes |
| Session timeout | 30 minutes |
| Dataset | REES46 2019-Oct (~20M events) |
| Date simulated | YYYY-MM-DD |

---

## Results

### Speed Layer vs Batch Layer

| Metric | Speed Layer (DynamoDB) | Batch Layer (Athena) | Delta |
|--------|----------------------|---------------------|-------|
| Total sessions | | | |
| Total revenue | | | |
| Conversion rate | | | |
| Avg session duration | | | |
| **Latency** | **< 30 seconds** | **~8 hours** | — |

### Restatement Analysis

| Metric | Value |
|--------|-------|
| Sessions requiring restatement | ___ (___ %) |
| Avg revenue discrepancy (restated sessions) | $___  |
| Max revenue discrepancy (single session) | $___ |
| Total revenue restated | $___ |
| Revenue error in speed layer | ___% |
| Events correctly placed in same session | ___% |

---

## Key Findings

### Finding 1: [e.g. "Most restatements were caused by short late arrivals"]

_Describe what the data showed. Be specific — include numbers._

### Finding 2: [e.g. "Conversion rate was overestimated in the speed layer"]

_Explain why this happened mechanically, not just that it happened._

### Finding 3: [e.g. "95% of sessions were accurate within 10% of batch revenue"]

_What does this mean for a business using this system?_

---

## Tradeoff Analysis

### When is the speed layer "good enough"?

The speed layer is sufficient when:
- **Use case:** _[e.g. live A/B test dashboards, real-time fraud signals]_
- **Acceptable error rate:** _[e.g. <5% session restatement]_
- **Revenue sensitivity:** _[e.g. <1% revenue discrepancy is acceptable for operational reporting]_

In our experiment: ___% of sessions were accurate without reconciliation,
meaning the speed layer would be sufficient for [use case].

### When is the batch layer essential?

The batch layer is required when:
- **Use case:** _[e.g. financial revenue reporting, billing, SLA calculations]_
- **Reason:** _[e.g. even a 1% revenue error on $1M/day = $10K/day in misreported revenue]_

In our experiment: ___% of sessions required restatement, representing
$___ in revenue that would have been incorrectly reported.

### What determines the restatement rate?

The key driver was the **late arrival injection rate** ([Z%] in this experiment).
The business implication: if [Z%] of mobile clients experience >5 minute network
delays, then at least [Z%] of sessions will be restated. In e-commerce:
- Mobile web: ~3–8% of events arrive late (weak connectivity, background sync)
- Native apps: ~1–3% (better connection handling)
- Point-of-sale: ~0% (direct server-side events)

---

## Architectural Recommendations

Based on these results, for a production e-commerce analytics system I would recommend:

1. **Keep the Lambda Architecture** because ___
2. **Tune the late-arrival window** to ___ minutes because ___
3. **Use the speed layer for** [list specific operational use cases]
4. **Use the batch layer for** [list specific reporting use cases]
5. **Consider** [one architectural improvement, e.g. Kafka + Flink instead of Kinesis + Lambda] **if** ___

---

## What I Would Do Differently at Scale

> This section shows you can think beyond the project.

| Current Approach | At 10x Scale | Reason |
|-----------------|-------------|--------|
| Kinesis on-demand | Apache Kafka (MSK) | More consumer groups, better replay |
| Lambda sessionizer | Apache Flink | Stateful streaming with exactly-once |
| DynamoDB | Apache Cassandra | Better write throughput at scale |
| EMR Serverless | Databricks | Better developer experience for Spark |
| Nightly batch | Hourly micro-batch | Reduces restatement window |

---

## Appendix: SQL Queries Used

Paste the Athena queries you ran to generate the numbers above.

```sql
-- Speed layer aggregate
[paste your query]

-- Batch layer aggregate  
[paste your query]

-- Restatement analysis
[paste your query]
```
