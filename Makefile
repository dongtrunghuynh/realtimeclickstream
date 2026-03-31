# Makefile
# ─────────────────────────────────────────────────────────────────────────────
# All development, testing, and deployment tasks.
#
# Usage:  make <target>  [ENV=dev|staging|prod]
#         make help
# ─────────────────────────────────────────────────────────────────────────────

ENV      ?= dev
TF_DIR   := infra
SRC_DIR  := src/stream_processor
BUILD    := .build
ZIP      := $(BUILD)/lambda.zip

BOLD  := \033[1m
GREEN := \033[32m
CYAN  := \033[36m
RESET := \033[0m

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo ""
	@echo "  $(BOLD)Clickstream Analytics Pipeline$(RESET)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS=":.*?## "}; {printf "  $(CYAN)%-22s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "  ENV=$(ENV)  (override with ENV=staging|prod)"
	@echo ""

# ── Python setup ──────────────────────────────────────────────────────────────

.PHONY: install
install:  ## Install all Python dev dependencies
	pip install --upgrade pip
	pip install -e ".[dev]"

# ── Code quality ──────────────────────────────────────────────────────────────

.PHONY: lint
lint:  ## Run ruff linter
	ruff check $(SRC_DIR) tests/ --output-format=full

.PHONY: format
format:  ## Auto-format code with ruff
	ruff format $(SRC_DIR) tests/
	ruff check $(SRC_DIR) tests/ --fix

.PHONY: typecheck
typecheck:  ## Run mypy strict type checking
	mypy $(SRC_DIR) --ignore-missing-imports --strict

.PHONY: check
check: lint typecheck  ## Run all static analysis (no tests)

# ── Tests ─────────────────────────────────────────────────────────────────────

.PHONY: test
test:  ## Run unit tests with coverage report
	pytest tests/unit/ \
		--cov=$(SRC_DIR) \
		--cov-report=term-missing \
		--cov-report=xml:coverage.xml \
		--cov-fail-under=90

.PHONY: test-watch
test-watch:  ## Re-run tests on file change (requires pytest-watch)
	@command -v ptw >/dev/null 2>&1 || pip install pytest-watch
	ptw tests/unit/ --runner "pytest --tb=short"

# ── Lambda build ──────────────────────────────────────────────────────────────

.PHONY: build
build: check test  ## Lint + test + package Lambda zip
	@echo "$(GREEN)▶ Building Lambda package…$(RESET)"
	@rm -rf $(BUILD) && mkdir -p $(BUILD)/pkg
	pip install -r $(SRC_DIR)/requirements.txt \
		--target $(BUILD)/pkg --quiet
	@cp -r $(SRC_DIR)/* $(BUILD)/pkg/
	@cd $(BUILD)/pkg && zip -r ../lambda.zip . \
		-x "*.pyc" -x "*/__pycache__/*" -x "*.dist-info/*"
	@echo "$(GREEN)✔ $(ZIP)  ($$(du -sh $(ZIP) | cut -f1))$(RESET)"

# ── Terraform ─────────────────────────────────────────────────────────────────

.PHONY: tf-init
tf-init:  ## terraform init for ENV
	cd $(TF_DIR) && terraform init -reconfigure \
		-backend-config="key=$(ENV)/terraform.tfstate"

.PHONY: tf-validate
tf-validate:  ## terraform validate
	cd $(TF_DIR) && terraform validate

.PHONY: tf-fmt
tf-fmt:  ## terraform fmt (recursive)
	terraform fmt -recursive $(TF_DIR)

.PHONY: tf-fmt-check
tf-fmt-check:  ## terraform fmt check (CI mode)
	terraform fmt -recursive -check $(TF_DIR)

.PHONY: tf-plan
tf-plan:  ## terraform plan for ENV
	@echo "$(GREEN)▶ Planning [$(ENV)]…$(RESET)"
	cd $(TF_DIR) && terraform plan \
		-var-file=environments/$(ENV).tfvars \
		-var="lambda_zip_path=../$(ZIP)" \
		-out=.tfplan-$(ENV)

.PHONY: tf-apply
tf-apply:  ## apply saved plan for ENV
	cd $(TF_DIR) && terraform apply .tfplan-$(ENV)

.PHONY: tf-destroy
tf-destroy:  ## DANGER: destroy all ENV resources
	@echo "$(BOLD)⚠ Destroying [$(ENV)] — Ctrl-C to abort$(RESET)"
	@sleep 3
	cd $(TF_DIR) && terraform destroy \
		-var-file=environments/$(ENV).tfvars \
		-var="lambda_zip_path=../$(ZIP)"

# ── Combined workflows ────────────────────────────────────────────────────────

.PHONY: ci
ci: lint typecheck tf-fmt-check tf-validate test  ## Full CI check (no AWS needed)
	@echo "$(GREEN)✔ All CI checks passed$(RESET)"

.PHONY: deploy-dev
deploy-dev: ENV=dev
deploy-dev: build tf-init tf-plan tf-apply  ## Build + deploy to dev
	@echo "$(GREEN)✔ Deployed to dev$(RESET)"

.PHONY: clean
clean:  ## Remove build artefacts
	@rm -rf $(BUILD) .pytest_cache coverage.xml .coverage htmlcov
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "$(GREEN)✔ Clean$(RESET)"
