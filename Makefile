.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE := docker compose -f infra/compose/docker-compose.yml

.PHONY: help setup dev dev-api down check lint typecheck test fmt \
        corpus-validate seed test-sandbox test-e2e test-db cost-report secret-scan \
        verify-solutions clean

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python (uv) and Node (pnpm) dependencies
	uv sync --all-packages
	cd apps/web && pnpm install
	git config core.hooksPath hooks

dev: ## Bring up Postgres (api/web/executor containers land in Phase 6 — see infra/compose/docker-compose.yml)
	$(COMPOSE) up -d
	uv run alembic -c apps/api/alembic.ini upgrade head

dev-api: ## Run the API against the compose Postgres (uvicorn --reload)
	uv run uvicorn api.main:app --reload --app-dir apps/api/src

down: ## Tear down the local stack
	$(COMPOSE) down

check: lint typecheck test corpus-validate secret-scan ## Everything CI runs

lint: ## Ruff + ESLint
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Auto-format
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## mypy
	uv run mypy apps/api/src apps/executor/src packages/corpus/src

test: ## pytest
	uv run pytest -q

corpus-validate: ## Validate the corpus against its schema, provenance and originality rules
	uv run python -m corpus.validate

secret-scan: ## Grep tracked files for common secret shapes (repo is public)
	@bash scripts/secret_scan.sh

verify-solutions: ## Run every coding item's reference solution against its own tests, in the sandbox
	uv run python scripts/verify_reference_solutions.py --strict-stub-check

seed: ## Load the corpus into the database
	uv run python -m api.seed

test-sandbox: ## Executor escape tests — all must fail closed
	uv run pytest apps/executor/tests -q -m sandbox

test-e2e: ## One scripted session per interview mode against a live stack
	uv run pytest apps/api/tests -q -m e2e

test-db: ## DB-backed tests against a live Postgres (make dev first)
	uv run pytest apps/api/tests -q -m db

cost-report: ## Per-session token and dollar spend from the llm_calls ledger
	uv run python -m api.cost_report

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
