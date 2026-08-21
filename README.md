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
  (apps/web) [phase 5]  (apps/api)     mastery · evidence · sessions
                          │  │           · llm_calls cost ledger
                          │  └──▶ Bedrock (Claude) via ModelRouter   [phase 3]
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

**Built (Phase 4).** A graded session writes evidence, updates `mastery` in the same
transaction, and the next session is planned from it: concepts ranked by weakness
priority, then the item whose expected score lands closest to the band where an outcome
teaches you something. The whole projection — item ratings included — rebuilds from
evidence alone, and a simulated candidate with an injected weakness is being drilled on it
within five sessions.

Every graded artifact writes an immutable `concept_evidence` row — that part runs today.
Mastery is *derived* from that evidence, never hand-written, so it can be recomputed from
scratch at any time:

- **`ability`** — an Elo rating per concept, updated against each item's own difficulty
  rating, and scaled by how much the evidence is trusted. Answers *how hard should the
  next question be*.
- **`stability` / `due_at`** — FSRS, from the `fsrs` package with interval fuzzing turned
  off, because a jittered schedule cannot be rebuilt from its evidence. Answers *when
  should I see this again*.

The session planner draws from a weakness priority combining low ability, recent error
rate, overdue review, prerequisite blocking and anti-repetition — and every plan shows the
breakdown, because adaptation you cannot inspect is adaptation you cannot trust.

## Layout

| Path | What it is |
|---|---|
| `apps/api/` | FastAPI — `/health` and `/auth/*` at the root, and behind a session cookie under `/api/v1` the **session layer** (plan → submit → grade → report), mastery, costs and `corpus/status`. The deterministic coding grader, GitHub OAuth and the model-call path live here too; the interviewer agent and its SSE stream do not |
| `apps/web/` | *Empty placeholder.* Next.js 15 app, Phase 5 |
| `apps/executor/` | Sandboxed code runner (no network, non-root, resource-capped) — isolation, `POST /execute` and `POST /probe` (the complexity probe) are built |
| `packages/corpus/` | Versioned question corpus + JSON Schema + validator (24 items today) |
| `research/` | *Empty placeholder.* Corpus ingestion pipeline, Phase 1 — the 24 items were hand-authored, not pipeline-produced |
| `scripts/` | The gates: secret scan, doc links, doc consistency, reference-solution verification — all four run in CI — plus the local push and hygiene checks |
| `hooks/` | `pre-push`: secret scan and the docs-with-code check, installed by `make setup` |
| `infra/compose/` | Local Postgres today; the rest of the stack lands in Phase 6 with the Dockerfiles |
| `infra/terraform/` | *Empty placeholder.* AWS: VPC, ALB, ECS Fargate, RDS, observability — Phase 6 |
| `docs/` | Design and specification — see the map below |
| `CLAUDE.md` | How to work here: docs travel with the code, commit and push at every checkpoint |

## Documentation

New here? Read [GLOSSARY](docs/GLOSSARY.md) → [ARCHITECTURE](docs/ARCHITECTURE.md) →
[BUILDLOG](docs/BUILDLOG.md). Changing anything? Read [CLAUDE.md](CLAUDE.md) first — it is
the working agreement between the code and these documents, and parts of it are gates. The glossary defines the vocabulary the others assume, and
the buildlog is the only document that always describes reality — **if any doc and the
buildlog disagree about what exists, the buildlog is right.**

| Doc | Covers | Phase | Status |
|---|---|---|---|
| [BUILDLOG](docs/BUILDLOG.md) | What is actually built, and what each wave cost to learn | all | Current |
| [GLOSSARY](docs/GLOSSARY.md) | Project vocabulary in one place | all | Current |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Services, trust boundaries, data model, model routing | all | Design, partly built |
| [CONCEPTS](docs/CONCEPTS.md) | The 159-concept taxonomy and its rules | 0 | ✅ Built |
| [CORPUS](docs/CORPUS.md) | What a corpus item is; the validator's eight checks | 0 → 1 | ✅ Contract built |
| [RESEARCH](docs/RESEARCH.md) | How items get researched and authored | 1 | Spec |
| [SECURITY](docs/SECURITY.md) | Threat model, sandbox isolation, the six escape tests | 2 | ✅ Isolation built |
| [GRADING](docs/GRADING.md) | The four graders and what they produce | 2 → 3 | ✅ Coding grader built; rubric graders are Phase 3 |
| [API](docs/API.md) | Endpoints, session state machine, SSE events, agent tools | 3 | ✅ Sessions built; agent, SSE and auth are spec |
| [COST](docs/COST.md) | Model routing, hard budgets, the ledger | 3 → 6 | Policy set |
| [ADAPTIVE](docs/ADAPTIVE.md) | Elo + FSRS, evidence, weakness priority, planning | 4 | ✅ Built |
| [WEB](docs/WEB.md) | Routes, the four mode workspaces, dashboard | 5 | Spec |
| [INFRA](docs/INFRA.md) | AWS from first principles — written to teach | 6 | Spec |
| [VOICE](docs/VOICE.md) | Vapi adapter, latency budget, what changes for speech | 7 | Spec |
| [OPERATIONS](docs/OPERATIONS.md) | Backups, deploys, alarms, runbook | 8 | Spec |
| [PRACTICE_LOG](docs/PRACTICE_LOG.md) | External problem tracker: LLM classification, spaced re-solve queue | 9 (needs 3+4) | Schema built; behaviour is spec |

