# Architecture

> **Status:** Design, partially built. Real today: the Postgres schema and migrations,
> settings and `ModelRouter` (unused), the sandbox, `POST /execute` and `POST /probe`, the
> test harness, the complexity probe, the **deterministic coding grader**, the
> **session layer** (`/api/v1` — plan, submit, grade, report) writing `artifacts`,
> `gradings` and `concept_evidence`, the **adaptive engine** (Elo, FSRS, the replayable
> `mastery` projection, and a planner that ranks by weakness priority), **auth** (GitHub
> OAuth and a signed session cookie every `/api/v1` route requires), the **model-call path**
> (`api.llm` — budget checked, call made, `llm_calls` row written) with `/costs` and
> `/costs/budget` over it, the **interviewer agent** (`POST /sessions/{id}/turns`, a system
> prompt per mode, three tools, turns persisted), the **SSE stream** (`GET
> /sessions/{id}/events`, with the interviewer's text streamed as it is generated), and a
> 24-item corpus, and **rubric grading** — so `design` and `behavioral` sessions grade as
> well as `coding` ones. Not built: quant's answer check, and two of the five agent tools.
> `docs/BUILDLOG.md` is authoritative.
> Related: [GLOSSARY](GLOSSARY.md) · [API](API.md) · [SECURITY](SECURITY.md) · [INFRA](INFRA.md) · [BUILDLOG](BUILDLOG.md) (what is actually built) · [PRACTICE_LOG](PRACTICE_LOG.md)

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
                                 Python 3.12 · C++20 [cpp not implemented]

  Vapi ──OpenAI-compatible /v1/chat/completions (SSE)──▶ same agent core   [phase 7]
```

## The three decisions that shape everything else

**1. The corpus is a build-time artifact.** Claude Code researches and authors it on
your machine; the result is versioned JSON in `packages/corpus/`. Nothing at runtime
invents a question. Consequences: sessions are reproducible, graders can be
deterministic, corpus changes are reviewable diffs, and the research cost lands on the
Max subscription rather than the API bill.

**2. Mastery is derived from immutable evidence.** Every graded artifact writes a
`concept_evidence` row and never mutates one. `mastery` is a projection that can be
recomputed from scratch. Consequences: the adaptive engine is auditable ("why did it
give me this?"), and the rating math can be replaced later without discarding history.

**3. The agent core is transport-agnostic.** The interviewer is a function over
(session state, corpus item, tools) → turn. HTTP+SSE is one adapter; Vapi's
OpenAI-compatible endpoint is another. Consequences: voice is a Phase 7 adapter rather
than a rewrite. Built as `api.agent.loop.run_turn`, which takes a database session, a
session row, an item and a string, and knows nothing about HTTP.

## Services

| Service | Responsibility | Trust |
|---|---|---|
| `apps/web` | UI only. Holds no secrets, talks only to the API. **Not built — an empty directory until Phase 5.** | Untrusted input |
| `apps/api` | Sessions, agent loop, grading, mastery, cost ledger, the live event stream, and the only door in — GitHub OAuth and the cookie it issues. The only service with DB and model credentials. **Stateful in one place:** the event bus is in-process memory, which is what makes running two tasks a Phase 6 decision rather than a config change. | Trusted |
| `apps/executor` | Runs candidate code. No network, no DB, no credentials. | **Hostile by assumption** |

The executor is a separate service specifically so that "runs untrusted code" and "holds
the database password" are never the same process.

### Where the sandbox actually lives

*Resolved 2026-08-20.*

Building the isolation layer raised a question the diagram above did not answer: launching
a sandbox container requires the Docker socket, and **the Docker socket is root-equivalent
control of the host** — whoever holds it can start a privileged container mounting `/`.
Giving that to the service whose job is running LLM-generated code would invert the whole
boundary.

The resolution turns on a fact about Phase 6, checked against AWS's documentation rather
than assumed: **Fargate cannot do this at all.** Host bind mounts (`sourcePath`) are
supported "only when using tasks that are hosted on Amazon EC2 instances or Amazon ECS
Managed Instances", `devices` is unsupported under Fargate, and every Fargate task "has its
own isolation boundary and does not share the underlying kernel". There is no socket to
mount and no sibling container to launch. **The docker-per-execution model is a local
development strategy that does not survive to production.**

That collapses the question rather than forcing a topology change:

| | Local (now) | Fargate (Phase 6) |
|---|---|---|
| What isolates | a throwaway `docker run` container | the Fargate task itself — own microVM, own kernel |
| Who launches it | the executor service, holding the Docker socket | ECS, from a task definition |
| Runs untrusted code in-process | never | yes — but the task *is* the boundary |

So the documented topology stands: `apps/executor` remains a service the API calls over
`EXECUTOR_URL`. Locally it is a **launcher** that holds the Docker socket and no other
credential and never evaluates candidate code in its own process; under Fargate it becomes
the sandbox itself and needs no socket. `executor.sandbox.run_sandboxed` is the seam where
that swap happens.

The residual local risk is honest and bounded: compromising the executor process yields
the Docker socket and therefore the host. It is accepted because the executor's attack
surface is one endpoint over FastAPI/uvicorn/Pydantic and nothing else, it holds no DB or
model credentials, and the exposure exists only on a single-user development machine —
never in the deployed system, which structurally cannot have it.

**An earlier draft of this note claimed the alternative "contradicts the documented service
diagram." That was wrong, and the error is worth keeping:** it came from reasoning about
the trust boundary in the abstract without checking what the target platform permits. The
platform constraint decided the design.

## Data model

**Built.** Every table below exists, applied by migrations `6e1d353bc543` (initial),
`1408f9143d32` (gradings record failures) and `137646f0d9a1` (timestamps carry their
timezone). `concepts`, `items`, `concept_edges` and `item_concepts` come from `make seed`;
`users`, `sessions`, `artifacts`, `gradings`, `concept_evidence` and `mastery` are written
by a real session; `turns` and `llm_calls` by the interviewer. `research_runs` and the
practice-log tables are still empty — nothing produces their rows yet.

Every timestamp column is `TIMESTAMP WITH TIME ZONE`. The naive default silently returns a
value with no offset, which raises on the first comparison against an aware `now()` and,
worse, would *not* raise inside Phase 4's date arithmetic.

| Table | Purpose |
|---|---|
| `users` | One row today. `github_id` is unique; a sentinel value holds the row until the first real login rewrites it in place, so evidence written before auth existed is not stranded. Schema is multi-tenant-shaped so it never needs a rewrite. |
| `concepts`, `concept_edges` | Seeded from the corpus; the DAG. |
| `items` | Seeded from the corpus; carries the live Elo rating, which drifts from the seed. |
| `item_concepts` | Join table for an item's full concept tuple. `items.primary_concept_id` covers the distinguished one; this covers all of them, including it. |
| `sessions` | One mock interview: mode, plan, status, timings. |
| `turns` | Every exchange, with the tool calls made. Written by the interviewer loop, and the record hints are counted from at grading time. |
| `artifacts` | Code submissions, diagrams, transcripts. |
| `gradings` | One row per graded artifact: `status`, a **nullable** score, detail, grader version. A grader that crashed or timed out is recorded as `failed` with no score — a CHECK keeps "failed but scored 0.0" from existing. |
| `concept_evidence` | **Immutable.** The source of truth for mastery. Written by graded sessions and, from Phase 9, by the practice log — `item_id`/`session_id` are nullable, and a `source` column plus `practice_problem_id` distinguish the two producers. |
| `mastery` | Derived projection: ability, observations, stability, due_at, last_seen, and the scheduler's own card. Rebuilt from `concept_evidence` by `POST /mastery/recompute`, never hand-edited. |
| `llm_calls` | Cost ledger: model, tokens in/out/cache, computed $, latency, session. Written by `api.llm` in its own transaction, so a caller that fails afterwards cannot erase the record of spend. |
| `research_runs` | Provenance for corpus builds. |
| `practice_problems`, `practice_solves` | Phase 9. External (LeetCode/Codeforces) problems logged manually, their classification against the corpus taxonomy, and their spaced re-solve schedule. See [PRACTICE_LOG](PRACTICE_LOG.md). |

pgvector **will be** used for semantic retrieval over corpus items and over your own past
mistakes — "show me things I got wrong that resemble this" is intended as a first-class
query. Today the Postgres image ships the extension and `pgvector` is a declared
dependency, but **no migration runs `CREATE EXTENSION`**, no table has an embedding
column, and nothing embeds anything. It lands with the code that needs it.

## Model routing

| Job | Model | `effort` | Why |
|---|---|---|---|
| Session planning | Opus 5 | `high` | Runs once per session; quality matters more than cost |
| Interviewing turns | Sonnet 5 | `medium` | The hot loop; near-Opus quality on dialogue at lower cost |
| Grading | Opus 5 | `high` | Directly determines mastery, so errors compound |
| Classification, extraction | Haiku 4.5 | `low` | Mechanical work |

**This table is the design; it is not what runs today.** Measured 2026-08-20, the AWS
account behind this project can reach `us.anthropic.claude-sonnet-4-6` and cannot reach any
Claude 5 model, so all four jobs are configured to Sonnet 4.6 until Bedrock model access is
granted. The substitution is configuration, not code —
[COST.md](COST.md#what-actually-runs-today) records the measurements and how to undo it.

All calls go through `ModelRouter`, so provider (Bedrock vs Anthropic direct) and model
choice are config, not call-site decisions. [PRACTICE_LOG](PRACTICE_LOG.md)'s problem
classification (Phase 9) uses the existing "Classification, extraction" row above — it
does not need a new job type.

Prompt construction is cache-shaped: `api.llm.cached_system` puts the frozen system prompt
in a block carrying the `cache_control` breakpoint, and everything volatile goes in
`messages`, after it. Automatic top-level caching is unavailable on Bedrock, so the
breakpoint is placed by hand. The assertion this section asked for — repeated
identical-prefix requests reporting a non-zero `cache_read_input_tokens` — is written, as
an `llm`-marked test run by `make test-llm` rather than in CI, which has no credentials.

## What is deliberately not here

- **No multi-tenancy.** Single user. The schema allows it later; the code does not
  implement it now. Since auth landed, session and mastery reads *are* filtered by the
  caller's user id — that is one `where` clause per query, not tenant isolation, and
  nothing enforces it structurally.
- **No runtime content generation.** See decision 1.
- **No LLM in the deterministic grading path.** Code correctness is decided by tests
  in a sandbox, not by a model's opinion of the code.
