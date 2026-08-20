.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE := docker compose -f infra/compose/docker-compose.yml

.PHONY: help setup dev dev-api down check lint typecheck test fmt \
        corpus-validate seed test-sandbox test-e2e test-db cost-report secret-scan \
        doc-links verify-solutions clean

help: ## Show this help
	@# [a-zA-Z0-9_-] not [a-z-]: the narrower class silently dropped `test-e2e`
	@# from this listing because of the digit, so a documented target was invisible.
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python deps and the pre-push secret-scan hook
	uv sync --all-packages
	@# apps/web is an empty Phase 5 placeholder with no package.json, so an unguarded
	@# `pnpm install` exits 1 and aborts setup BEFORE the hook is installed — meaning a
	@# fresh clone silently ends up with no pre-push secret scan on a public repo.
	@if [ -f apps/web/package.json ]; then \
	  cd apps/web && pnpm install; \
	else \
	  echo "skipping pnpm: apps/web has no package.json yet (Phase 5)"; \
	fi
	git config core.hooksPath hooks

dev: ## Bring up Postgres (api/web/executor containers land in Phase 6 — see infra/compose/docker-compose.yml)
	$(COMPOSE) up -d
	uv run alembic -c apps/api/alembic.ini upgrade head

dev-api: ## Run the API against the compose Postgres (uvicorn --reload)
	uv run uvicorn api.main:app --reload --app-dir apps/api/src

down: ## Tear down the local stack
	$(COMPOSE) down

check: lint typecheck test corpus-validate doc-links secret-scan ## Everything CI runs

lint: ## Ruff (ESLint joins in Phase 5, with apps/web)
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

doc-links: ## Verify every internal doc link resolves — file and heading anchor
	@uv run python scripts/check_doc_links.py

secret-scan: ## Grep tracked files for common secret shapes (repo is public)
	@bash scripts/secret_scan.sh

verify-solutions: ## Run every coding item's reference solution against its own tests, in the sandbox
	uv run python scripts/verify_reference_solutions.py --strict-stub-check --complexity

seed: ## Load the corpus into the database
	uv run python -m api.seed

test-sandbox: ## Executor escape tests — all must fail closed
	uv run pytest apps/executor/tests -q -m sandbox

test-e2e: ## One scripted session per mode against a live stack — NO e2e tests exist yet (Phase 3)
	uv run pytest apps/api/tests -q -m e2e

test-db: ## DB-backed tests against a live Postgres (make dev first)
	uv run pytest apps/api/tests -q -m db

cost-report: ## Per-session token and dollar spend from the llm_calls ledger
	uv run python -m api.cost_report

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