## Quick start

```sh
make setup      # install dependencies and the pre-push gates (secret scan, docs-with-code)
make dev        # bring up Postgres and run migrations
make seed       # load the corpus into the database
make dev-api    # run the API against it (uvicorn --reload)
make login      # mint a session cookie — every /api/v1 route needs one
make check      # ruff + mypy + pytest + corpus validate + doc gates + secret scan, then hygiene
make test-db    # schema and session tests against the live Postgres

make test-sandbox     # every test needing real Docker: escapes, /execute, /probe, grading
make test-e2e         # one scripted coding session — needs Postgres AND Docker
make test-llm         # the only tests that call a real model — costs money, needs credentials
make verify-solutions # every reference solution through the same harness candidates get
make down             # tear down the local stack
```

`make dev` currently brings up Postgres only — the `api`, `web` and `executor`
containers land in Phase 6, when they have Dockerfiles.

Set `SESSION_SECRET` in `.env` before the API is useful: without one, every `/api/v1`
route answers `503` naming it rather than running open. `make login` then prints a cookie
for `curl`; a browser logs in through GitHub, which additionally needs an OAuth app and
`GITHUB_ALLOWED_ID` — see [`.env.example`](.env.example) and [API](docs/API.md#auth).

## Build status

**Phases 0 and 2 complete for what they were scoped to. Phases 1 and 3 partially
landed**, deliberately out of order — each was taken far enough to unblock the next. See [`docs/BUILDLOG.md`](docs/BUILDLOG.md)
for what actually exists and what each phase still owes.

- [x] **0 — Foundations:** repo, schema, taxonomy, corpus contract, CI
- [ ] **1 — Corpus v1:** researched, evidence-ranked, original statements — *thin slice
      landed (2026-08-20): 24 items, 3 archetypes + 3 instances in each of the four
      domains, verified; bulk authoring toward ~400/~150 remains*
- [x] **2 — Executor + deterministic grading** — *isolation, `POST /execute`,
      `POST /probe` and the scoring grader landed and verified (2026-08-20). A quadratic
      submission that passes every one of an item's tests is caught by the probe and
      scores 0.75; `cpp` and `peak_rss_kb` remain, both deferred rather than owed*
- [ ] **3 — Interview runtime (text) + API** — *DB schema, migrations, settings and
      model routing landed early (2026-08-16); the **session layer** landed 2026-08-20 —
      `/api/v1`, plan → submit → grade → report, writing real `concept_evidence`, verified
      end to end against a live stack. **Auth landed 2026-08-20**: GitHub OAuth, a signed
      session cookie, and no route under `/api/v1` reachable without one. **The model-call
      path landed 2026-08-20**: budget enforced, ledger written, `/costs` live, and the
      first real Bedrock calls of the project's history made — which found that the model
      ids shipped since Phase 3 were never callable. The interviewer agent, the SSE stream
      and rubric grading remain — nothing in the running system calls a model yet*
- [x] **4 — Adaptive engine** — *Elo, FSRS, the replayable projection, the weakness
      priority and the planner landed 2026-08-20, verified against both gates in
      [ADAPTIVE](docs/ADAPTIVE.md). Weights are placeholders until real sessions calibrate
      them*
- [ ] **5 — Web app**
- [ ] **6 — AWS deploy**
- [ ] **7 — Voice via Vapi**
- [ ] **8 — Hardening**
- [ ] **9 — Practice log:** external problem tracking, classification, spaced re-solve queue
