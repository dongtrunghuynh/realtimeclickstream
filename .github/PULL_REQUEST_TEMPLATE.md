## Summary

<!-- 1–3 sentences: what does this PR do and why? -->

## Type of Change

- [ ] `feat` — New feature (event simulator, Lambda handler, Spark job, Terraform module)
- [ ] `fix` — Bug fix
- [ ] `refactor` — No behaviour change, structural improvement
- [ ] `infra` — Terraform / infrastructure change
- [ ] `test` — New or updated tests
- [ ] `docs` — Documentation only
- [ ] `chore` — Dependencies, scripts, tooling

## Component(s) Affected

- [ ] Event Simulator (`src/event_simulator/`)
- [ ] Lambda Sessionizer (`src/lambda/sessionizer/`)
- [ ] Spark Batch Reconciler (`src/spark/`)
- [ ] DynamoDB shared client (`src/lambda/shared/`)
- [ ] Accuracy/Latency Dashboard (`src/dashboard/`)
- [ ] Athena views (`athena/`)
- [ ] Terraform — Kinesis module
- [ ] Terraform — Lambda module
- [ ] Terraform — DynamoDB module
- [ ] Terraform — EMR Serverless module
- [ ] Terraform — S3/Athena module

## What Changed and Why

<!--
Explain the design decision, not just what code changed.
Examples:
- "Used ApproximateArrivalTimestamp instead of event_time because event_time
   can be None for late-arriving events injected by the simulator."
- "Switched to DynamoDB conditional writes to make Lambda idempotent under
   Kinesis at-least-once delivery."
-->

## Testing

- [ ] Unit tests pass locally: `pytest tests/unit/ -v`
- [ ] New tests added for new behaviour
- [ ] Terraform validates: `terraform validate && terraform fmt -check` (if .tf changed)
- [ ] Manually tested against Kinesis in dev workspace (if Lambda/simulator changed)
- [ ] EMR Serverless Spark job ran successfully in dev (if Spark changed)

## Data Engineering Checklist

- [ ] No hardcoded stream/table/bucket names — using env vars or config
- [ ] Late-arriving events handled correctly (using arrival time, not event time, for windowing)
- [ ] DynamoDB writes are idempotent (conditional expression or update, not blind put)
- [ ] S3 output is partitioned by `year/month/day/hour`
- [ ] Kinesis shard limits respected (1MB/s write per shard)
- [ ] IAM roles follow least-privilege principle
- [ ] No credentials or `.env` files committed

## Cost Impact

<!-- Any change that adds a new AWS resource or increases usage -->
- [ ] New AWS resource added — estimated cost: ___
- [ ] No cost impact

## Screenshots / Evidence

<!-- Attach CloudWatch metric screenshot, Athena query result, or DynamoDB item if relevant -->

## Reviewer Notes

<!-- Anything you want the reviewer to pay special attention to -->

---
*Read [`SKILL.md`](../../SKILL.md) for PR review conventions and comment labelling standards.*
