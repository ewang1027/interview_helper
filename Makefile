.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE := docker compose -f infra/compose/docker-compose.yml

.PHONY: help setup dev dev-api dev-web down check check-web lint typecheck test fmt \
        corpus-validate seed test-sandbox test-e2e test-db cost-report secret-scan \
        doc-links doc-check hygiene verify-solutions login test-llm build-web \
        backup restore clean

help: ## Show this help
	@# [a-zA-Z0-9_-] not [a-z-]: the narrower class silently dropped `test-e2e`
	@# from this listing because of the digit, so a documented target was invisible.
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python deps and the pre-push hooks (secret scan, docs-with-code)
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

dev-web: ## Run the web app against the API (next dev, proxies /api and /auth to API_ORIGIN)
	cd apps/web && pnpm dev

build-web: ## Production build of the web app
	cd apps/web && pnpm build

down: ## Tear down the local stack
	$(COMPOSE) down

check: lint typecheck test corpus-validate doc-links doc-check check-web secret-scan hygiene ## Everything CI runs, then a commit-hygiene report

check-web: ## Web app: eslint, tsc and the component tests
	@# Skipped with a message rather than failing when dependencies are not
	@# installed: `make check` is the gate a Python-only change runs, and making
	@# it depend on a pnpm install nobody asked for would be a gate people learn
	@# to skip. CI installs them, so CI always runs it.
	@if [ -d apps/web/node_modules ]; then \
	  cd apps/web && pnpm lint && pnpm typecheck && pnpm test; \
	else \
	  echo "skipping web checks: apps/web/node_modules absent (run make setup)"; \
	fi

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

doc-check: ## Verify the docs agree with each other: status headers, the index, the phase tables
	@uv run python scripts/check_docs.py

hygiene: ## Report uncommitted and unpushed work (informational — never fails)
	@bash scripts/commit_hygiene.sh

secret-scan: ## Grep tracked files for common secret shapes (repo is public)
	@bash scripts/secret_scan.sh

verify-solutions: ## Run every coding item's reference solution against its own tests, in the sandbox
	uv run python scripts/verify_reference_solutions.py --strict-stub-check --complexity

login: ## Mint a session cookie for the local user (needs SESSION_SECRET and the database)
	@uv run python -m api.mint_session

seed: ## Load the corpus into the database
	uv run python -m api.seed

test-sandbox: ## Every test that needs real Docker: escape suite, /execute, /probe, grading
	@# Not scoped to apps/executor: the coding grader's end-to-end tests live in
	@# apps/api and need the same real daemon, and a path-scoped target would have
	@# skipped them silently — which is the failure mode this repo keeps finding.
	uv run pytest -q -m sandbox

test-e2e: ## One scripted coding session against a live stack — needs Postgres AND Docker
	uv run pytest -q -m e2e

test-db: ## DB-backed tests against a live Postgres (make dev first)
	@# Seeded first, because `items` is a projection of the corpus and the planner reads it.
	@# Twice now, authoring corpus items and then running this produced a wall of failures
	@# whose only cause was a stale table -- 47 of them the first time, and nothing in the
	@# output said so. CI already seeds before this step; this brings local into line.
	uv run python -m api.seed
	uv run pytest apps/api/tests -q -m db

test-llm: ## The only tests that call a real model — costs money, needs credentials and Postgres
	uv run pytest -q -m llm -rs

cost-report: ## Per-session token and dollar spend from the llm_calls ledger
	uv run python -m api.cost_report

backup: ## Dump the local database to backups/ (gzipped pg_dump)
	@bash scripts/backup_db.sh dump

restore: ## Restore the database from a dump: make restore FILE=backups/... CONFIRM=1
	@CONFIRM=$(CONFIRM) bash scripts/backup_db.sh restore "$(FILE)"

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
