# Build log

> **Status:** Current — this is the one document that always describes reality.
> If another doc and this one disagree about what exists, this one is right.

What has actually been built, phase by phase. `docs/ARCHITECTURE.md` describes the
design; this records what exists on disk and what the next phase picks up.

Rules for this file: record what was *verified*, not what was written. If something is
unverified, say so. If a gate was skipped, say that too.

## Where things stand — 2026-08-20

Entries below are **chronological, not in phase order**. Work has deliberately jumped
between phases, taking each only as far as needed to unblock the next — Phase 3's
persistence layer landed before Phase 1 had any content, because the practice-log spec
needed a real schema to be more than prose. Read this table first; the entries are the
detail behind it.

| Phase | State | What exists | What it still owes |
|---|---|---|---|
| **0** Foundations | **complete** | workspace, 159-concept taxonomy, corpus schema + validator, CI | — |
| **1** Corpus v1 | **partial** — thin slice | 24 items — 3 archetypes + 3 instances in each of four domains, verified | bulk authoring toward ~400/~150 |
| **2** Executor + grading | **complete** — the deterministic half it was scoped to | sandbox isolation (6 escape tests), `POST /execute`, `POST /probe`, complexity probe, reference-solution verification, **the coding grader** — score + evidence rows | `cpp`, `peak_rss_kb` — deferred, not owed |
| **3** Runtime + API | **partial** — half built | schema + migrations, settings, `ModelRouter`, the **session layer** (`/api/v1`, plan → submit → grade → report, writing `artifacts`, `gradings`, `concept_evidence`), and **auth** — GitHub OAuth, a signed session cookie, every `/api/v1` route behind it | interviewer agent, SSE stream, rubric graders, budget middleware |
| **4** Adaptive engine | **built** | Elo, FSRS, the replayable projection, the weakness priority, and a planner that drills a simulated injected weakness within five sessions | weights are placeholders until real sessions calibrate them |
| **5–8** Web, AWS, voice, hardening | **not started** | — | — |
| **9** Practice log | **partial** — schema only | `practice_problems`, `practice_solves`, and `concept_evidence`'s two-producer shape — all migrated, landed with the Phase 3 slice | classification, endpoints, scheduling. No longer gated on the engine: `apply_evidence` already handles an evidence row with no item, so a logged solve would feed mastery today. It is gated on a **model call**, which nothing in this project has ever made |

One thing worth knowing before reading anything else as further along than it is:
**no model call has ever been made.** `ModelRouter` resolves config and builds a client,
nothing calls it, and the token budgets in `.env.example` are read into settings but
enforced nowhere. Everything downstream of a model — the interviewer agent, rubric
grading, the SSE stream, the cost ledger, the practice log — is waiting on that one thing.

The auth gate this file carried since the session layer landed is **closed** as of
2026-08-20: every `/api/v1` route requires a signed session cookie, and the only way to
one is GitHub OAuth or `make login` with the server's own secret.

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

---

## Phase 3 (infra slice) — database, migrations, model routing · 2026-08-16

Taken **out of phase order deliberately.** Phases 1 and 2 (corpus authoring, executor)
are still unstarted; this landed the persistence and config layer they will both write
into, because the practice log spec (`docs/PRACTICE_LOG.md`, Phase 9) needed a real
schema to be more than prose. Sessions, the interviewer agent, grading, SSE and auth —
the rest of `docs/API.md` — are **not** built.

**Verified.** `make check` clean, plus DB-backed tests against real Postgres:

```
ruff check          All checks passed
ruff format --check 40 files already formatted
mypy (strict)       no issues in 15 source files
pytest              29 passed, 3 deselected
corpus validate     159 concepts · 0 items · 0 errors, 0 warnings
secret scan         clean
pytest -m db        3 passed        (live Postgres, after make dev)
alembic check       No new upgrade operations detected
```

Also verified by running, not by reading: `alembic downgrade base && upgrade head`
round-trips cleanly; `make seed` loads 159 concepts idempotently (run three times);
`uvicorn api.main:app` boots and serves `/health` and `/corpus/status` (159 concepts,
52/51/37/19 by domain).

### What landed

| Area | State |
|---|---|
| `apps/api/src/api/models.py` | All 13 tables from ARCHITECTURE's data model, plus the two practice-log tables — 15 in total |
| `apps/api/migrations/` | Alembic env + initial migration `6e1d353bc543`, applied and round-tripped |
| `apps/api/src/api/settings.py` | Pydantic Settings over every var in `.env.example` — nothing calls `os.environ` |
| `apps/api/src/api/db.py` | Sync psycopg3 engine + `get_session` dependency |
| `apps/api/src/api/model_router.py` | Job → model resolution and the Bedrock/Anthropic client factory. **No call sites yet** |
| `apps/api/src/api/seed.py` | `make seed` — idempotent corpus upsert |
| `apps/api/src/api/cost_report.py` | `make cost-report` — reads `llm_calls`, prints zeros on an empty ledger |
| `infra/compose/docker-compose.yml` | Postgres only (pgvector/pgvector:pg16) |
| CI | Postgres service + migrate/seed/db-test steps |

### Decisions worth keeping

- **`concept_evidence` gained its two-producer shape now rather than at Phase 9.**
  `item_id`/`session_id` are nullable, `practice_problem_id` and `source` are new, and a
  CHECK constraint enforces that exactly one of the two is set. Retrofitting a
  nullability change onto a populated immutable table later would have been the
  expensive version of this.
- **`InterviewSession`, not `Session`.** The table is `sessions`, but the class cannot
  be `Session` without shadowing `sqlmodel.Session` in every module that imports both.
- **Compose ships Postgres alone.** BUILDLOG previously deferred the whole file to
  Phase 6 on the grounds that composing not-yet-existing services would be guessing —
  that reasoning still holds for `api`/`web`/`executor` (none has a Dockerfile). Postgres
  is the one service that exists and is needed now. `make dev-api` runs uvicorn against it.
- **A `db` pytest marker, excluded by default.** The CHECK constraint has no SQLite
  equivalent, so the schema is only meaningfully tested against real Postgres. Default
  `pytest` stays hermetic; `make test-db` and CI run the DB tests explicitly.

### Things found by running them

- **`script_location = migrations` silently resolves against cwd**, so
  `alembic -c apps/api/alembic.ini upgrade head` worked from `apps/api/` and failed from
  the repo root — which is exactly how `make dev` and CI invoke it. Fixed with
  `%(here)s`. Would have shipped as a green local run and a red CI run.
- **Alembic's autogenerate emits `sqlmodel.sql.sqltypes.AutoString()` without importing
  `sqlmodel`**, so the generated migration failed at import. The import is added to the
  template; check it on every future autogenerate.
- **`corpus.Concept.deprecated_at` is a `date`, the column is a `datetime`.** mypy strict
  caught it before Postgres did; `seed.py` converts explicitly rather than relying on
  driver coercion.

### Deferred deliberately

- **Auth.** `docs/API.md` specifies GitHub OAuth and a signed cookie; nothing is
  implemented, and no endpoint currently requires one. Any route added before auth lands
  is open — that is fine while the only routes are `/health` and `/corpus/status`, and it
  is a gate before anything that reads or writes user data.
- **The `ModelRouter` has no call sites and has never made a real model call.** It
  resolves config and constructs a client; that is all that is verified. Token budgets
  (`MAX_TOKENS_PER_*`) are read into settings but **not enforced anywhere** — the
  middleware `docs/COST.md` describes does not exist yet.
- **pgvector is installed in the container but no table has an embedding column.**
  Semantic retrieval lands with the code that needs it. *Correction (2026-08-20): this
  entry originally said "the extension is created". It was created by hand with a one-off
  `docker exec … CREATE EXTENSION` on the dev database. **No migration runs it**, so a
  fresh clone does not have it — the claim was true of my machine and false of the repo,
  which is the distinction this log exists to keep.*

### Next

Phase 1 (corpus) and Phase 2 (executor) remain the real next steps, unchanged. When
Phase 3 proper resumes, it picks up auth, sessions, the agent loop, and the budget
middleware against a schema that already exists.

---

## Phase 2 (isolation layer) — the sandbox, measured rather than assumed · 2026-08-18

The executor's **isolation** layer, and only that. `POST /execute`, the language test
harnesses, and the complexity probe are **not** built — the `test_no_execute_endpoint_yet`
guard is still in place and still passing, deliberately.

**Verified.**

