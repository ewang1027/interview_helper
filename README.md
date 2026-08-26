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
within ten sessions — five until the corpus grew a foundational concept gating six others,
which the priority formula correctly establishes first (see [ADAPTIVE](docs/ADAPTIVE.md)).

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
| `apps/api/` | FastAPI — `/health` and `/auth/*` at the root, and behind a session cookie under `/api/v1` the **session layer** (plan → submit → grade → report), mastery, costs and `corpus/status`. The deterministic coding grader, GitHub OAuth, the model-call path, the **interviewer agent** and the **SSE stream** live here too |
| `apps/web/` | Next.js 15 app — dashboard, session creation with its plan preview, the live interview and its four workspaces, the report, concepts, history, corpus, costs, the practice log, and the **job-application tracker** |
| `apps/executor/` | Sandboxed code runner (no network, non-root, resource-capped) — isolation, `POST /execute` and `POST /probe` (the complexity probe) are built |
| `packages/corpus/` | Versioned question corpus + JSON Schema + validator (48 items today) |
| `research/` | *Empty placeholder.* Corpus ingestion pipeline, Phase 1 — the 48 items were hand-authored, not pipeline-produced |
| `scripts/` | The gates: secret scan, doc links, doc consistency, reference-solution verification — all four run in CI — plus the local push and hygiene checks |
| `hooks/` | `pre-push`: secret scan and the docs-with-code check, installed by `make setup` |
| `infra/compose/` | The whole stack — Postgres, api, executor, web and a Caddy front door. `make up-stack` |
| `infra/ecs/` | Step 2's scaffolding: the API task definition, and what exists in the account |
| `infra/terraform/` | *Empty placeholder.* AWS: VPC, ALB, ECS Fargate, RDS, observability — Phase 6 step 3 |
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
| [CORPUS](docs/CORPUS.md) | What a corpus item is, and what the validator does and does not catch | 0 → 1 | ✅ Contract built |
| [RESEARCH](docs/RESEARCH.md) | How items get researched and authored | 1 | Spec |
| [SECURITY](docs/SECURITY.md) | Threat model, sandbox isolation, the six escape tests, the answer parser | 2 | ✅ Isolation built |
| [GRADING](docs/GRADING.md) | The four graders and what they produce | 2 → 3 | ✅ All four graders built |
| [API](docs/API.md) | Endpoints, session state machine, SSE events, agent tools | 3 | ✅ Sessions, agent, SSE, auth and all five tools built |
| [COST](docs/COST.md) | Model routing, hard budgets, the ledger | 3 → 6 | Policy set |
| [ADAPTIVE](docs/ADAPTIVE.md) | Elo + FSRS, evidence, weakness priority, planning | 4 | ✅ Built |
| [WEB](docs/WEB.md) | Routes, the four mode workspaces, dashboard | 5 | ✅ All nine routes built |
| [INFRA](docs/INFRA.md) | AWS from first principles — written to teach | 6 | ✅ Compose stack built · AWS is spec |
| [VOICE](docs/VOICE.md) | Vapi adapter, latency budget, what changes for speech | 7 | Spec |
| [OPERATIONS](docs/OPERATIONS.md) | Backups, deploys, alarms, runbook | 8 | ✅ Local backup built · rest is spec |
| [PRACTICE_LOG](docs/PRACTICE_LOG.md) | External problem tracker: LLM classification, spaced re-solve queue | 9 (needs 3+4) | ✅ Built |
| [JOBS](docs/JOBS.md) | Application tracker: paste-import, the stage funnel, LLM tagging and the web-search research pass | 10 (needs 3) | ✅ API + page built |

## Quick start

