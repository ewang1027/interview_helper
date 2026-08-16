# Architecture

> **Status:** Design. The service boundaries are real; almost none of the code is —
> only health endpoints and the corpus loader exist today (**Phase 0**).
> Related: [GLOSSARY](GLOSSARY.md) · [API](API.md) · [SECURITY](SECURITY.md) · [INFRA](INFRA.md) · [BUILDLOG](BUILDLOG.md) (what is actually built)

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
than a rewrite.

## Services

| Service | Responsibility | Trust |
|---|---|---|
| `apps/web` | UI only. Holds no secrets, talks only to the API. | Untrusted input |
| `apps/api` | Sessions, agent loop, grading, mastery, cost ledger. The only service with DB and model credentials. | Trusted |
| `apps/executor` | Runs candidate code. No network, no DB, no credentials. | **Hostile by assumption** |

The executor is a separate service specifically so that "runs untrusted code" and "holds
the database password" are never the same process.

## Data model (lands in Phase 3)

| Table | Purpose |
|---|---|
| `users` | One row today. Schema is multi-tenant-shaped so it never needs a rewrite. |
| `concepts`, `concept_edges` | Seeded from the corpus; the DAG. |
| `items` | Seeded from the corpus; carries the live Elo rating, which drifts from the seed. |
| `sessions` | One mock interview: mode, plan, status, timings. |
| `turns` | Every exchange, with the tool calls made. The grading input. |
| `artifacts` | Code submissions, diagrams, transcripts. |
| `gradings` | One row per graded artifact: score, per-criterion detail, grader version. |
| `concept_evidence` | **Immutable.** The source of truth for mastery. |
| `mastery` | Derived projection: ability, stability, due_at, last_seen. |
| `llm_calls` | Cost ledger: model, tokens in/out/cache, computed $, latency, session. |
| `research_runs` | Provenance for corpus builds. |

pgvector is used for semantic retrieval over corpus items and over your own past
mistakes — "show me things I got wrong that resemble this" is a first-class query.

## Model routing

| Job | Model | Why |
|---|---|---|
| Session planning | Opus 5 | Runs once per session; quality matters more than cost |
| Interviewing turns | Sonnet 5 | The hot loop; near-Opus quality on dialogue at lower cost |
| Grading | Opus 5 | Directly determines mastery, so errors compound |
| Classification, extraction | Haiku 4.5 | Mechanical work |

All calls go through `ModelRouter`, so provider (Bedrock vs Anthropic direct) and model
choice are config, not call-site decisions.

Prompt construction is cache-shaped: the frozen per-mode system prompt and the item
context sit above the `cache_control` breakpoint, volatile turn content below. A CI
assertion checks that repeated identical-prefix requests report a non-zero
`cache_read_input_tokens`, because silent cache invalidation is expensive and invisible.

## What is deliberately not here

- **No multi-tenancy.** Single user. The schema allows it later; the code does not
  implement it now.
- **No runtime content generation.** See decision 1.
- **No LLM in the deterministic grading path.** Code correctness is decided by tests
  in a sandbox, not by a model's opinion of the code.
