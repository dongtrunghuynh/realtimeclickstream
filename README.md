# 🖱️ Real-Time Clickstream Pipeline — Streaming Analytics

> **Difficulty:** Intermediate &nbsp;|&nbsp; **Estimated Cost:** $0 (all open source) &nbsp;|&nbsp; **Timeline:** 4–5 weeks part-time &nbsp;|&nbsp; **Architecture Pattern:** Streaming + Lambda Architecture

---

## Overview

Build a real-time clickstream analytics pipeline that captures simulated user browsing events, streams them through **Apache Kafka**, processes them with **Apache Flink** (or Spark Structured Streaming) for sessionization, and serves both a **real-time dashboard** (sub-minute latency) and a **batch-reconciled historical view**.

This project forces the team to think about event ordering, late-arriving data, and the tradeoffs between speed and correctness — the core challenges in any streaming system.

---

## Dataset

**[REES46 E-Commerce Behaviour Dataset](https://www.kaggle.com/) (~20M events)**

Contains `view`, `add-to-cart`, and `purchase` events with:
- Timestamps & session IDs
- Product metadata
- Category hierarchy

> Your team will write a Python event generator that replays these events into Kafka at configurable throughput.

---

## Tech Stack

| Tool | Role |
|------|------|
| **Apache Kafka** (+ KRaft) | Event ingestion and streaming backbone |
| **Apache Flink** (or Spark Structured Streaming) | Real-time sessionization, tumbling windows, watermarks for late data |
| **Apache Spark** (standalone) | Batch re-processing for historical accuracy and session stitching |
| **Redis** | Low-latency serving layer for real-time session state |
| **MinIO + Trino** | Batch query layer for historical analysis |
| **Ansible** (or Docker Compose) | Infrastructure as code — reproducible, reviewable service definitions |

---

## Key Deliverables

1. **Python Event Simulator** — Replays the REES46 dataset into Kafka with configurable event rates, including intentional late-arriving and out-of-order events.

2. **Flink / Spark Streaming Jobs** — Perform sessionization (30-minute inactivity window), compute running cart totals using stateful processing, and write session state to Redis.

3. **Batch Spark Job** — Reconciles sessions nightly, handles late arrivals, and writes corrected session data back to MinIO as Parquet.

4. **Trino Views** — Compare real-time (Redis) vs. batch-reconciled (MinIO/Parquet) metrics to demonstrate the accuracy/latency tradeoff.

5. **Complete Docker Compose Stack** — With Ansible playbooks for configuration; a single `docker compose down -v` tears everything down cleanly.

---

## ⭐ Standout Move — Accuracy/Latency Tradeoff Dashboard

After running the pipeline for a simulated day, query both the real-time Redis path and the batch-reconciled Trino path, and present a **side-by-side comparison**:

- How many sessions did the real-time path get wrong?
- What was the average revenue discrepancy?
- What percentage of late-arriving events caused restatements?

This kind of rigorous quantitative analysis demonstrates you understand **why** Lambda Architecture exists — not just how to build it.

---

## Infrastructure

| Service | RAM |
|---------|-----|
| Kafka (KRaft mode, single broker) | ~512 MB |
| Flink JobManager + TaskManager | ~1.5 GB |
| Redis | ~256 MB |
| Spark standalone | ~1 GB |
| **Total** | **~3.5 GB** |

> All services use official Docker images with no licensing costs.

---

## Skills Unlocked

- Kafka producer/consumer patterns
- Flink/Spark Streaming stateful processing
- Sessionization
- Redis caching and serving
- Trino federated queries
- Ansible configuration management
- Lambda Architecture tradeoffs

---

## Getting Started

```bash
# Clone the repo
git clone https://github.com/dongtrunghuynh/realtimeclickstream
cd realtimeclickstream

# Start all services
docker compose up -d

# Tear everything down (including volumes)
docker compose down -v
```

---

## Project Structure

```
realtimeclickstream/
├── simulator/          # Python event generator
├── flink-jobs/         # Sessionization & streaming jobs
├── spark-jobs/         # Batch reconciliation jobs
├── trino-views/        # SQL views for accuracy/latency comparison
├── infra/              # Docker Compose + Ansible playbooks
└── dashboard/          # Accuracy/latency tradeoff visualization
```
