# Changelog

All notable changes to this project are documented here.
Format: [Semantic Versioning](https://semver.org/)

---

## [Unreleased]

### Week 5 — Dashboard & Analysis (TODO)
- [ ] Accuracy/latency tradeoff dashboard (src/dashboard/)
- [ ] DynamoDB snapshot export script
- [ ] Athena comparison views
- [ ] docs/tradeoffs.md — quantitative analysis

### Week 4 — Spark Batch Reconciler (TODO)
- [ ] session_stitcher.py — nightly re-sessionization
- [ ] late_arrival_handler.py — restatement audit
- [ ] Athena table DDL registered
- [ ] Spark job submission script tested

### Week 3 — Lambda Sessionizer (TODO)
- [ ] Lambda handler deployed and processing Kinesis events
- [ ] Session state persisted to DynamoDB
- [ ] Cart totals accumulating correctly
- [ ] Late arrivals routed to S3 only
- [ ] Integration tests passing

### Week 2 — Event Simulator (TODO)
- [ ] CSV reader for REES46 dataset
- [ ] Kinesis producer with batching
- [ ] Late arrival injector
- [ ] CloudWatch metrics
- [ ] Unit tests passing

---

## [0.1.0] — Project Setup

### Added
- Project structure scaffolded (all directories, __init__ files)
- CLAUDE.md — AI context file for the project
- SKILL.md — Git/PR/code-review workflow guide
- README.md — Project overview
- docs/setup-guide.md — Complete setup instructions
- docs/architecture.md — Architecture deep dive
- docs/step-by-step.md — Week-by-week task guide
- docs/tradeoffs.md — Template for interview deliverable
- Terraform modules: Kinesis, DynamoDB, Lambda, EMR Serverless, S3+Athena
- Terraform environments: dev.tfvars, prod.tfvars
- GitHub: PR template, CODEOWNERS, CI workflow, deploy workflow, nightly teardown
- GitHub Issue templates: bug report, feature request
- Athena: table DDL (create_tables.sql), views (realtime, batch, comparison)
- Source stubs: event_simulator, Lambda sessionizer, Spark session_stitcher
- Test suites: unit tests for all components, integration test framework
- Scripts: setup.sh, build_lambda.sh, submit_spark_job.sh, teardown_dev.sh
- Scripts: athena_setup.sh, export_dynamodb_snapshot.sh
- Makefile with all common commands
- requirements.txt, requirements-dev.txt, pyproject.toml, ruff.toml, pytest.ini