```
make check          33 passed, 10 deselected (hermetic — no Docker, 0.52s)
make test-sandbox   7 passed  (6 escape tests + 1 sanity control, real Docker, 11s)
ruff / format       All checks passed · 44 files formatted
mypy (strict)       no issues in 17 source files
secret scan         clean
```

### The escape tests were verified to FAIL

A green escape test proves nothing by itself, so each was re-run against a deliberately
weakened sandbox:

| Weakening | Observed | Test outcome |
|---|---|---|
| drop `--network none` | `tcp:REACHED` | would fail |
| drop the `/etc` overlay | `READ_OK:/etc/passwd` | would fail |
| drop the explicit `docker kill` | **container still running after its own timeout** | would fail |

A `test_sanity_a_normal_program_runs` control guards the opposite error: a sandbox so
broken it runs nothing would otherwise make all six escape tests pass.

### Three specified controls did not work as written

All three came out of measuring rather than reading, and all three would have shipped as
green tests verifying nothing. Full detail in `docs/SECURITY.md`'s new "Measured
behaviour" section; the short form:

- **`subprocess(timeout=)` on `docker run` kills the CLI, not the container.** The daemon
  keeps running the code and `--rm` never fires, so the container leaks too. Test 5 would
  have reported `timeout` correctly while a runaway container burned CPU indefinitely.
  Reproduced directly during the negative-control pass. An explicit `docker kill` (0.10s)
  is the actual enforcement; `docker stop` measured 10.1s against a SIGTERM-ignoring
  process, which is a hang wearing a timeout's clothes.
- **`--read-only` does not deny reads.** Test 2 was unachievable as specified. Needs a
  non-root `--user` plus an empty read-only tmpfs over `/etc`.
- **A custom seccomp profile replaces the default rather than layering on it**, so the
  spec's "default profile plus explicit denies" is not expressible. Writing the natural
  version would have *weakened* the sandbox — the default was measured genuinely blocking
  `unshare(CLONE_NEWUSER)`, which a `defaultAction: ALLOW` profile re-permits. Docker's
  default is left untouched and **`ptrace` is a named open gap**, not a solved problem.

### Smaller traps, each now a comment in `sandbox.py`

- `--memory` without `--memory-swap` grants an equal amount of swap, silently doubling
  the real limit.
- `--workdir` pointed at a tmpfs flips its mode from `1777` to `0755 root:root`, so every
  execution fails `PermissionError` on its own scratch dir unless `uid=,gid=,mode=` are
  passed explicitly.
- Exit 137 means both "OOM-killed" and "we killed it" — telling them apart needs
  `docker inspect .State.OOMKilled`, which `--rm` makes impossible. Hence run → inspect →
  remove, plus a labelled reaper.
- A recursive fork bomb was measured **exiting 0 with empty output**. Never infer success
  from exit 0 alone.
- **Bind mounts silently produce an empty directory on Colima** when the source is outside
  its shared mounts — no error at all — while working fine on Linux CI. Candidate code is
  fed on stdin instead, which sidesteps the class.

### An architectural question this raised, deliberately left open

`ARCHITECTURE.md` and `.env.example` (`EXECUTOR_URL`) describe the executor as a
long-lived HTTP service that the API calls. But launching a sandboxed container requires
access to the Docker socket, and **the Docker socket is root-equivalent control of the
host** — anyone holding it can start a privileged container mounting `/`. Giving it to
the service whose entire job is running LLM-generated code would invert the trust
boundary this project treats as its most valuable property.

That points at a different topology: the *trusted* side launches a short-lived,
credential-free container per execution, and `apps/executor` becomes the image and
in-container harness rather than a service. That is a real change to the documented
service diagram, so it is **not** being made unilaterally — `sandbox.py` is written as a
library that works under either topology, and the decision is owed before `POST /execute`
lands. Nothing is blocked meanwhile.

### Deferred deliberately

- `POST /execute` and the language harnesses — they need corpus items with real tests to
  run against (Phase 1), and the topology question above settled first.
- Vendoring Docker's default seccomp profile to close the `ptrace` gap.
- A purpose-built sandbox image. `python:3.12-slim` is used as-is; isolation lives in the
  run flags, not the image, and a Dockerfile is Phase 6 work anyway.

### Next

Unchanged: Phase 1 (corpus) and the rest of Phase 2 (execution/grading on top of this
isolation layer). Settle the executor topology question before `POST /execute`.

---

## Phase 1 (thin slice) — first real corpus content · 2026-08-19

Six coding items and six quant items — 3 archetypes + 3 instances each — authored by two
concurrent agents owning one file apiece (`data/items/coding.json`, `data/items/quant.json`).
Deliberately a **thin vertical slice**, not bulk authoring: the open question the Phase 0
log left ("how many items before the runtime exists to use them") is answered here as
"enough to prove the pipeline, then stop."

**Verified independently of both agent reports.**

```
corpus validate        159 concepts · 12 items (6 archetypes, 6 instances) · coding=6, quant=6
                       0 errors, 0 warnings
verify_reference_...   ok i.code.0001 12/12 · i.code.0002 10/10 · i.code.0003 11/11
  --strict-stub-check  zero stub passes
source URLs            15/15 return HTTP 200 (8 coding, 7 quant) — none fabricated
concept references     all resolve verbatim; every primary_concept is in its own concepts
source independence    every item cites >=2 sources on distinct registrable domains
make check             37 passed, 10 deselected
```

The three quant answers were re-derived from the statements rather than checked against
the authors' scripts: **39** (exact absorbing-chain solve, value iteration, and 300k-run
Monte Carlo at 38.99), **149/20** (backward induction *and* brute force over all 2^20
deterministic stop-set policies, which proves global optimality rather than assuming the
threshold rule), and **16/3** (exact enumeration of all 495 arrangements).

### Two validator gaps, both the shape this project keeps finding

Neither was a wrong answer — both were **checks that looked stronger than they were.**

**1. The originality rule is not enforced against sources.** `_check_originality` shingles
the statement against the item's own `sources[].evidence` field — *the author's own
paraphrase* — because the validator runs offline with no copy of the page. It catches an
author who pastes problem text into their evidence note and nothing else: **a statement
copied verbatim from a live URL passes cleanly.** The error message even reads "overlaps
N% of source `<url>` text", describing a comparison that never happened. `CORPUS.md` now
says what is actually enforced, and records that the rule is upheld by *process* — read,
close the tab, write from the pattern — with the shingle check as a backstop against one
specific slip. Closing it properly means snapshotting source text at research time, which
means storing third-party text this repo is otherwise careful not to hold. Deferred, named.

Worth noting the quant author ran the *real* check unprompted — stripped the HTML of all
seven cited pages and shingled the statements against actual page text: **max shared
12-gram 0, max 8-gram containment 0.000%.** It also caught one of its own drafts sharing a
generic 10-word phrase with a source (1.96%, far under the 15% threshold) and rewrote the
sentence rather than ship it.

**2. `reasoning_rubric` weights were never summed.** The weight check lived in the
`type: "rubric"` branch only, so a quant instance whose reasoning weights summed to 0.8
validated clean — and those criteria are what write evidence, so a short sum silently
scales every score derived from them. Found by the quant author reading the validator
rather than assuming it did what `CORPUS.md` claimed.

Fixed by extracting `_check_criteria`, shared by both branches, which now also rejects
duplicate criterion ids and criteria naming a concept that does not exist — the latter
matters because `concept_evidence.concept_id` is a foreign key, so an unresolvable
criterion concept is an insert failure at grading time rather than a mis-tag. It warns on
a criterion with no `levels`, since an LLM grader without score anchors drifts between runs.

Four tests added, and the checks were confirmed **load-bearing** by neutralising
`_check_criteria` and re-running: with it, three defects caught; without it, an item
carrying all three passes clean.

### Reference solutions are now verified, not trusted

`scripts/verify_reference_solutions.py` runs every coding item's reference solution
against its own tests **inside `executor.sandbox`** — the same isolation a candidate gets,
because verifying in a more permissive environment proves the wrong thing. It lives in
`scripts/` because it is the one place legitimately needing both `corpus` and `executor`,
and neither package should depend on the other (the executor's dependency list is held
deliberately short by `SECURITY.md`).

It was verified against synthetic solutions *before* any real content existed: a correct
solution passes 3/3, a constant-returning one is caught at 1/3, a raising one at 0/3, a
missing entrypoint is reported, and tuple/list results normalise. Note the
constant-returning stub still passed one of three tests — which is exactly why
`--strict-stub-check` exists.

