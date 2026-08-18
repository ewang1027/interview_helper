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
| `docs/` | Design and specification — see the map below |

## Documentation

New here? Read [GLOSSARY](docs/GLOSSARY.md) → [ARCHITECTURE](docs/ARCHITECTURE.md) →
[BUILDLOG](docs/BUILDLOG.md). The glossary defines the vocabulary the others assume, and
the buildlog is the only document that always describes reality — **if any doc and the
buildlog disagree about what exists, the buildlog is right.**

| Doc | Covers | Phase | Status |
|---|---|---|---|
| [BUILDLOG](docs/BUILDLOG.md) | What is actually built, and what each wave cost to learn | all | Current |
| [GLOSSARY](docs/GLOSSARY.md) | Project vocabulary in one place | all | Current |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Services, trust boundaries, data model, model routing | all | Design |
| [CONCEPTS](docs/CONCEPTS.md) | The 159-concept taxonomy and its rules | 0 | ✅ Built |
| [CORPUS](docs/CORPUS.md) | What a corpus item is; the validator's seven checks | 0 → 1 | ✅ Contract built |
| [RESEARCH](docs/RESEARCH.md) | How items get researched and authored | 1 | Spec |
| [SECURITY](docs/SECURITY.md) | Threat model, sandbox isolation, the five escape tests | 2 | Spec |
| [GRADING](docs/GRADING.md) | The four graders and what they produce | 2 → 3 | Spec |
| [API](docs/API.md) | Endpoints, session state machine, SSE events, agent tools | 3 | Spec |
| [COST](docs/COST.md) | Model routing, hard budgets, the ledger | 3 → 6 | Policy set |
| [ADAPTIVE](docs/ADAPTIVE.md) | Elo + FSRS, evidence, weakness priority, planning | 4 | Spec |
| [WEB](docs/WEB.md) | Routes, the four mode workspaces, dashboard | 5 | Spec |
| [INFRA](docs/INFRA.md) | AWS from first principles — written to teach | 6 | Spec |
| [VOICE](docs/VOICE.md) | Vapi adapter, latency budget, what changes for speech | 7 | Spec |
| [OPERATIONS](docs/OPERATIONS.md) | Backups, deploys, alarms, runbook | 8 | Spec |
| [PRACTICE_LOG](docs/PRACTICE_LOG.md) | External problem tracker: LLM classification, spaced re-solve queue | 9 (needs 3+4) | Spec |

## Quick start

```sh
make setup      # install dependencies and the pre-push secret-scan hook
make dev        # bring up Postgres and run migrations
make seed       # load the corpus into the database
make dev-api    # run the API against it (uvicorn --reload)
make check      # ruff + mypy + pytest + corpus validate + secret scan
make test-db    # schema tests against the live Postgres
```

`make dev` currently brings up Postgres only — the `api`, `web` and `executor`
containers land in Phase 6, when they have Dockerfiles.

## Build status

**Phase 0 — foundations.** See [`docs/BUILDLOG.md`](docs/BUILDLOG.md) for what has actually
landed and what the next phase picks up.

- [ ] **0 — Foundations:** repo, schema, taxonomy, corpus contract, CI
- [ ] **1 — Corpus v1:** researched, evidence-ranked, original statements — *thin slice
      landed (2026-08-19): 12 items across coding and quant, verified; bulk authoring and
      the design/behavioral domains remain*
- [ ] **2 — Executor + deterministic grading** — *isolation layer landed and verified
      (2026-08-18); `POST /execute`, test harnesses and the complexity probe remain*
- [ ] **3 — Interview runtime (text) + API** — *DB schema, migrations, settings and
      model routing landed early (2026-08-16); sessions, grading, auth and budgets remain*
- [ ] **4 — Adaptive engine**
- [ ] **5 — Web app**
- [ ] **6 — AWS deploy**
- [ ] **7 — Voice via Vapi**
- [ ] **8 — Hardening**
- [ ] **9 — Practice log:** external problem tracking, classification, spaced re-solve queue