```sh
make setup      # install dependencies and the pre-push gates (secret scan, docs-with-code)
make dev        # bring up Postgres and run migrations
make seed       # load the corpus into the database
make dev-api    # run the API against it (uvicorn --reload)
make login      # mint a session cookie — every /api/v1 route needs one
make dev-web    # run the web app (proxies /api and /auth to the API — one origin)
make up-stack   # the whole thing in containers on :3000 — the supported deployment
make down-stack # stop it (the database volume survives)
make check      # ruff + mypy + pytest + corpus validate + doc gates + web checks, then hygiene
make check-web  # just the web app: eslint, tsc, component tests
make coverage   # Python coverage — needs Postgres, or the figure drops ~26 points
make test-db    # seeds the corpus, then the schema and session tests against live Postgres

make test-sandbox     # every test needing real Docker: escapes, /execute, /probe, grading
make test-e2e         # one scripted coding session — needs Postgres AND Docker
make test-llm         # the only tests that call a real model — costs money, needs credentials
make verify-solutions # every reference solution through the same harness candidates get
make backup           # dump the local database to backups/ (nothing else backs it up)
make restore FILE=... CONFIRM=1   # replace the database with a dump
make down             # tear down the local stack — data survives; `down -v` does not
```

`make dev` brings up Postgres only, which is what the local `uvicorn`/`next` workflow
wants. `make up-stack` runs everything in containers instead — that is the *supported
deployment*, not a dev convenience, and the portability gate in [INFRA](docs/INFRA.md)
runs exactly it on a second machine. The web app talks to the API
through a same-origin proxy rather than to `localhost:8000`, because the session cookie is
`SameSite=Lax` and the API mounts no CORS — see [WEB](docs/WEB.md#one-origin-and-why).

Set `SESSION_SECRET` in `.env` before the API is useful: without one, every `/api/v1`
route answers `503` naming it rather than running open. `make login` then prints a cookie
for `curl`; a browser logs in through GitHub, which additionally needs an OAuth app and
`GITHUB_ALLOWED_ID` — see [`.env.example`](.env.example) and [API](docs/API.md#auth).

Without an OAuth app the web app still opens: `/login` reports what is unset and how to
mint a cookie by hand. With one, set `GITHUB_REDIRECT_URI` to the **web app's** origin
(`http://localhost:3000/auth/callback`) and give the OAuth app the same callback — a
cookie set on the API's port is cross-site to the browser and will not come back
([WEB](docs/WEB.md#one-origin-and-why)).

## Build status

**Phases 0, 2 and 3 complete for what they were scoped to; 4, 9 and 10 built; 1
partially landed, 6 begun**, deliberately out of order — each was taken far enough to unblock the
next. See
[`docs/BUILDLOG.md`](docs/BUILDLOG.md) for what actually exists and what each phase still
owes.

- [x] **0 — Foundations:** repo, schema, taxonomy, corpus contract, CI
- [ ] **1 — Corpus v1:** researched, evidence-ranked, original statements — *thin slice
      landed (2026-08-20, widened twice on 2026-08-21): 48 items — 4 archetypes and 8
      instances in every one of the four domains. The fourth archetype in each measures a
      concept that was a *prerequisite* of one already served, so the planner's
      prerequisite gate can now turn away from a concept it could have served in all four
      modes rather than only in quant. Coding references are verified in a real sandbox and
      quant answers twice over; design and behavioral rubrics have no such check, and say
      so. Bulk authoring toward ~400/~150 remains*
- [x] **2 — Executor + deterministic grading** — *isolation, `POST /execute`,
      `POST /probe` and the scoring grader landed and verified (2026-08-20). A quadratic
      submission that passes every one of an item's tests is caught by the probe and
      scores 0.75; `cpp` and `peak_rss_kb` remain, both deferred rather than owed*
- [x] **3 — Interview runtime (text) + API** — *DB schema, migrations, settings and
      model routing landed early (2026-08-16); the **session layer** landed 2026-08-20 —
      `/api/v1`, plan → submit → grade → report, writing real `concept_evidence`, verified
      end to end against a live stack. **Auth landed 2026-08-20**: GitHub OAuth, a signed
      session cookie, and no route under `/api/v1` reachable without one. **The model-call
      path landed 2026-08-20**: budget enforced, ledger written, `/costs` live, and the
      first real Bedrock calls of the project's history made — which found that the model
      ids shipped since Phase 3 were never callable. **The interviewer agent landed
      2026-08-20**: a system prompt per mode, a turn loop with three tools, and `turns`
      finally getting rows, narrating itself on **the SSE stream** — also landed
      2026-08-20, carrying the interviewer's text as the model generates it. **Rubric
      grading landed 2026-08-20** too, and **the quant grader 2026-08-21** — a symbolic
      answer check behind a parser wall, plus the derivation judged against the item's
      reasoning rubric — so all four modes can now be created and graded, and the
      interviewer's **last two tools landed** the same day: `check_answer`, and
      `record_observation`, which makes the conversation itself a third producer of
      evidence. Still owed: a full session against a live provider, which is gated on
      Bedrock access rather than on code*
- [x] **4 — Adaptive engine** — *Elo, FSRS, the replayable projection, the weakness
      priority and the planner landed 2026-08-20, verified against both gates in
      [ADAPTIVE](docs/ADAPTIVE.md). Weights are placeholders until real sessions calibrate
      them*
- [ ] **5 — Web app** — *every route landed 2026-08-24: Next.js 15 behind a
      same-origin proxy (the session cookie is `SameSite=Lax` and the API mounts no CORS,
      so cross-origin was never going to work), a typed client over all 25 endpoints, and
      the SSE reducer that treats `agent.message.done` as authoritative and reports a
      `seq` jump the server is structurally unable to see. The dashboard's heatmap covers
      the whole 159-concept taxonomy; `/session/new` shows the plan before you commit to
      it; the live view carries the transcript, the interviewer's tool calls and each
      hint's cost, with a workspace per mode. Gated by `make check-web` and a CI job —
      eslint, tsc, 26 component tests, production build. **Nothing has been opened in a
      browser yet**, so the visual layer is unreviewed; the Playwright gate is owed, and
      so is a live session against a real interviewer*
- [ ] **6 — AWS deploy** — *step 1 of the ramp landed 2026-08-25: Dockerfiles for
      `api`, `executor` and `web`, and `make up-stack` runs the whole application in
      containers behind a **Caddy front door** that routes by path — the job the ALB does
      in the target diagram, so compose mirrors the deployed topology instead of
      approximating it. Only the front door publishes a port; the API and executor are
      reachable only on the compose network. The sandbox was re-verified from inside the
      containerised launcher — no egress, no socket, no writes outside `/scratch`. **Steps
      2–5 need an authenticated AWS session**, not more code: `aws sts get-caller-identity`
      reports the session expired*
- [ ] **7 — Voice via Vapi**
- [ ] **8 — Hardening**
- [x] **9 — Practice log** — *external problem tracking, classification behind a
      confidence gate, and the spaced re-solve queue, landed 2026-08-21. A logged solve
      writes real `concept_evidence` and moves the same mastery a graded submission does.
      The classifier is uncalibrated — no gold set, and no real model has run it*
- [x] **10 — Job applications** — *the tracker landed 2026-08-25: two tables, a stage
      **event log** with the board derived from it, ten endpoints and a `/jobs` page. A
      pasted list is parsed and tagged by one structured Sonnet 5 call; above ten rows a
      second Opus 5 pass **searches the web** for the postings and fills in what the list
      left out. The funnel counts `furthest_stage`, so a rejection after an onsite still
      counts as an onsite reached. Web search is billed per search and does not appear in
      any token count, so the ledger grew a column for it. **Run live 2026-08-26**: a
      messy five-row paste parsed correctly for $0.0092, and the research pass made six
      real web searches for $0.2266 — which found that structured outputs reject the JSON
      Schema range keywords, a defect two older features shared and neither had ever hit.
      An import is now 3 SQL statements rather than 240. The page has still not been opened
      in a browser, like every other route here*