The coding author's own oracle pass is worth recording as method: it recomputed every
`expected` value with a **separately written brute force** rather than with its reference
solution, and that caught **three hand-computed expected values that were wrong**.
Checking a solution against itself would have passed all three.

### A dependency that is specified but not installed

`GRADING.md` grades quant answers by **sympy equivalence**, so `1/3`, `0.333...` and `2/6`
all pass. **`sympy` is not a dependency of any package in this workspace** — it is absent
from every `pyproject.toml` and not importable in the project venv. The quant author
reported "sympy 1.14.0 is installed", which was true of whatever interpreter it reached,
not of this project. Nothing is broken today because the quant grader does not exist yet;
it is recorded here so the grader's first commit does not discover it. The three `exact`
strings on disk (`39`, `149/20`, `16/3`) are trivially parseable, so no content is at risk.

### Deferred deliberately

- The other two domains (`system_design`, `behavioral`) — same pattern, not yet run.
- Bulk authoring toward the ~400/~150 target. The slice exists to prove the pipeline.
- `cpp` reference solutions; the harness skips non-python languages with a notice.

### Next

Unchanged: the rest of Phase 2 (`POST /execute`, harnesses, complexity probe), still
gated on the executor topology question recorded in the Phase 2 entry above.

---

## Phase 1 (thin slice) — all four domains · 2026-08-20

The coding/quant slice extended to `system_design` and `behavioral`, again by two
concurrent agents owning one file each. **24 items: 3 archetypes + 3 instances in every
domain.**

```
corpus validate   159 concepts · 24 items (12 archetypes, 12 instances)
                  behavioral=6, coding=6, quant=6, system_design=6
                  0 errors, 0 warnings
source URLs       15/15 return HTTP 200 (9 design, 6 behavioral)
criterion weights  all 6 rubric instances sum to exactly 1.0 in float, not merely
                  within the validator's 1e-6 tolerance
criterion ids     unique per item; every one carries >=3 score anchors
concept refs      every item concept AND every criterion concept resolves verbatim
make check        37 passed, 10 deselected
```

The rubric domains are the first content to exercise the `_check_criteria` validation
added with the quant slice, and it passed clean rather than needing to catch anything.

### Verification is weaker here, and that is worth stating

Coding items are checked by *execution* and quant items by *independent re-derivation*.
Neither is available for a rubric: there is no reference solution to run and no number to
recompute. What was verified is **structure** — weights, anchors, concept resolution,
source liveness — plus a read of whether each criterion is actually citable to a
transcript span, as `GRADING.md` requires. Whether the rubrics *discriminate well* is
unproven and cannot be proven until real transcripts exist to grade. That is what
`GRADING.md`'s calibration harness is for, and it is not built.

