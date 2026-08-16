# Build log

> **Status:** Current — this is the one document that always describes reality.
> If another doc and this one disagree about what exists, this one is right.

What has actually been built, phase by phase. `docs/ARCHITECTURE.md` describes the
design; this records what exists on disk and what the next phase picks up.

Rules for this file: record what was *verified*, not what was written. If something is
unverified, say so. If a gate was skipped, say that too.

---

## Phase 0 — Foundations · complete · 2026-08-15

Repo skeleton, build tooling, the concept taxonomy, and the corpus contract.

**Verified.** `make check` runs clean end to end:

```
ruff check          All checks passed
ruff format --check 12 files already formatted
mypy (strict)       no issues in 8 source files
pytest              21 passed
corpus validate     159 concepts · 0 items · 0 errors, 0 warnings
```

### What landed

| Area | State |
|---|---|
| Workspace | `uv` workspace (`apps/api`, `apps/executor`, `packages/corpus`) + pnpm slot for `apps/web` |
| Concept taxonomy | **159 concepts** across all four domains, DAG-validated |
| Corpus contract | `concept.schema.json`, `item.schema.json` — archetype/instance split, per-modality grading union |
| Corpus validator | 7 checks, each with a test proving it *catches* the failure, not just that it passes |
| API | health + `/corpus/status` only |
| Executor | health only — no execution path exists yet, by design |
| CI | GitHub Actions: lint, types, tests, corpus gate |

### Concept counts by domain

| Domain | Concepts |
|---|---|
| coding | 52 |
| quant | 51 |
| system_design | 37 |
| behavioral | 19 |

Bands: 22 foundational · 81 core · 56 advanced.

### Decisions worth keeping

- **The corpus is a build-time artifact.** `research/` (Claude Code, on the Max plan)
  writes it; nothing at runtime generates items. This is what makes sessions
  reproducible and graders deterministic, and it moves the research cost off the API
  bill entirely.
- **Statements are original prose; sources justify the *archetype*, not the text.**
  The validator enforces this with two shingle thresholds — any shared 12-word run is
  an error, and >15% containment of a source's 8-grams is an error. This is the rule
  that keeps proprietary problem statements out of the repo.
- **Mastery is derived, never stored as ground truth.** Every graded artifact will
  write an immutable `concept_evidence` row; `mastery` is recomputable from evidence
  alone. That keeps the adaptive engine auditable and lets the math change later
  without losing history.
- **Instances must point at an archetype.** Enforced by the validator. It prevents the
  corpus from drifting into a pile of one-off problems with no attested pattern behind
  them.
- **Sources must be independent**, measured by distinct registrable domain. Two pages
  on the same site are one source.

### Things found by running them

- `uv sync` built empty wheels for `api` and `executor` because their `src/` trees had
  no `.py` files at the time. The dist-info looked correct while imports failed. Fixed
  with a targeted `--reinstall-package`; worth remembering that a present dist-info is
  not evidence a workspace package is importable.
- Two test modules both named `test_health.py` collide under pytest's rootdir-less
  collection even in separate packages. Renamed to `test_api_health.py` /
  `test_executor_health.py`.
- Ruff's isort guessed `api` as first-party and `corpus` as third-party, so import
  order churned between `make fmt` runs. Pinned `known-first-party`.
- `starlette.testclient` warns that `httpx` support is deprecated in favour of
  `httpx2`. Not blocking; revisit when the test surface grows.

### Self-review findings

Reviewed the validator after committing, since a validator with a hole is worse than
none — it grants false confidence. Two real gaps, both fixed (`make check` green,
23 tests):

1. **Domain and modality were never checked against each other.** An item with
   `domain: "coding"` and `modality: "quant"` passed validation and would have been
   routed to a grader that cannot grade it. They are 1:1; now enforced as an error.
2. **Concept tags were never checked against the item's domain.** A coding item could
   tag `kelly-criterion` and silently write evidence to a quant concept — corrupting
   mastery in a way that is very hard to trace back. Now a *warning*, not an error,
   because it is occasionally legitimate (a quant-dev coding problem really can touch
   probability).

Also hardened `main()`: a stray argument that is not an existing directory now falls
back to the default corpus root instead of failing obscurely further down.

