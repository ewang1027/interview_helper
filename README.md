# interview_helper

An adaptive mock-interview trainer for SWE and quant-trading loops. It runs realistic
interviews across four surfaces — **coding**, **quant math**, **system design**, and
**behavioral** — grades each one per concept, and uses that graded history to decide what
to drill next. Text-driven today; voice via Vapi later.

Single user, self-hosted. Runs in containers anywhere, and deploys to AWS on ECS Fargate.

## Architecture

```
                        ┌──────────────────────────────────┐
   Claude Code          │  research/  (build time, Max plan)│
   (your machine)  ────▶│  web research → evidence-ranked   │
                        │  archetypes → authored items      │
                        └───────────────┬───────────────────┘
                                        │ commits versioned JSON
                                        ▼
                        ┌──────────────────────────────────┐
                        │  packages/corpus/  (in-repo)      │
                        │  concepts · items · tests · rubrics│
                        └───────────────┬───────────────────┘
                                        │ seeded into
                                        ▼
  Next.js 15 ──SSE──▶  FastAPI  ──▶  Postgres (+pgvector)
  (apps/web)           (apps/api)      mastery · evidence · sessions
                          │  │           · llm_calls cost ledger
                          │  └──▶ Bedrock (Claude) via ModelRouter
                          │
                          └──▶ apps/executor  (sandboxed, no network)
                                 Python 3.12 · C++20

  Vapi ──OpenAI-compatible /v1/chat/completions (SSE)──▶ same agent core   [phase 7]
```

The shape that matters: **the question corpus is a build-time artifact, not a runtime
generation**. Claude Code researches and authors it on your machine and commits versioned
JSON. That makes sessions reproducible, graders deterministic, and the research free —
while live sessions run on Bedrock, funded by AWS credits.

## How it adapts

Every graded artifact writes an immutable `concept_evidence` row. Mastery is *derived*
from that evidence, never hand-written, so it can be recomputed from scratch at any time:

- **`ability`** — an Elo rating per concept, updated against each item's own difficulty
  rating. Answers *how hard should the next question be*.
- **`stability` / `due_at`** — FSRS. Answers *when should I see this again*.

The session planner draws from a weakness priority combining low ability, recent error
rate, overdue review, and prerequisite blocking.

## Layout

| Path | What it is |
|---|---|
| `apps/api/` | FastAPI — sessions, interviewer agent, grading, mastery |
| `apps/web/` | Next.js 15 app |
| `apps/executor/` | Sandboxed code runner (no network, non-root, resource-capped) |
| `packages/corpus/` | Versioned question corpus + JSON Schema + validator |
| `research/` | Claude Code-driven corpus ingestion pipeline (build time) |
| `infra/compose/` | Portable deployment — runs the stack on any machine |
| `infra/terraform/` | AWS: VPC, ALB, ECS Fargate, RDS, observability |
| `docs/` | [ARCHITECTURE](docs/ARCHITECTURE.md) · [CONCEPTS](docs/CONCEPTS.md) · [CORPUS](docs/CORPUS.md) · [GRADING](docs/GRADING.md) · [ADAPTIVE](docs/ADAPTIVE.md) · [COST](docs/COST.md) · [INFRA](docs/INFRA.md) · [BUILDLOG](docs/BUILDLOG.md) |

## Quick start

```sh
make setup      # install Python (uv) and Node (pnpm) dependencies
make dev        # bring up Postgres, API, and web locally
make check      # ruff + mypy + pytest + eslint + tsc
make seed       # load the corpus into the database
```

## Build status

**Phase 0 — foundations.** See [`docs/BUILDLOG.md`](docs/BUILDLOG.md) for what has actually
landed and what the next phase picks up.

- [ ] **0 — Foundations:** repo, schema, taxonomy, corpus contract, CI
- [ ] **1 — Corpus v1:** researched, evidence-ranked, original statements
- [ ] **2 — Executor + deterministic grading**
- [ ] **3 — Interview runtime (text) + API**
- [ ] **4 — Adaptive engine**
- [ ] **5 — Web app**
- [ ] **6 — AWS deploy**
- [ ] **7 — Voice via Vapi**
- [ ] **8 — Hardening**