Both authors did design against the failure mode: each behavioral instance carries a
criterion built specifically to separate a real story from a fluent generic one, and the
design criteria are phrased as observable acts ("computes both the daily aggregate and the
cost of the single worst notice, and cites that figure") rather than as qualities
("understands scale"). An uncitable criterion scores *not-demonstrated*, which is a
distinct state from failed.

### Both agents independently flagged the same misleading message — now fixed

The originality error read "statement overlaps N% of source `<url>` text" when it had in
fact compared against the item's own `evidence` note. Two agents, working separately,
each reported it unprompted. It now says *evidence note*, and the constants carry a
comment stating the scope plainly, because a check that names the wrong thing invites
exactly the false confidence `CORPUS.md` warns about. The underlying gap — no offline copy
of the page — is unchanged and still deferred.

### Method worth keeping

- **The quant author ran the real originality check anyway**, unprompted: it stripped the
  HTML of all seven cited pages and shingled the statements against actual page text (max
  shared 12-gram 0, max 8-gram containment 0.000%), then caught one of its *own* drafts
  sharing a generic 10-word phrase with a source and rewrote it rather than ship at 1.96%.
- **The coding author recomputed every `expected` with a separately written brute force**
  rather than with its reference solution, catching three wrong hand-computed values.
  Checking a solution against itself would have passed all three.
- **A 429 was diagnosed rather than treated as a dead link.** The design author hit a
  transient GitHub rate limit firing nine requests back-to-back, verified the page twice
  more plus the raw mirror, and warned that a verification loop would need pacing. It did
  — the same URL returns 200 with a 3s delay between requests.
- Three agents disclosed, unprompted, a rule they had bent or a source they had dropped
  (a 403 read via curl instead of the fetch tool; two candidate URLs rejected rather than
  cited; read-only `git status` calls against an instruction barring git entirely).

### Deferred deliberately

- Bulk authoring toward ~400 archetypes / ~150 instances. The slice exists to prove the
  pipeline end to end, and it does.
- Rubric calibration against real transcripts — blocked on transcripts existing.
- `cpp` reference solutions; the verifier skips non-python languages with a notice.

### Next

The corpus is no longer the blocker. The rest of Phase 2 — `POST /execute`, the language
harnesses, the complexity probe — now has real content to run against, and the executor
topology question that gated it is resolved (see ARCHITECTURE, "Where the sandbox
actually lives").

---

## Phase 2 (execution layer) — `POST /execute` · 2026-08-20

The half of Phase 2 that sits on top of the isolation layer. A submission now runs
against a corpus item's tests and comes back as a typed result.

```
make check            48 passed, 18 deselected (hermetic — no Docker, 0.54s)
make test-sandbox     15 passed (7 escape + 8 /execute end-to-end, real Docker)
verify-solutions      33/33 reference tests, zero stub passes, through the SAME harness
mypy (strict)         no issues in 18 source files
corpus validate       24 items, 0 errors, 0 warnings
```

### The Phase 0 guard was discharged, not deleted

`test_no_execute_endpoint_yet` asserted `/execute` returned 404, deliberately placed to
stop an execution path landing without its isolation tests. It is now replaced by tests
pinning the endpoint's contract, and the obligation it encoded was met literally: the
escape suite landed *before* the endpoint, and `/execute` gained its own
`test_the_sandbox_still_applies_to_submitted_code` — because an endpoint that quietly
bypassed the isolation would pass every escape test while defeating all of them.

### The protocol was wrong, and the content is what proved it

`ExecuteRequest.tests` was typed `str`, assuming an item ships test *source code*. It does
not: `gradingTests.tests` is a list of structured cases (`input`, `expected`, `kind`,
`hidden`) against a named `entrypoint`. The contract was written in the previous session,
before a single corpus item existed, and reading like a reasonable guess is exactly what
made it survive review. Corrected to match the schema, with the history kept in the
module docstring — **guessing an interface ahead of its data is how a contract ends up
describing something nothing produces.**

### One driver, not two

`scripts/verify_reference_solutions.py` had its own copy of the test-running driver,
written before `/execute` existed. Both are now `executor.harness`. A reference-solution
check that built its driver even slightly differently from the one candidates are graded
by would be verifying the wrong thing while reporting green — and the two copies had
already begun to diverge (the script's compared with a local `_norm`, the endpoint would
have needed its own).

### A bad test found a real bug

Writing the anti-forgery test, the first assertion drafted was
`assert out.total == 99 or out.total == 2` — which cannot fail. Rewriting it to actually
discriminate exposed that `parse_result` returned on the **first** marker line it found,
so a candidate printing a forged result line *before* the driver's would be believed.

Fixed two ways: the last marker now wins, and the driver flushes then `os._exit(0)` so
candidate code cannot register an `atexit` handler that prints a later line. The residual
is documented rather than papered over — a candidate that forges a marker and then exits
the process itself leaves its line as the only one, which is unclosable while the result
travels on the stdout the candidate can write to, and is out of scope under
`SECURITY.md`'s threat model (single user, no hostile population, and the only person
deceived is the one practising).

The lesson is the tautological assertion, not the bug: **a test that cannot fail hides
the thing it was written to check.** It was caught here only because the assertion looked
odd while being typed.

### What `/execute` refuses to do

- **Never turns a failed run into a score.** A timeout, OOM kill, missing entrypoint, or
  early `sys.exit(0)` returns a non-`ok` outcome with `passed = 0`, and `is_gradeable` is
  false. Scoring a timeout as 0/3 would write evidence of weakness against a concept the
  candidate may know perfectly well — `GRADING.md`'s "failure is a failure".
- **Never raises for a bad run.** Always HTTP 200 with an outcome, because the caller has
  to record the failure either way and an exception would lose the detail. 422 is reserved
  for a malformed *request* — a missing entrypoint field, zero tests, a typo'd limit.
- **Never runs unlimited.** A typo'd `wall_millis` is a 422, not a silent default cap.

### Deferred deliberately

- **The complexity probe.** `GRADING.md` requires running at increasing *n* and fitting
  the growth curve against `complexity_target` (every coding item declares one). It is a
  measurement problem, not a plumbing one — the Colima VM has 2 CPUs against CI's 4, and
  wave-1 of `learning_files` recorded `-O2` deleting timing loops outright — so it wants
  its own pass with real numbers rather than being bolted on here.
- **`cpp`.** `/execute` returns a `harness_error` naming the language rather than
  pretending; the corpus declares python only so far.
- **`peak_rss_kb`** is still always 0. Reporting a number nothing measures would be worse
  than the zero.

### Next

The interview runtime proper — sessions, the agent loop, grading, and the budget
middleware — against a schema, a corpus, and now an execution path that all exist.

---

## Phase 2 (complexity probe) — measured, and the generator turned out to be the point · 2026-08-20

The last named piece of Phase 2's deterministic grading. It catches what `GRADING.md`
asks it to: "the accepted-but-quadratic solution that passes small tests".

```
make check          59 passed, 23 deselected (hermetic)
make test-sandbox   20 passed (7 escape + 8 /execute + 5 probe, real Docker, 32s)
verify-solutions    3/3 reference solutions match their declared complexity_target
                    i.code.0001 slope 1.03 vs O(n) · 0002 slope 1.00 vs O(n)
                    0003 slope 1.06 vs O(n log S)
```

### The spec asked for something the schema could not express

`gradingTests` carried `complexity_target` and no way to build an input of size *n* —
test cases hold fixed `input` arrays, which cannot be grown. "Run at increasing n" was
**unimplementable as written**, and had been since the schema was authored. Added
`complexity_probe` (`generator` defining `make_input(n)`, `sizes`, `repeats`) and
back-filled it onto the three coding items.

### Thresholds are measured, because the textbook ones would fail correct code

Calibrated by running known functions through the same sandbox:

| function | theory at these n | **measured** |
|---|---|---|
| `for x in xs: t += x` | 1.00 | 1.006, 1.005 |
| `sum(xs)` | 1.00 | 1.107, 1.113 |
| `sorted(xs)` | ~1.09 | **1.505, 1.458** |
| nested `for`/`for` | 2.00 | 2.196, 2.176 |

Repeat trials agree to ~0.05, so verdicts are stable — but **measured slopes sit well
above theory**. `sorted` predicts 1.09 and measures 1.5. Bands taken from the textbook
would have called every correct `sorted`-based solution super-linear and written false
evidence of weakness. The bands come from the measurements, and the probe reports
`inconclusive` rather than guessing: `slower_than_target` requires clearing the band by a
0.35 margin, so an n-log-n solution against an O(n) target is never failed. Splitting O(n)
from O(n log n) by timing is unreliable and worth less than the cost of being wrong.

### The finding: a random generator disarms the probe entirely

The first negative control — a genuinely naive backward scan against an O(n) target —
was **not caught**, and the reason is the whole lesson. On random input that scan
terminates almost immediately, so it really is near-linear. Measured, same solution:

| generator | slope | verdict |
|---|---|---|
| random values | 1.277 | **matches** — walks straight through |
| ascending (worst case) | **2.032** | slower_than_target |

The reference monotonic stack measures 0.995 on the same ascending input, so the
adversarial generator separates the two cleanly rather than penalising both. **The probe's
power is in the generator, not in the curve fitting.** Both corpus generators are now
worst-case by construction — ascending for the span scan, an alphabet of exactly `k` for
the sliding window so a naive per-start rescan degenerates — and a test pins the finding
so nobody "simplifies" a generator back to `random.randrange` and quietly disarms the check.

### A fix that made things briefly worse

With adversarial generators the impostors became slow enough that the probe itself timed
out, and both came back `inconclusive` — **the most damning case producing the least
verdict.** The driver now carries a time budget: it stops repeating a run once one takes
over a second, stops growing n once the cumulative spend passes the budget, and reports
the points it has. Four points still land, and both impostors are caught at slope ~2.01.

Worth stating plainly: for one round of measurement the probe was strictly worse than
before, and only running it revealed that. A design reasoned through on paper would have
shipped the adversarial generators and called the job done.

### Deferred deliberately

- **Scoring.** The probe returns a verdict; nothing yet folds it into a score with
  correctness and hint penalties. `ProbeResult.penalises` marks the only verdict allowed
  to count against a candidate.
- **`cpp`.** The driver is Python-specific.
- **Rubric-graded domains** have no analogue and need none.

### Next

Phase 2's deterministic half is done: isolation, execution, and now growth. What remains
before a session can run end to end is Phase 3's runtime — sessions, the agent loop,
grading that writes `concept_evidence`, auth, and the budget middleware.

---

## Phase 2 (scoring) — a run becomes a score, and a score becomes evidence · 2026-08-20

The last thing Phase 2 owed, and the seam Phase 3 needs: `api.grading.coding` joins a
corpus item to its own tests, runs them in the sandbox, measures growth, and returns both
a score and the `concept_evidence` rows that score implies.

```
make check          87 passed, 31 deselected (hermetic; was 59)
make test-sandbox   28 passed — 7 escape + 8 /execute + 5 probe + 3 /probe + 5 grading
                    (real Docker, 139s)
verify-solutions    3/3 unchanged — slopes 1.03 / 1.05 / 1.07 against their targets
```

### The probe earned its keep, on a real item, for the first time

Three submissions to `i.code.0002`, graded through the whole path:

| submission | tests | slope | verdict | score |
|---|---|---|---|---|
| the item's own reference (monotonic stack) | **10/10** | 0.995 | matches | **1.00** |
| the same reference, two hints taken | 10/10 | 1.016 | matches | 0.855 |
| a naive backward scan | **10/10** | 2.017 | slower_than_target | **0.75** |

**The tests cannot tell rows 1 and 3 apart.** That item's largest stress case is n=800,
where a quadratic scan is still instant, so the impostor passes every single case. Until
now that was a claim about a synthetic pair in the probe's own unit tests; this is the
first time it has been demonstrated end to end, on corpus content, through the grader.

The premise is pinned as its own test: one case asserts `correctness == 1.0` for the
impostor *before* the next asserts the probe caught it. Without that, a future stress case
grown large enough to time the impostor out would leave the probe's test passing for
entirely the wrong reason.

### The spec's own formula paid a wrong answer for being fast

`GRADING.md` asked for "a weighted mix of correctness (dominant), complexity match, and
hint penalty". Implemented literally — `0.75 * correctness + 0.25 * complexity` — a
submission that fails every test and returns instantly scores **0.25**: `return []` is
O(1), and the probe would call it `matches`.

So complexity and hints became *multipliers* on earned correctness rather than terms
beside it. `score = correctness x complexity_retention x hint_retention`, where the last
two are only ever ≤ 1. Correctness is now the only term that can put points on the board,
which is what "dominant" should have meant. The doc was corrected rather than the code
bent to fit it, and a test (`test_a_fast_wrong_solution_earns_nothing_from_the_probe`)
holds the line.

The same reasoning fixes where the probe runs at all: it is **skipped when nothing
passed**, because against a zero it can only confirm the zero at the cost of a 20-second
sandbox sweep. Zero is the only place that gate can sit without creating a rank
inversion — gating at "all tests passed" would let an 11/12 quadratic (0.917, unprobed)
outrank a 12/12 quadratic (0.75).

### The wire contract is copied, and a test is what makes that safe

`apps/api` does not import `executor.protocol`. Importing it would make the service that
holds the database password depend on the package that owns the Docker-socket launcher,
and ship `executor.sandbox` inside the API image for the sake of three Pydantic classes.
So `api.executor_client` carries its own copy — and copies drift silently, in the worst
possible way: a renamed `passed` field would leave the grader reading a defaulted zero and
writing evidence that the candidate got nothing right.

`test_executor_contract.py` is the price of that choice. It validates every request body
the client builds against the real `ExecuteRequest` / `ProbeRequest` — both
`extra="forbid"`, so an invented or renamed field fails there — round-trips a real
response through the client's model, and asserts the two sides enumerate the same
outcomes, kinds and verdicts. Drift is a red test rather than a wrong score.

### Three small traps, each found by running something

- **`make test-sandbox` was path-scoped to `apps/executor`**, and so was CI's step. The
  new grading tests need the same real daemon and live in `apps/api`, so both would have
  skipped them in silence while reporting green. Both now select on the marker
  (`pytest -q -m sandbox`) instead of on a path.
- **pytest collected a source function as a test.** The grader's helper was called
  `test_payloads`; imported into a test module, pytest gathered it and failed with
  "fixture 'item' not found". Renamed `case_payloads`, with a comment saying why — the
  tempting fix was to add a fixture.
- **`TestClient` refuses a per-request timeout.** The client set one on every call, which
  is right against a real server and a deprecation warning against an injected test
  client. An injected client now owns its own transport policy; only a client this code
  constructed gets a timeout.

### Deferred deliberately

- **Persistence.** The grader is pure: it returns evidence rows and writes nothing.
  `concept_evidence` is still empty, and stays that way until there is a session to write
  rows against. That split is what will let a fixed grader be re-run over old artifacts
  instead of mastery being hand-patched.
- **Hint recording.** The penalty schedule is implemented; nothing records that a hint was
  given. `turns` has no hint column, so the count arrives as an argument from the caller.
  The column is owed with the session layer.
- **Per-concept attribution is uniform.** Every concept an item names gets the *same*
  score; only confidence differs (primary 0.9, secondary 0.54). A complexity miss is
  arguably evidence about `big-o-analysis` in particular, and this grader cannot say so —
  rubric criteria can name a concept, test-graded items have no analogue.
- **Full-pass confidence ignores what the suite contained.** Passing a trivial all-example
  suite claims as much as passing one with adversarial cases. Not a live risk — every item
  on disk carries ten or more cases across every kind — and inventing a correction nothing
  can measure yet is the mistake the complexity bands avoided.
- **`cpp` and `peak_rss_kb`**, unchanged from the entries above.
- **No server-side ceiling on `wall_ms` / `memory_mb`.** `/probe` inherits that open item
  from `/execute` and defaults *higher* (60s wall, 512 MB), bounded in practice by its own
  20s internal budget. Recorded in SECURITY.md, still owed.

### Next

Phase 3's session layer, which is now the only thing standing between a graded submission
and a mastery number: the `/api/v1` router, the session state machine, and
`POST /sessions/{id}/submissions` turning a grade into rows in Postgres. It is also the
first surface where auth stops being theoretical, since it is the first one that writes
user data.

---

## Phase 3 (session layer) — evidence stops being a return value and becomes a row · 2026-08-20

`/api/v1` exists, and with it the loop the whole project is for: plan a session, submit a
solution, grade it in the sandbox, write what it proves. `concept_evidence` has rows in it
for the first time.

```
make check          98 passed, 46 deselected (hermetic; was 87)
make test-db        17 passed (live Postgres)
make test-sandbox   28 passed (real Docker, 137s)
make test-e2e       1 passed (44s) — the first e2e test in the project
```

### The first end-to-end run

`make test-e2e` had been a Makefile target with nothing behind it since Phase 0. It now
runs one scripted coding session with **nothing stubbed**: a real executor process on a
real socket, real containers, real rows.

| submission | tests | complexity | score |
|---|---|---|---|
| `i.code.0001`, the item's own reference | passed | matches | **1.00** |
| `i.code.0002`, a naive backward scan | passed | slope 2.0, slower_than_target | **0.75** |

Session `complete`, report written, **8 `concept_evidence` rows** — four concepts per
item, primary at confidence 0.9, the rest at 0.54.

The socket is the part that mattered. Every other test injects the executor app
in-process, so the path a deployment actually uses — `EXECUTOR_URL` →
`ExecutorClient()` → HTTP → another process — had never been exercised by anything.

### The schema had nowhere to record a failed grading

`gradings.score` was `NOT NULL`. GRADING.md requires that a grader crash, timeout or OOM
kill be **recorded** as a failed grading, and with a non-null score the only options were
a fabricated `0.0` or no row at all — one corrupts mastery, the other hides the failure.

Migration `1408f9143d32` adds `status`, makes `score` nullable, and adds a CHECK:
`(status = 'graded') = (score IS NOT NULL)`. "Failed but scored 0.0" cannot be written.
This was specified in a document from Phase 0 and contradicted by a schema from Phase 3;
nothing caught it until something tried to record one.

### Timestamps had no timezone, and the lucky failure is what found it

`GET /sessions/{id}` reports elapsed seconds. The first call raised:

```
TypeError: can't subtract offset-naive and offset-aware datetimes
```

Every datetime column was a naive `TIMESTAMP` — SQLModel's default — while the code
writes aware UTC. So an aware value went in and a naive one came back.

Fixed at the schema, not at the call site: migration `137646f0d9a1` converts all **21**
timestamp columns to `TIMESTAMP WITH TIME ZONE`, with an explicit
`USING <col> AT TIME ZONE 'UTC'` so the conversion states what the existing rows meant
instead of inheriting it from whatever `TimeZone` the server happened to be set to.

Worth stating plainly: here the defect raised. In Phase 4's FSRS scheduling it would
**not** have — two naive datetimes subtract perfectly well and quietly mean whatever the
server's clock was set to. A db test now asserts a round-tripped `ts` comes back aware,
because the failure it guards against is silent.

### A planner that says it is not one

Real planning needs mastery, which needs evidence, which needed sessions — so this wave
ships the simplest honest selection: eligible items ordered by distance from a fixed
difficulty target, filled to the time budget. Every plan it produces carries
`"adaptive": false`, the strategy id `corpus-order-placeholder@1`, and a `why` string
saying no mastery data exists. It is deterministic, so the same request twice produces
the same session — a shuffling planner makes any bug found in a session unreproducible.

### Refusals that mean something

Every error is RFC 9457 `problem+json` with a slug a client can branch on. The ones worth
naming:

- **422 for a mode with no grader.** A quant session would plan real items and then
  dead-end at the first submission. Refusing at creation, naming the missing grader, beats
  an interview that can never complete.
- **409 for a second submission on one item.** Not `Idempotency-Key` support — a client
  cannot tell a retry from a real second attempt — but it refuses the harmful half of it:
  one item cannot write two sets of evidence into one session.
- **503 with "run `make seed`"** when the plan names items the database has never been
  told about. The corpus is the source of truth and `items` is a projection of it, so that
  gap is possible; this one **fired on the first run** — the local database had been
  seeded before any corpus item was authored — and it said so in a sentence instead of
  surfacing as a foreign-key violation three calls later.

### What ends a session

`complete` when every planned item has reached a *terminal* grading — and a **failed**
grading is terminal. Nothing can be resubmitted for that item, so waiting for it would
leave the session open forever; such a session completes with less evidence than it has
items, which is the honest outcome. `abandoned` keeps whatever was already graded, per
API.md: a session you quit halfway through is real data about the half you did.

`wrapping` and `grading` are in the spec's state machine and are **not** simulated. They
are the agent's and the rubric graders' states; passing through them in microseconds,
observed by nothing, would be theatre.

### Deferred deliberately

- **Auth — and it is now overdue, not merely absent.** Open routes that write user data
  are exactly what this file called a hard gate. `api.users.current_user` is the single
  seam it lands on.
- **The interviewer agent, the SSE stream, `turns`, hints.** No model call has been made
  by anything, so `llm_calls` is still empty and the budgets still enforce nothing.
- **`Idempotency-Key`** on both `POST /sessions` and `/submissions`.
- **Rubric and quant graders**, which is why only `coding` sessions can be created.
- **Mastery and cost routes**, and `GET /corpus/items/{id}`'s statement redaction.
- **Resubmission.** One artifact per item per session. Iterating on a solution is the
  interviewer loop's job.
- **Concurrency.** That one-per-item rule is a code check, not a unique index: two
  simultaneous submissions could both pass it. Single user, so it is a real hole with no
  realistic trigger — stated rather than closed.

### Next

Auth, before anything else. It is the only thing between "writes user data" and
"deployable", and every later wave makes it more expensive to retrofit. After that the
fork is real: the **interviewer agent** (the first model call, which makes the cost ledger
and the budget middleware live) or **Phase 4's mastery projection**, which finally has
evidence to replay.

---

## Phase 4 (ratings and scheduling) — the projection, and the test that proved it wrong · 2026-08-20

`mastery` is populated, and it is a *projection*: a graded session updates it in the same
transaction that writes the evidence, and `POST /mastery/recompute` rebuilds the whole
thing — item ratings included — from `concept_evidence` alone.

```
make check          110 passed, 56 deselected (hermetic; was 98)
make test-db        27 passed (live Postgres)
make test-e2e       1 passed (43s)
```

### The replay gate found a real bug on its first run

docs/ADAPTIVE.md's gate: "recomputing `mastery` from `concept_evidence` alone must
reproduce the live table exactly". It did not.

A timestamp written as `datetime.timezone.utc` comes back from Postgres as
`ZoneInfo("Etc/UTC")` — same instant, same offset, **different object** — and FSRS
compares `tzinfo` against `timezone.utc` by equality:

```
ValueError: datetime must be timezone-aware and set to UTC
```

The incremental path never saw it: those rows had not left Python. Only the replay reads
timestamps back from the database, so only the replay raised. Normalising at the boundary
(`moment.astimezone(UTC)`) fixes it, and the comment there says what it is for, because it
reads exactly like the no-op somebody deletes.

Worth noting what this cost: the previous wave converted every column to `TIMESTAMPTZ`
precisely so timestamps would carry their zone, and that fix was correct — this is a
*second*, independent trap in the same area, and only an end-to-end property test could
have found it.

### An item's rating drifted four times too fast

The bound in the item-rating test was `<= K_ITEM` (4 points from one attempt). Measured:
**9.1**.

One graded submission writes one evidence row *per concept the item names* — four, for
the coding items on disk — and the item update ran on each of them. An item's rating was
therefore drifting in proportion to how many concepts its author happened to list, which
is a fact about the corpus file, not about the candidate.

The item update is now tied to the *primary* concept's row: one attempt, one update, and
still derivable from evidence alone, which is what replay needs. The test now asserts both
halves — four evidence rows, one rating step — so the next person to "simplify" it sees
what it was for.

### Fuzzing off, and measured rather than assumed

`fsrs` (the FSRS-6 package) is used instead of hand-rolled arithmetic: spaced-repetition
parameters are *fitted*, and constants that merely look like FSRS would be a claim nothing
could check. Two of its defaults had to go:

| default | why it is wrong here | measured |
|---|---|---|
| `enable_fuzzing=True` | a jittered interval cannot be rebuilt from evidence | six identical reviews → **six different due dates** |
| `learning_steps=(1m, 10m)` | a concept is not re-drilled sixty seconds later | a due date always in the past, so every concept reads as overdue |

Both are pinned by tests, including a negative control that *demonstrates* the fuzzed
scheduler disagreeing with itself — "fuzzing off" reads like a preference until you watch
it produce five answers to one question.

### Confidence is what makes one result count more than another

The grader already distinguished a primary concept (confidence 0.9) from the ones an item
merely touches (0.54). That distinction would have been thrown away one layer later if the
rating moved the same distance for both, so `K` is scaled by confidence. A db test asserts
the primary concept moves further than the secondary from the same submission — which is
the whole reason the grader bothered to record two different numbers.

### Deferred deliberately

- **The weakness priority and the planner that uses it**, and therefore the other half of
  the Phase 4 gate — the simulated candidate with an injected weakness. The session
  planner remains the placeholder, and still says so in every plan.
- **Cold-start calibration.** `calibrating` is reported (fewer than five observations) and
  the K-decay already moves early estimates fast, but no separate calibration *plan*
  exists, because there is no planner to write one.
- **The weights** in the priority formula. Placeholders in a document, still.
- **The db tests share the development database.** Teardown deletes only the rows a test
  created, then replays the projection to restore the invariant — but the value assertions
  assume the concepts they touch start unmeasured. The day that database holds real
  practice history, these want a database of their own.

### Next

The planner. It is the last piece that turns all of this from a measurement into a
*behaviour* — the point where a weak concept changes what the next session serves — and it
is what the simulated-candidate gate exists to test. Auth is still owed before deployment.

---

## Phase 4 (the planner) — a gate that passed for the wrong reason · 2026-08-20

The engine chooses now: concepts ranked by weakness priority, then the item whose expected
score lands closest to the band where an outcome teaches something. Every plan carries the
reasoning — what each item targets, what you were expected to score, and the concepts it
weighed but did not serve.

```
make check          108 passed, 65 deselected (hermetic)
make test-db        36 passed (live Postgres)
make test-e2e       1 passed (43s)
```

### The gate passed, and it was worthless

docs/ADAPTIVE.md's Phase 4 gate: a simulated candidate who fails one concept and aces the
rest, and within five sessions a majority of served items must target the weakness. It
passed on the first run. It should not have counted:

```
session 1: served i.code.0002   <- the weak item, before any evidence existed
session 2: served i.code.0002
session 3: served i.code.0002
...
```

With nothing measured, every concept has an identical priority, so the ranking fell through
to its tie-break — sorting by concept id. `monotonic-stack` sorts before `sliding-window`.
The planner served the weak item five times out of five **by alphabet**, and the assertion
could not tell that apart from adaptation.

A gate that a default can satisfy is not a gate. It now also requires that the *first*
session not be the weak item, and that the engine finish rating that concept lowest of
everything it measured — which no tie-break can fake.

### Then the fixed gate failed, and found the real bug

With the majority requirement made honest, the ranking test failed on a stranger note:
after failing `monotonic-stack` five times, the candidate's *strongest* concept was
`monotonic-stack`.

The cause is one constant. `ability` started at **1200**, the number chess ratings start
from, while the corpus's instances are rated 1470–1830 (median 1550). Consequences, all
measured:

| with `ability = 1200` | |
|---|---|
| expected score against a median item | **0.12** |
| items inside the planner's 0.60–0.75 band | **none, ever** |
| scoring 0.2 on a 1600-rated item | *beats* a 0.09 expectation, so ability **rises** |
| five straight failures on one concept | rating goes **1200 → 1218** |

Elo was working exactly as specified; the origin of the scale was wrong. A new concept now
starts at **1550**, the median instance rating on disk. Same simulation afterwards:

```
session 1: served i.code.0001 (expected 0.599 — the item nearest the band)
session 2: served i.code.0002 -> failed
sessions 3-5: served i.code.0002

final: monotonic-stack 1519  <- weakest, correctly
       sliding-window  1567  <- strongest, correctly
       i.code.0001 elo 1480 -> 1478.6 (easier than believed)
       i.code.0002 elo 1600 -> 1603.0 (harder than believed)
```

It is a **fixed** constant, not a median computed from the corpus at import: a starting
rating that moved when the corpus gained an item would change what a replay of old evidence
produces, and the projection has to be reproducible.

### The tie-break now does real work

Concepts that tie on priority are ordered by how far their best item sits from the
informative band. That is the cold-start case — everything ties when nothing is measured —
and it is the difference between opening with an item you are expected to score 0.43 on and
one sitting on the band's edge at 0.599.

### Two limits that are the corpus's, not the planner's

- **The prerequisite gate usually has nowhere to send you.** `monotonic-stack` is gated by
  `stack-simulation`, and no item measures it. Substituting toward it would plan an empty
  session, so the plan reports the prerequisite and keeps the concept. Both branches are
  tested against the real DAG; only one is reachable with 24 items.
- **The band cannot choose an item, only a concept.** Each concept has exactly one item, so
  once a concept is picked, the item is forced. The mechanism is built and idle.

Neither is worth "fixing" in code. Both are what a corpus of 24 items looks like from
inside a planner built for 400.

### A route that answered 404 for a route that exists

`GET /mastery/weaknesses` returned a not-found problem document. FastAPI matches routes in
registration order, and `/mastery/{concept_id}` was declared first, so `weaknesses` arrived
as a concept id. Declaration order is now load-bearing and says so in a comment.

### Deferred deliberately

- **The weights.** `w1..w5` are the document's placeholders, moved into named constants so
  calibrating them is an edit in one place. Nothing has been calibrated, because
  calibrating them needs real sessions.
- **Cold-start calibration as a distinct plan.** A plan with no evidence behind it is
  marked `"calibration": true` and ordered by band distance, but there is no separate
  spread-across-domains strategy — with three coding items, there is nothing to spread.
- **Concept-level FSRS only.** `due_at` schedules a *concept*; nothing schedules an item.
- **The db tests still share the development database**, unchanged from the last wave.

### Next

Auth, which has been owed since sessions started writing user data, and after that the
interviewer agent — the first model call in the project's history, and the point where the
cost ledger and the budget middleware stop being empty tables.

---

## Phase 4 (review pass) — what a cold read found that a green suite did not · 2026-08-20

The engine was finished, every gate was green, and the suite had passed the two tests
docs/ADAPTIVE.md asks for. An independent review of `mastery`, `priority`, `planner`,
`sessions` and `grading` — read cold, against the design docs — found eleven things. Seven
were real enough to fix, and two of those were holes in the gates themselves.

```
make check          112 passed, 70 deselected (hermetic)
make test-db        41 passed (live Postgres; was 36)
make test-sandbox   28 passed (real Docker, 134s)
make test-e2e       1 passed (43s)
```

### The projection had no serialisation, and the suite could not see it

`grade_artifact` is a sync function run in a threadpool, one per submission, so two
gradings genuinely overlap on a deployed server. `apply_evidence` is a read-modify-write of
`mastery.ability` and `items.elo`. Every database test in the suite runs through
`TestClient`, **which executes background tasks inline** — so the whole suite had only ever
exercised the serial case.

Reproduced immediately, and in the worst variant available:

```
IntegrityError: duplicate key value violates unique constraint "mastery_pkey"
DETAIL:  Key (user_id, concept_id)=(01M0…, big-o-analysis) already exists.
```

All three coding items name `big-o-analysis`, so two submissions in flight both found no
row for it and both inserted one. The quieter failure is worse: two transactions that each
add their delta to the same rating lose one of them — the evidence row survives, its effect
does not, and a replay then legitimately disagrees with the live table.

Fixed with a Postgres advisory lock taken **before the evidence rows are constructed**, so
their `ts` values are stamped inside the critical section and the order a replay sees is
the order they were applied in. Held to commit.

The test that guards it took three attempts to become worth having:

1. Two threads and a barrier: caught it once, then passed three runs in a row. The window
   is microseconds wide, and a flaky guard is worse than none.
2. A delay injected into the read, so the overlap is deterministic — and it *still* passed
   with the lock disabled, because the exception-safety fix below now catches the collision
   and records a failed grading. `assert not errors` had become unfalsifiable.
3. Asserting the gradings actually **succeeded**. Negative control: 3/3 failures with the
   lock disabled, 3/3 passes with it restored.

### "Never raises" was a docstring, not a property

`grade_artifact` caught the three exceptions `grade_coding` was expected to raise. Anything
after that — the evidence insert, the projection update — escaped, and the `with Session(...)`
block rolled back **the `gradings` row along with it**. The session then reported that item
as `"grading"` forever, never completed, and refused a retry with `409` because the artifact
already existed. The only exit was `POST /end`, and the client had its `202` long before.

Live triggers existed today: the primary-key collision above, and an `IntegrityError` on
`concept_evidence.concept_id` if the corpus gained a concept and `make seed` was not re-run
— which `create_session` already guards for *items*, with a message telling you to seed.

Now: the whole body is guarded, and the failure row is written through a **fresh** session,
because a transaction that has already raised cannot be used to record why.

### A gate that skipped a column

`fsrs.Card()` stamps `card_id` from `datetime.now()` and sleeps a millisecond to keep those
ids unique. So every replay produced a different `mastery.fsrs_card` — and the replay gate
did not notice, because its snapshot compared four derived columns and not the card. Every
*number* matched; the row did not.

A first card is now built from the evidence (`card_id` and `due` derived from its `ts`),
which is both deterministic and 25ms faster per twenty concepts. The gate compares every
column the projection owns. Negative control: restoring the bare `Card()` fails two tests.

### The review slot was unreachable twice over

docs/ADAPTIVE.md asks for a minority of due-for-review items among the weaknesses. It could
not fire:

- Its "good at it" floor was `0.55` on the **normalised** scale — an Elo of 1810, 260 points
  above where a concept starts. Simulated with the real K decay, a candidate first crosses
  it on their **55th** consecutive success, because beating an item drags the item's rating
  down and shrinks every subsequent gain.
- Even with the floor fixed, the weakness pass fills greedily and always leaves *less than
  one item* of budget behind. Considered afterwards, review had nowhere to go — the items
  on disk are 20–25 minutes and a quarter of a 45-minute session is 11.

The floor is now in Elo, and the slot is **reserved before** the weakness pass runs, which
then skips it. A test drives it by writing a `mastery` row directly — the one place in the
suite that does, because reaching that state honestly takes dozens of sessions.

### A comment that claimed a property the code did not have

`recompute`'s docstring justified its tie-breaking by saying rows from one grading are for
different concepts and therefore independent. They are not: the primary concept's row is
what moves `items.elo`, and every secondary row for the same item reads that rating to
compute its own expectation. Applying a secondary first shifts that concept's ability by
~0.07 Elo — invisible in a report, and enough to fail the gate's `==`.

Also corrected, in the same docstring: the projection is a function of evidence **and the
corpus priors as they stand now**, not of evidence alone. `make seed` refreshes
`difficulty_elo` and `primary_concept_id`, so re-authoring an item's difficulty changes what
a replay of old evidence produces. That is the right behaviour and it is not what
"rebuildable from evidence alone" implies.

### Four smaller ones, all real

- **A connection pool leaked per submission** — `ExecutorClient` was constructed per
  request. One per process now.
- **The local user was created and discarded on every read-only request** — `current_user`
  flushed without committing, and a route that never writes rolls back on close.
- **The review query was ordered in Python over an unordered `SELECT`**, so two concepts
  due at the same instant picked differently between runs.
- **A misleading `422`.** Focusing on a concept that is only ever *secondary* — like
  `big-o-analysis`, named by all three coding items and primary to none — matched items,
  planned nothing, and reported "the corpus has no active coding instances matching this
  request", which sends you looking for a corpus problem that is not there.

### What this says about the suite

Every one of these lived under a green `make check`, and two of them lived *inside* the
tests meant to catch exactly that class of bug. The pattern is consistent: the suite tests
the code as the author imagined it running — serially, in-process, with `TestClient`
executing background work inline — and the defects were in the gap between that and how it
actually runs. Worth remembering the next time a passing gate is offered as evidence.

### Next

Auth, unchanged from the last entry, and then the interviewer agent.

---

## Repo discipline — two standing rules that had no gate · 2026-08-20

Two rules had governed this repo since Phase 0 and were written down nowhere: a change
documents itself in the **same commit**, and work is committed and pushed at every
checkpoint rather than at the end of a session. Habit had held them — of the 24 commits so
far that touched code, 20 changed documentation in the same breath. This wave writes both
down in `CLAUDE.md` and gates the parts a script can judge.

```
make check   112 passed · corpus valid · doc links 18 files · doc consistency 16 docs
```

### What landed

- **`CLAUDE.md`** — the working agreement: which document owes an update for which kind of
  change, the rules that keep the set coherent, the commit cadence and prefixes, and an
  explicit paragraph on what the scripts cannot check.
- **`scripts/check_docs.py`** (`make doc-check`, and a CI step) — five comparisons between
  claims that live in two places at once. `check_doc_links.py` proves a cross-reference
  *resolves*; this proves both ends of it still agree.
- **`scripts/docs_with_code.sh`** (pre-push) — refuses a push whose commits change code and
  no `.md`. `wip:` is exempt, because a checkpoint is not a unit of work, and
  `ALLOW_UNDOCUMENTED=1` is the deliberate exception, typed where it is visible.
- **`scripts/commit_hygiene.sh`** (`make hygiene`, the tail of `make check`) — reports what
  is uncommitted and what is unpushed. Never fails, and never runs in CI.

### The four commits that skipped documentation were all gates

Measured rather than assumed, and the pattern was not the one expected. Every commit in
this history that changed code and no document changed a **gate**: the secret scan
(`f707bb9`), reference-solution verification (`854da03`), the corpus validator's public
suffix list (`7e74da0`), and the test pinning `Settings` against `.env.example`
(`a952f80`). Nothing else slipped — not one feature.

That is a coherent blind spot rather than four lapses. A gate is the one kind of code a
reader of the documents never watches run, so it is the one kind whose behaviour they can
only learn from prose. `scripts/`, `hooks/`, `.github/`, the `Makefile` and
`pyproject.toml` are therefore all on the push gate's list of code.

### The doc gate found something on its first run

README's documentation table indexed `PRACTICE_LOG` as `Spec`, while that document's own
status header has read "Schema built, behaviour not" since the Phase 3 slice migrated its
two tables. Neither line is careless and nobody was going to catch it: they are in
different files and each is true of something.

Four phase rows also carried state cells no script could read — `thin slice`,
`deterministic half **done**`, `half built`, `schema only`. The state column is now a
controlled vocabulary (`complete` · `built` · `partial` · `not started`) with the nuance in
prose after a dash, because the verdict has to sit somewhere a script can compare and the
sentence after it is for a human. Phase 2 reads `**complete** — the deterministic half it
was scoped to`, which is what README's checkbox had been claiming on its own.

### The push gate's first draft passed vacuously

`git rev-list` was called with `|| true`, so a range it could not resolve listed no
commits, found no violations, and pronounced itself clean. What caught it was the test
written to prove the `wip:` exemption: it printed "clean, 0 commit(s) inspected", the right
answer for the wrong reason — the range was `HEAD~2..HEAD~1` in a repository with two
commits. An unresolvable range is now a loud failure.

Negative controls after the fix: one identical one-line code change is let through as
`wip: checkpoint` and refused as `feat:`, and over the last six real commits the gate
reproduces the one historical violation in range and clears the other five. Then the hook
itself, rather than the script it calls: a throwaway commit touching one script and no
document was refused by `git push`, and this wave's own push — code and documents
together — cleared both it and the secret scan.

### Every check in the doc gate was verified to fail

Against a copy of `docs/`, one perturbation at a time: a status header deleted, a doc
nobody indexed, a README checkbox flipped against the buildlog, a state cell written as
prose, and a wave entry dated after the "Where things stand" heading. All five were
reported, and the copy passed clean before and after each. Emptying README's table tripped
the vacuity guard instead of reporting perfect agreement — the failure a consistency gate
has to be protected from first, since a parser that matches nothing finds every set
difference empty.

### Deferred deliberately

- **Truth is not checkable.** Every gate here compares two documents to each other. A claim
  both files make and neither has verified passes cleanly. `CLAUDE.md` says so in the file.
- **No check that a unit of work leaves a buildlog entry.** The push gate accepts any `.md`
  change, a typo fix included. Requiring a `docs/BUILDLOG.md` diff was rejected as the kind
  of rule that gets routed around rather than followed.
- **`docs_with_code` does not run in CI.** It judges a range of commits, and a CI job on a
  squashed pull request cannot see one. The hook is the enforcement point and `git push
  --no-verify` walks past it: this is discipline with a backstop, not a control.

### Next

Unchanged by any of this: auth, owed since sessions started writing user data, and then the
interviewer agent.

---

## Phase 3 (auth) — the gate that had been owed since the session layer · 2026-08-20

Every route was open. That was defensible while the surface was `/health` and `/execute`
on a laptop, and stopped being defensible the moment `POST /sessions` started writing user
data — a line two entries of this file called a hard gate and crossed anyway. It is closed.

The threat it actually closes is not the laptop. It is Phase 6: the same code behind a
public ALB, where "no auth" means the internet can start sessions, read every transcript
and spend Bedrock credits. Closing it before that deploy costs a day; closing it during
one costs the incident.

```
make check          138 passed, 77 deselected (hermetic; was 112)
make test-db         48 passed (live Postgres; was 41)
make test-sandbox    28 passed (real Docker, 132s)
make test-e2e         1 passed (43s)
```

### What landed

GitHub OAuth in, a signed cookie afterwards, exactly as docs/API.md specified it:
`GET /auth/login` → GitHub → `GET /auth/callback`, plus `GET /auth/me` and
`POST /auth/logout`. The cookie is `HttpOnly`, `SameSite=Lax`, `Secure` unless configured
otherwise for plain-http localhost, and carries a user id, a GitHub id and an expiry under
HMAC-SHA256 — stdlib, no new dependency, and nothing secret inside it.

The guard is **one dependency on the `/api/v1` router**, not one per route. A per-route
decorator is a thing that can be forgotten; a prefix is not. `/health` and `/auth/*` sit
outside that prefix, so their exemption is structural rather than a branch inside the
dependency that someone widens later.

### There is no local login, and that is the point

The obvious convenience is a dev-only login route behind `AUTH_MODE=local`. It was
rejected: a flag is a thing that can be wrong in production, and the failure is silent and
total. Development instead mints a cookie *outside* the process — `make login`
(`python -m api.mint_session`) signs one with the same `SESSION_SECRET` the server
verifies with, which grants nothing that holding the secret did not already grant.

The property that buys: **the deployed API contains no code path that issues a session
without GitHub.** Not one that is switched off — one that does not exist.

### A missing secret answered "sign in at /auth/login", which nobody can act on

The first draft read the cookie first and resolved `SESSION_SECRET` only if one was
present. So a server with no secret answered `401` to a request with no cookie: advice to
go and log in, when logging in needs the same missing secret. The test asking for `503`
failed, and the fix is the ordering — configuration is checked before credentials are.

That distinction is now a rule the error module encodes: `not-configured` (503) is
separate from `unauthenticated` (401) and from `dependency-unavailable` (503), because
"the server is missing a variable" and "your cookie is bad" send an operator to different
places. The message names the variable.

### The first login has to adopt a row, not create one

`users.github_id` is unique and non-null, so the row that existed before auth carried a
sentinel `0`. A callback that created a new row for the real account would have stranded
every `concept_evidence` row written to date behind a user nobody can log in as — mastery
silently empty, history intact and unreachable. The callback adopts the sentinel row in
place instead, and a database test drives the whole flow to prove exactly one `users` row
exists afterwards.

A second real account logging in does *not* adopt anything: that means the configured
account changed, the newcomer starts with an empty projection, and it is logged as a
warning rather than quietly inheriting somebody else's practice history.

### FastAPI read a test helper's signature and turned it into a query parameter

`app.dependency_overrides[get_settings] = make_settings`, where `make_settings(**overrides)`
builds a test configuration. FastAPI inspects an override's signature like any other
dependency, so `**overrides` became a **required query parameter** named `overrides`, and
every route answered `400 malformed-request` instead of anything about auth. Twice — once
in each auth test module, because the second was written from the first.

The fix is a zero-argument callable, and the reason is now a comment in both files. Worth
knowing generally: a dependency override is not a stub, it is a dependency, and its
signature is part of the contract.

### What the guard was checked with

Nine tests cover the signature itself — a flipped byte, a stripped signature, another
server's secret, an expired token, a payload that is a list rather than an object, a
signed payload with no expiry. Then the one that is not about any particular route:

```python
def test_every_api_route_requires_a_session(client):
    paths = client.get("/openapi.json").json()["paths"]
    ...
    assert not open_routes, f"reachable without a session: {open_routes}"
```

It enumerates the surface from the schema the app generates, so it covers routes that do
not exist yet. Negative control: deleting the router's dependency fails it along with four
others; restoring it passes all 26. The route-surface test in `test_api_health.py` gained
the four `/auth` routes for the same reason it exists — a route added without a doc row
reads as unbuilt to anyone planning Phase 5 against the spec.

Two other verifications worth recording. Auth is decided **before** body validation, so an
unauthenticated caller with malformed JSON gets `401` rather than a critique of their
payload; the malformed-body test had to sign in to keep testing what it was written for.
And a stranger's session id now answers `404` — the same as a made-up one, because a `403`
would confirm it exists.

### Deferred deliberately

- **No server-side session store, so no instant revocation.** Logout clears the browser's
  copy; a stolen cookie lives until it expires. Rotating `SESSION_SECRET` invalidates every
  session at once, which for one user is the whole revocation story worth maintaining.
- **No rate limiting.** Login is the only unauthenticated write path and GitHub throttles
  it. Revisit with the ALB in Phase 6.
- **No CSRF token.** `SameSite=Lax` covers the cross-site `POST`, and a same-site attacker
  is already past everything else here.
- **`/openapi.json` and `/docs` stay open.** They describe a route surface that is in a
  public repo anyway.
- **Query scoping is not multi-tenancy.** Session reads are filtered by the caller's user
  id, matching what every mastery query already did. That is one `where` clause, not an
  enforced boundary, and docs/ARCHITECTURE.md now says so where it says multi-tenancy is
  out of scope.
- **The 30-day cookie lifetime is a constant, not a setting.** Six auth variables is
  already a lot of configuration to keep correct; a seventh nobody will tune is not worth
  the `.env.example` line the settings test would then require.

### Next

The interviewer agent — the first model call in this project's history, and the point where
`llm_calls` stops being an empty table and the budget middleware stops being a paragraph.
