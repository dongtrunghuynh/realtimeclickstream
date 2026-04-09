# Real-Time Clickstream Pipeline — Streaming Analytics

A production-grade **Lambda Architecture** pipeline built on AWS. Ingests e-commerce
clickstream events in real-time via Kinesis + Lambda, batch-reconciles sessions nightly
with Spark on EMR Serverless, and quantifies the accuracy/latency tradeoff between the
speed and batch layers.

---

## Architecture

```
[Python Event Simulator (REES46 dataset)]
        │  configurable replay rate + intentional late arrivals
        ▼
[Kinesis Data Streams — on-demand]
        │
        ├──► [Lambda — Sessionizer]
        │          30-min inactivity window
        │          Running cart totals
        │          ▼
        │    [DynamoDB — Speed Layer]    ←── Sub-minute latency reads
        │
        └──► [S3 — Raw Events (Parquet)]
                    │
             [EMR Serverless — Spark]
                  Nightly reconciliation
                  Late-arrival stitching
                    │
             [S3 — Corrected Sessions]  ←── Batch Layer
                    │
             [Athena — Comparison Views]
                    │
        [Accuracy/Latency Dashboard]
```

## Stack

| Layer | Service |
|-------|---------|
| Ingestion | Amazon Kinesis Data Streams (on-demand) |
| Speed processing | AWS Lambda (Python 3.12) |
| Speed serving | Amazon DynamoDB (on-demand) |
| Batch processing | EMR Serverless (Spark 3.5) |
| Batch storage | Amazon S3 + Apache Parquet |
| Batch query | Amazon Athena (Iceberg) |
| Infrastructure | Terraform (modules + dev/prod workspaces) |

## Quick Start

```bash
# Prerequisites: AWS CLI configured, Terraform ≥ 1.7, Python ≥ 3.11, Java 11

git clone <repo>
cd realtimeclickstream
pip install -r requirements.txt

cd terraform
terraform init
terraform workspace new dev
terraform apply -var-file=environments/dev.tfvars

cd ..
python src/event_simulator/simulator.py --rate 100 --duration 300
```

See [`docs/setup-guide.md`](docs/setup-guide.md) for the full walkthrough.

## Key Deliverables

1. **Event Simulator** — Replays REES46 dataset into Kinesis with configurable rate + late arrivals
2. **Lambda Sessionizer** — 30-min inactivity window, cart totals, DynamoDB writes
3. **Spark Batch Reconciler** — Nightly session stitching + late-arrival restatements
4. **Athena Views** — Side-by-side speed vs batch comparison
5. **Accuracy Dashboard** — Quantified latency/accuracy tradeoff (the ⭐ standout piece)

## Estimated Cost

| Resource | Cost |
|----------|------|
| Kinesis on-demand | ~$0.08/hr when active |
| Lambda | Free tier (1M requests/month) |
| EMR Serverless | Pennies per Spark job |
| DynamoDB | Free tier (<1KB writes) |
| **Total** | **~$5–12/month** |

> **Always run `terraform destroy` in dev workspace at end of day.**

## Project Structure

See [`docs/architecture.md`](docs/architecture.md) for full detail.

## License

MIT
