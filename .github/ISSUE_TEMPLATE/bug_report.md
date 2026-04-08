---
name: Bug Report
about: Something is broken — data loss, incorrect session counts, Lambda errors, Spark failures
title: "fix(COMPONENT): short description of the bug"
labels: ["bug", "needs-triage"]
assignees: []
---

## Component

<!-- Which part of the pipeline is broken? -->
- [ ] Event Simulator (`src/event_simulator/`)
- [ ] Kinesis producer / stream
- [ ] Lambda Sessionizer (`src/lambda/sessionizer/`)
- [ ] DynamoDB session state
- [ ] Spark Batch Reconciler (`src/spark/`)
- [ ] Athena views / queries
- [ ] Accuracy/Latency Dashboard
- [ ] Terraform infrastructure
- [ ] CI / GitHub Actions

---

## Bug Description

<!-- One clear sentence: what is wrong? -->

---

## Expected vs Actual Behaviour

**Expected:**
<!-- What should happen? -->

**Actual:**
<!-- What is actually happening? -->

---

## Steps to Reproduce

```bash
# Exact commands to reproduce the issue
```

1.
2.
3.

---

## Evidence

<!-- Paste relevant logs, error messages, CloudWatch excerpts, Athena query results -->

```
[paste logs here]
```

**CloudWatch log group** (if applicable):
```
/aws/lambda/clickstream-sessionizer-dev
/aws/emr-serverless/clickstream-reconciler-dev
```

---

## Environment

| Field | Value |
|-------|-------|
| AWS Region | us-east-1 |
| Terraform workspace | dev / prod |
| Python version | |
| Terraform version | |
| Dataset date range | |
| Simulator rate at time of bug | |

---

## Data Impact

<!-- Is any data lost or incorrect? -->
- [ ] Session data lost (not written to DynamoDB)
- [ ] Revenue figures incorrect in speed layer
- [ ] Revenue figures incorrect in batch layer
- [ ] Late arrivals not reconciled by Spark
- [ ] No data impact — infrastructure/tooling issue only

---

## Possible Cause

<!-- Optional: your hypothesis on what's wrong -->

---

## Related

<!-- Link to related PRs, issues, or Athena queries -->
- Related to #