Verified the cycle detector by hand against the diamond and repeated-push cases, since
an iterative DFS with a stale-entry stack is exactly where a subtle false positive
would hide. A stale `(node, False)` entry popped while the node is GREY is a genuine
back edge, and popped while BLACK it is correctly skipped.

**Known and accepted for now:**
- `GET /corpus/status` reloads the whole corpus from disk per request. Fine at 159
  concepts and 0 items; needs a cached loader once the corpus is real. Phase 3.
- `starlette.testclient` warns that `httpx` support is deprecated in favour of
  `httpx2`. Not blocking; revisit when the test surface grows.
- The originality thresholds (12-gram, 15% containment) are untested against real
  research output — they are calibrated on intuition. Phase 1 will produce the first
  evidence about whether they are too strict or too loose.

### Deferred deliberately

- `infra/compose/docker-compose.yml` — Phase 6 opens with it, and writing it before
  there are services to compose would be guessing.
- Database schema and Alembic migrations — the tables are designed in
  `docs/ARCHITECTURE.md` but land with the code that uses them in Phase 3, so the
  first migration reflects something real.
- `apps/web` — Next.js scaffold lands in Phase 5.

---

## Documentation pass · 2026-08-16

Not a phase — a gap-filling round after auditing coverage against the eight phases.

**The problem measured.** Documentation was front-loaded and infra-heavy: 6,457 words,
but the phases with the most remaining work had the least. Coverage by phase was 0 ✅,
1 partial, 2 partial, **3 none**, 4 ✅, **5 none**, 6 ✅, **7 none**, **8 none**. Grepping
confirmed it — "state machine", "threat", "seccomp", "escape test", "Monaco", and
"restore" appeared nowhere, despite escape tests and a restore drill being stated gates.

Structurally, the docs were hub-and-spoke with no spokes touching: README had 9 outbound
links, and the eight docs had **one** link between them in total. Reading GRADING never
led to ADAPTIVE, even though evidence is what connects them.

**What was added.** Seven documents, each unblocking a phase that would otherwise have
been improvised:

| Doc | Unblocks |
|---|---|
| RESEARCH | Phase 1 — the pipeline that turns "no seed bank" into a corpus |
| SECURITY | Phase 2 — threat model and the five escape tests its gate depends on |
| API | Phase 3 — the contract the web app *and* the Vapi shim both build against |
| WEB | Phase 5 |
| VOICE | Phase 7 |
| OPERATIONS | Phase 8 — plus backup/rollback, which go live with Phase 6 |
| GLOSSARY | Vocabulary that was previously scattered across files |

Plus a structural pass: a status banner on every doc so built-vs-designed is visible at a
glance, cross-links between related docs, and a README documentation map with per-phase
status.

**Decisions recorded along the way** (fuller detail in each doc):

- Archetype ranking is by evidence density — a recency-weighted count of independent
  registrable domains — never by asking a model to score novelty or importance.
- The originality rule is a *process* constraint, not only a validator check: read
  sources to learn that a pattern is asked, then close them and write from the pattern.
- The security posture prioritises credential exposure over sandbox exotica, because a
  leaked Bedrock role against $10k of credits is the worst realistic outcome here.
- Prompt injection is handled by capability design rather than filtering — the agent has
  no tool that writes the corpus, sends anything outbound, or reads secrets.
- `abandoned` sessions write evidence for what was graded; `failed` sessions write none.
- Coding mode over voice grades the *explanation*, not the code, and writes evidence
  against communication concepts. Pretending otherwise would write misleading evidence.
- Only two tables are irreplaceable — `concept_evidence` and the session transcripts.
  Everything else is derived, in git, or in Terraform.

**Honest caveat.** These are specifications, not built systems. The odds that all of them
survive contact with implementation unchanged are low — the API surface and the adaptive
weights are the most likely to move. They are written to make Phases 1–8 executable
rather than improvised, and the buildlog remains the record of what is actually true.

### Next: Phase 1 — Corpus v1

Run the research pipeline per domain. Targets: ~400 archetypes, ~150 gradeable
instances. The gate is the validator plus a human spot-check — every archetype cites
two independent sources, every coding instance's reference solution passes its own
hidden tests, and the originality check is clean.

Open question to settle first: how many items per domain are worth authoring before
the runtime exists to use them. Leaning toward a thin vertical slice — ~15 instances
per modality — so Phase 2 and 3 have real content to grade against, then bulk
authoring after the loop is proven.
