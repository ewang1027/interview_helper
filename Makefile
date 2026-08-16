.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE := docker compose -f infra/compose/docker-compose.yml

.PHONY: help setup dev down check lint typecheck test fmt \
        corpus-validate research-check research-rank spot-check \
        seed test-sandbox test-e2e cost-report clean

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python (uv) and Node (pnpm) dependencies
	uv sync --all-packages
	cd apps/web && pnpm install

dev: ## Bring up the full stack locally (Postgres, API, web, executor)
	$(COMPOSE) up --build

down: ## Tear down the local stack
	$(COMPOSE) down

check: lint typecheck test corpus-validate research-check ## Everything CI runs

lint: ## Ruff + ESLint
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Auto-format
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## mypy
	uv run mypy apps/api/src apps/executor/src packages/corpus/src research/src

test: ## pytest
	uv run pytest -q

corpus-validate: ## Validate the corpus against its schema, provenance and originality rules
	uv run python -m corpus.validate

research-check: ## Verify every cited source traces back to a recorded research run
	uv run python -m research.runlog

research-rank: ## Rank archetypes by evidence density
	uv run python -m research.density

spot-check: ## Print 10 seeded-random instances for a human read (the Phase 1 gate)
	uv run python -m research.spotcheck --n 10 --seed 1

seed: ## Load the corpus into the database
	uv run python -m api.seed

test-sandbox: ## Executor escape tests — all must fail closed
	uv run pytest apps/executor/tests -q -m sandbox

test-e2e: ## One scripted session per interview mode against a live stack
	uv run pytest apps/api/tests -q -m e2e

cost-report: ## Per-session token and dollar spend from the llm_calls ledger
	uv run python -m api.cost_report

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
