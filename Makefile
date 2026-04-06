# =============================================================================
# Makefile — Common project commands
# Run 'make help' to see all targets
# =============================================================================

.DEFAULT_GOAL := help
SHELL         := /bin/bash
ENV           ?= dev
DATE          ?= $(shell date -d yesterday +%Y-%m-%d 2>/dev/null || date -v -1d +%Y-%m-%d)
RATE          ?= 100
DURATION      ?= 300
LATE_PCT      ?= 0.05

# Colours
BOLD  := \033[1m
RESET := \033[0m
GREEN := \033[32m
BLUE  := \033[34m

# ─── Help ───────────────────────────────────────────────────────────────────

.PHONY: help
help:
	@echo ""
	@echo "$(BOLD)Clickstream Pipeline — Available Commands$(RESET)"
	@echo ""
	@echo "$(BOLD)$(BLUE)Setup$(RESET)"
	@echo "  make setup              One-time setup (state bucket, TF workspaces, deps)"
	@echo "  make install            Install Python dependencies"
	@echo ""
	@echo "$(BOLD)$(BLUE)Infrastructure$(RESET)"
	@echo "  make tf-init            terraform init"
	@echo "  make tf-plan            terraform plan (dev)"
	@echo "  make tf-apply           terraform apply (dev)"
	@echo "  make tf-destroy         terraform destroy dev (COST = \$$0)"
	@echo "  make tf-outputs         Print all terraform outputs"
	@echo ""
	@echo "$(BOLD)$(BLUE)Lambda$(RESET)"
	@echo "  make build-lambda       Package Lambda zip for deployment"
	@echo "  make deploy-lambda      Build + apply Lambda only"
	@echo "  make lambda-logs        Tail Lambda CloudWatch logs (live)"
	@echo ""
	@echo "$(BOLD)$(BLUE)Simulator$(RESET)"
	@echo "  make simulate           Run simulator (RATE=100 DURATION=300 LATE_PCT=0.05)"
	@echo "  make simulate-fast      Quick 60s test run at 200 events/s"
	@echo "  make simulate-day       Full 1hr run to generate a day of data"
	@echo ""
	@echo "$(BOLD)$(BLUE)Batch Jobs$(RESET)"
	@echo "  make spark-run          Submit Spark batch reconciler (DATE=yesterday)"
	@echo "  make spark-run DATE=2024-10-15   Run for specific date"
	@echo ""
	@echo "$(BOLD)$(BLUE)Athena$(RESET)"
	@echo "  make athena-setup       Create all Glue tables and Athena views"
	@echo "  make snapshot-dynamodb  Export DynamoDB sessions to S3 for Athena"
	@echo ""
	@echo "$(BOLD)$(BLUE)Dashboard$(RESET)"
	@echo "  make dashboard          Run accuracy/latency comparison dashboard"
	@echo "  make dashboard DATE=2024-10-15 --csv  Save results to CSV"
	@echo ""
	@echo "$(BOLD)$(BLUE)Testing & Quality$(RESET)"
	@echo "  make test               Run unit tests"
	@echo "  make test-cov           Run tests with coverage report"
	@echo "  make lint               Ruff lint check"
	@echo "  make lint-fix           Ruff lint + auto-fix"
	@echo "  make tf-validate        Validate Terraform config"
	@echo "  make check              lint + tf-validate + test (run before every PR)"
	@echo ""
	@echo "$(BOLD)$(BLUE)Utilities$(RESET)"
	@echo "  make clean              Remove build artefacts"
	@echo "  make cost-check         Verify no surprise AWS resources are running"
	@echo ""

# ─── Setup ──────────────────────────────────────────────────────────────────

.PHONY: setup
setup:
	@echo "$(GREEN)Running one-time setup...$(RESET)"
	bash scripts/setup.sh

.PHONY: install
install:
	pip install -r requirements.txt
	@echo "$(GREEN)Dependencies installed$(RESET)"

# ─── Infrastructure ─────────────────────────────────────────────────────────

.PHONY: tf-init
tf-init:
	cd terraform && terraform init

.PHONY: tf-plan
tf-plan:
	cd terraform && terraform workspace select $(ENV) && \
	    terraform plan -var-file=environments/$(ENV).tfvars

.PHONY: tf-apply
tf-apply:
	cd terraform && terraform workspace select $(ENV) && \
	    terraform apply -var-file=environments/$(ENV).tfvars

.PHONY: tf-destroy
tf-destroy:
	@echo "$(BOLD)Destroying $(ENV) environment — cost = \$$0$(RESET)"
	bash scripts/teardown_dev.sh

.PHONY: tf-outputs
tf-outputs:
	cd terraform && terraform workspace select $(ENV) && terraform output

# ─── Lambda ─────────────────────────────────────────────────────────────────

.PHONY: build-lambda
build-lambda:
	bash scripts/build_lambda.sh

.PHONY: deploy-lambda
deploy-lambda: build-lambda
	cd terraform && terraform workspace select $(ENV) && \
	    terraform apply -var-file=environments/$(ENV).tfvars \
	    -target=module.lambda

.PHONY: lambda-logs
lambda-logs:
	aws logs tail /aws/lambda/clickstream-sessionizer-$(ENV) --follow

# ─── Simulator ──────────────────────────────────────────────────────────────

.PHONY: simulate
simulate:
	python src/event_simulator/simulator.py \
	    --rate $(RATE) \
	    --duration $(DURATION) \
	    --late-arrival-pct $(LATE_PCT)

.PHONY: simulate-fast
simulate-fast:
	python src/event_simulator/simulator.py \
	    --rate 200 \
	    --duration 60 \
	    --late-arrival-pct 0.05

.PHONY: simulate-day
simulate-day:
	@echo "$(GREEN)Running full 1hr simulation at 200/s with 8%% late arrivals$(RESET)"
	python src/event_simulator/simulator.py \
	    --rate 200 \
	    --duration 3600 \
	    --late-arrival-pct 0.08

# ─── Spark ──────────────────────────────────────────────────────────────────

.PHONY: spark-run
spark-run:
	bash scripts/submit_spark_job.sh session_stitcher $(DATE)

.PHONY: spark-run-late
spark-run-late:
	bash scripts/submit_spark_job.sh late_arrival_handler $(DATE)

# ─── Athena ─────────────────────────────────────────────────────────────────

.PHONY: athena-setup
athena-setup:
	bash scripts/athena_setup.sh

.PHONY: snapshot-dynamodb
snapshot-dynamodb:
	bash scripts/export_dynamodb_snapshot.sh

# ─── Dashboard ──────────────────────────────────────────────────────────────

.PHONY: dashboard
dashboard:
	python src/dashboard/accuracy_latency_dashboard.py --date $(DATE)

.PHONY: dashboard-csv
dashboard-csv:
	python src/dashboard/accuracy_latency_dashboard.py \
	    --date $(DATE) \
	    --output dashboard_$(DATE).csv

# ─── Tests & Quality ────────────────────────────────────────────────────────

.PHONY: test
test:
	pytest tests/unit/ -v

.PHONY: test-cov
test-cov:
	pytest tests/unit/ -v \
	    --cov=src \
	    --cov-report=term-missing \
	    --cov-report=html:htmlcov \
	    --cov-fail-under=70
	@echo "$(GREEN)Coverage report: htmlcov/index.html$(RESET)"

.PHONY: test-integration
test-integration:
	pytest tests/integration/ -v -m integration

.PHONY: lint
lint:
	ruff check src/ tests/

.PHONY: lint-fix
lint-fix:
	ruff check --fix src/ tests/
	ruff format src/ tests/

.PHONY: tf-validate
tf-validate:
	cd terraform && terraform validate && terraform fmt -check -recursive

.PHONY: check
check: lint tf-validate test
	@echo "$(GREEN)All checks passed — safe to push$(RESET)"

# ─── Utilities ──────────────────────────────────────────────────────────────

.PHONY: clean
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf htmlcov/ .coverage coverage.xml
	rm -rf src/lambda/_build src/lambda/sessionizer.zip
	@echo "$(GREEN)Clean$(RESET)"

.PHONY: cost-check
cost-check:
	@echo "Checking for running AWS resources..."
	@echo "Kinesis streams:"
	@aws kinesis list-streams --query 'StreamNames' --output table
	@echo "Lambda functions:"
	@aws lambda list-functions --query 'Functions[?starts_with(FunctionName, `clickstream`)].FunctionName' --output table
	@echo "DynamoDB tables:"
	@aws dynamodb list-tables --query 'TableNames[?starts_with(@, `clickstream`)]' --output table
	@echo "EMR Serverless applications:"
	@aws emr-serverless list-applications --query 'applications[].{Name:name,State:state}' --output table
	@echo ""
	@echo "If everything shows empty above, cost = \$$0"

# ─── Pipeline ────────────────────────────────────────────────────────────────

.PHONY: run-pipeline
run-pipeline:
	bash scripts/run_full_pipeline.sh

.PHONY: run-pipeline-quick
run-pipeline-quick:
	bash scripts/run_full_pipeline.sh --quick

# ─── Local Dashboard ─────────────────────────────────────────────────────────

.PHONY: dashboard-sample
dashboard-sample:
	@echo "Rendering sample dashboard (no AWS needed)..."
	python src/dashboard/local_report.py --sample --date $(DATE)

.PHONY: report
report:
	python src/dashboard/local_report.py \
	    --speed-csv  speed_$(DATE).csv \
	    --batch-csv  batch_$(DATE).csv \
	    --audit-csv  audit_$(DATE).csv \
	    --date $(DATE)

# ─── DLQ ────────────────────────────────────────────────────────────────────

.PHONY: dlq-list
dlq-list:
	python src/lambda/sessionizer/dlq_handler.py --list

.PHONY: dlq-reprocess-dry
dlq-reprocess-dry:
	python src/lambda/sessionizer/dlq_handler.py --reprocess --dry-run

.PHONY: dlq-reprocess
dlq-reprocess:
	python src/lambda/sessionizer/dlq_handler.py --reprocess
