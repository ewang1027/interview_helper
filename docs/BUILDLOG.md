# Build log

> **Status:** Current — this is the one document that always describes reality.
> If another doc and this one disagree about what exists, this one is right.

What has actually been built, phase by phase. `docs/ARCHITECTURE.md` describes the
design; this records what exists on disk and what the next phase picks up.

Rules for this file: record what was *verified*, not what was written. If something is
unverified, say so. If a gate was skipped, say that too.

## Where things stand — 2026-08-25

Entries below are **chronological, not in phase order**. Work has deliberately jumped
between phases, taking each only as far as needed to unblock the next — Phase 3's
persistence layer landed before Phase 1 had any content, because the practice-log spec
needed a real schema to be more than prose. Read this table first; the entries are the
detail behind it.

| Phase | State | What exists | What it still owes |
|---|---|---|---|
| **0** Foundations | **complete** | workspace, 159-concept taxonomy, corpus schema + validator, CI | — |
| **1** Corpus v1 | **partial** — thin slice | 48 items — 4 archetypes **and 8 instances** in every one of the four domains. The fourth archetype in each measures a **prerequisite** of a concept already served, which is what the planner's gate needs | bulk authoring toward ~400/~150, and archetypes for the other 143 concepts nothing measures as a primary |
| **2** Executor + grading | **complete** — the deterministic half it was scoped to | sandbox isolation (6 escape tests), `POST /execute`, `POST /probe`, complexity probe, reference-solution verification, **the coding grader** — score + evidence rows | `cpp`, `peak_rss_kb` — deferred, not owed |
| **3** Runtime + API | **complete** | the **session layer** (`/api/v1`, plan → submit → grade → report), **auth** (GitHub OAuth, a signed cookie, every route behind it), the **model-call path** (budget enforced, `llm_calls` written, `/costs` live), the **interviewer** (`POST /sessions/{id}/turns`, all five tools, `turns` written), the **SSE stream** (every event, `observation.recorded` included), **rubric grading** and the **quant grader** (a walled sympy answer check plus the derivation rubric) — all four modes grade | — *(closed 2026-08-25: a real session ran end to end on the Anthropic API — conversation, `run_code` against the sandbox, submission, grading, evidence. Bedrock is still gated on a use-case form; the provider switch is one env var)* |
| **4** Adaptive engine | **built** | Elo, FSRS, the replayable projection, the weakness priority, and a planner that drills a simulated injected weakness within ten sessions — five until `W_UNLOCKS` woke up | weights are placeholders until real sessions calibrate them; the gate's window scales with unmeasured foundational corpus |
| **5** Web app | **partial** — all ten routes | every route docs/WEB.md specifies plus the **practice log**: dashboard, `/session/new` with the plan shown before you commit, the **live session** (SSE, transcript, tool calls, hints with their cost) and its **four workspaces**, the report, `/concepts`, `/concepts/{id}`, `/history`, `/corpus`, `/costs`, `/practice` with LeetCode import, `/login`. Monaco served locally rather than from a CDN. 30 component tests, in `make check` and CI | **nothing has been opened in a browser** — no browser tooling here, so the visual layer is unreviewed; the Playwright gate, and a live session against a real interviewer |
| **6** AWS deploy | **partial** — step 1 of 5 | Dockerfiles for `api`, `executor` and `web`; `make up-stack` runs all of it behind a **Caddy front door** routing by path, the job the ALB does — so compose mirrors the target topology. Only the front door publishes a port. Sandbox isolation re-verified from inside the containerised launcher | steps 2–5: one service on Fargate by hand, Terraform, the rest of the stack, the portability gate — **all blocked on an authenticated AWS session**, not on code |
| **7–8** Voice, hardening | **not started** | — | — |
| **9** Practice log | **built** | the tables (migrated with the Phase 3 slice), the **classification call** behind a confidence gate, the **FSRS-inspired re-solve schedule**, and all **six endpoints** — a logged solve writes real evidence and moves the same projection a graded submission does | the hand-labeled gold set for calibrating the classifier, and a real model call — the same Bedrock gate every model path here waits on |

~~One thing worth knowing before reading anything else as further along than it is: **no
full session has run against a live model.**~~ **Closed 2026-08-25.** A full session ran on
the Anthropic API — the interviewer held a conversation, called `run_code` against the real
sandbox, reported 11 passing hidden tests, and the submission graded 1.0 and wrote evidence
for four concepts. `make test-llm` passes rather than skips. It cost **$0.0119**.

Struck rather than deleted, because the shape of the fix is the useful part: nothing was
wrong with the code. `MODEL_PROVIDER=anthropic` was built in Phase 3 and called "the escape
hatch", the pricing table already normalised both providers' model ids, and the switch was
four lines of `.env`. Bedrock remains gated behind an Anthropic use-case form
(docs/COST.md) and is still the intended home once credits apply.

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

### And then against a real server, because the tests never load the environment

Every test overrides `get_settings`, so nothing in the suite proved that `SESSION_SECRET`
is read from the environment at all — the one step between "the code is right" and "the
deployment works". Against `uvicorn` on a real port: `/health` 200 open; `/api/v1/mastery`
401 with a problem document; `/auth/login` 503 naming all three unset OAuth variables;
`make login`'s cookie accepted, and the same cookie with its last character changed
refused. With `SESSION_SECRET` unset in the environment, `/health` still 200 and
`/api/v1/mastery` 503 — fail-closed, from configuration rather than from a test double.

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

---

## Phase 3 (the model-call path) — the ids in `.env.example` had never worked · 2026-08-20

Everything around a model call, built before the thing that makes one: the budget check in
front of it, the ledger row behind it, and `/costs` over the top. The interviewer agent is
the next wave and this is what it will call.

The wave was supposed to be routine. It was not, because making the first real call in this
project's history is what discovered that **the model ids this repo has shipped since
2026-08-16 were never callable** — a four-month-old configuration that no test could fail
on, because nothing had ever tried it.

```
make check       149 passed, 90 deselected (hermetic; was 138)
make test-db      59 passed (live Postgres; was 48)
make test-llm      2 skipped — real calls, see below
```

### What landed

- **`api.llm.complete`** — the one path to a model. Budget checked, call made, `llm_calls`
  row written, in that order and without exception.
- **`api.pricing`** — a rate table keyed on model *family*, so a Bedrock inference-profile
  id prices the same as its first-party name. Anthropic list rates; Bedrock is partner-
  priced, so the dollar figure is an estimate and the AWS bill is authoritative.
- **Budget enforcement** — `429 budget-exceeded`, refused before the provider is called.
- **`GET /costs` and `GET /costs/budget`** — specified in docs/API.md since Phase 3, unbuilt
  until there was a row to report.
- **Per-job `effort`** — docs/COST.md asked for this ("grading high, utility classification
  low") and `ModelRouter` carried no per-job parameters. It does now, and omits `effort`
  for a model family that would reject it rather than making that model unusable.

### The first real calls, and what they found

Four probes against Bedrock, in order, each one answering the previous failure:

| Attempt | Result |
|---|---|
| `AnthropicBedrockMantle` + `anthropic.claude-haiku-4-5` | `MissingDependencyException` — the login credential provider needs `botocore[crt]` |
| the same, with `botocore[crt]` installed | `403 not available for this account` |
| `AnthropicBedrockMantle` + `anthropic.claude-opus-5` (the shipped id) | `404 the model does not exist` |
| `AnthropicBedrock` (InvokeModel) + `anthropic.claude-haiku-4-5-20251001-v1:0` | `400 on-demand throughput isn't supported. Retry with an inference profile` |
| `AnthropicBedrock` + `us.anthropic.claude-haiku-4-5-20251001-v1:0` | **`ok`** |

So: current Bedrock models are reachable only as **cross-region inference profiles**, the
`us.`-prefixed ids, and only on the classic InvokeModel client — the newer Mantle client
the SDK recommends for new code answers `404` for every id this account can serve. None of
the four `MODEL_*` values this repo shipped were in that shape.

A second sweep found what the account can actually reach: `us.anthropic.claude-sonnet-4-6`
and `us.anthropic.claude-sonnet-4-5-...` answer; every Claude 5 model returns *not available
for this account*; Haiku 4.5 returns *model use case details have not been submitted*. So
the routing table in docs/ARCHITECTURE.md — Opus 5 for planning and grading, Sonnet 5 for
turns — **is a design that cannot run here yet.** All four jobs now default to Sonnet 4.6,
which is a substitution recorded in three places rather than a quiet downgrade, and
docs/COST.md carries the measurements and the console steps that undo it.

### What the docs claimed and the wire said

Three specifics that would have been wrong if written from memory, and were checked against
the provider's own documentation before the code was:

- **Automatic (top-level) `cache_control` is not available on Bedrock.** The breakpoint is
  placed by hand on the system block, and a test pins the request shape — the failure mode
  is a larger bill and nothing else.
- **`output_config.effort` is rejected by model families older than 4.6.** Model ids are
  configuration here, so the router treats effort as a capability rather than a constant.
- **`budget_tokens` is gone** on every model this project routes to. Nothing in the new code
  reaches for it.

### The ledger row is written in its own transaction

The same reasoning as a failed grading, and for the same reason it was learned the hard
way: the caller's work can fail after the call, and a rollback that erases the record of
money already spent leaves a bill nothing explains. A test drives the caller into an
exception after a successful call and asserts the row is still there.

The budget check is deliberately "already spent", not "would this call fit". The input size
is not known before the call and asking the provider would itself be a call, so the last
call before a refusal can overshoot its ceiling by at most its own `max_tokens`. Bounded
and honest beat precise and expensive. Both scopes are tested by setting the limit *below*
what the ledger already holds, so neither test depends on what else is in the database.

### A paid test that `make test-db` was about to run

`test_llm_live.py` was marked `llm` **and** `db`, which reads as "needs both". Markers are
selection, not requirements: `make test-db` selects `-m db`, so the suite that runs after
every change would have made real model calls and spent real money. It is `llm` only now,
with `make test-llm` as its gate, and the docstring says it needs Postgres too.

### The cache assertion docs/COST.md asked for, and why it is not in CI

Two calls with an identical prefix; the second must report a non-zero
`cache_read_input_tokens`. It runs under `make test-llm` rather than in CI, because CI has
no credentials and a cache assertion against a fake provider asserts nothing at all.

### What is verified, and what is not

Verified: everything around the call, against a fake provider — the request shape including
the cache breakpoint, per-job effort, the ledger row and its cost, budget refusals in both
scopes, the routes, and the row surviving a caller that fails afterwards. Also verified:
that Bedrock answers this machine at all, by five raw SDK calls that cost about a cent.

**Not verified:** `complete()` end to end against a live provider. The AWS login session
expired between the probes and the test being written, and refreshing it is an interactive
command. `make test-llm` skips with the provider's own words rather than failing, which is
the correct behaviour for an environment condition — and it means the first thing to do
after `aws login` is run it.

### Deferred deliberately

- **No streaming.** The SSE stream is the interviewer's wave; `complete()` is one request
  and one response.
- **No tool loop.** Also the interviewer's — this layer makes a call, it does not decide
  what to do with a `tool_use` block.
- **No retry beyond the SDK's.** It already retries 429s and 5xx twice.
- **No `count_tokens` pre-check.** It would make the budget exact and cost a round trip per
  call to do it.
- **`botocore[crt]` is a dev dependency**, not a runtime one: it is needed by the *local*
  login credential provider, and a Fargate task role does not use it.

### Next

The interviewer agent: the system prompt per mode, the turn loop, the five tools in
docs/API.md, and `turns` finally getting rows. It is the first caller of everything above.

---

## Phase 3 (the interviewer) — a conversation that can run code · 2026-08-20

`POST /sessions/{id}/turns`, a system prompt per mode, three tools, and `turns` finally
getting rows. The first thing in this project that calls a model on purpose.

```
make check       174 passed, 102 deselected (hermetic; was 149)
make test-db      70 passed (live Postgres; was 59)
make test-llm      3 skipped — the account's Bedrock access is gated, see below
```

### What the interviewer is allowed to do

Three tools, not the five docs/API.md listed, and the shape of two of them changed:

- **`run_code` does not take tests.** The spec had the caller passing `tests[]`; the corpus
  owns them and the model supplies only source. Letting the model choose the tests would
  let it run a payload of its own devising *and* mark its own work, which are the two
  things this design spends the most effort preventing.
- **`reveal_hint` takes no item id.** There is exactly one item in play, and naming another
  would be a way to read ahead. Levels are enforced monotonic rather than trusted: skipping
  to the last hint is what a model trying to be helpful does, and it is the dearest one.
- **`end_round`** finishes an item, not the session. The last one moves the session to
  `wrapping`; grading still has to happen, and `_maybe_complete` is still what ends it.

`check_answer` and `record_observation` are not built, for reasons rather than for time:
the first is quant-only and no quant session can be created, and the second would make
`concept_evidence` have two producers before rubric grading exists, which is how one item's
concept gets counted twice.

### The prompt is a cached prefix, so it is byte-stable by construction

`api.agent.prompts.system_prompt` takes a mode and a corpus item and nothing else — no
clock, no session id, no dict rendered without a fixed key order — because prompt caching
is a prefix match and one changed byte re-bills everything after it. A test asserts two
builds of the same item are identical, and another asserts two different items are not, so
the first cannot pass by the builder ignoring its arguments.

The corpus statement goes inside `<problem>…</problem>` under a paragraph saying that
anything in it reading like a direction is content rather than an instruction. That is
docs/SECURITY.md's structural defence, and it is worth being precise about what it buys:
not immunity, but a tool surface where succeeding is worth very little.

### Hints turned out not to need the column docs/GRADING.md said was owed

`reveal_hint` writes a `turns` row carrying the tool, the item and the level; grading counts
the highest level that session took on that item. The turns are already the authoritative
account of what happened, and a column would be a second place for the same fact to live
and the first to go stale. A test takes two hints in conversation, submits the reference
solution, and asserts the recorded score is below the perfect one it would otherwise be.

### Three seams, and the third was found by a test spending real money

The executor arrives as a FastAPI dependency; so, now, does the model client. The first
draft of the route test reached into `api.llm` and replaced `complete` on the module — and
the replacement's `kwargs.setdefault("client", model)` did nothing, because `run_turn`
passes `client=None` explicitly and `setdefault` only fills a *missing* key. So the test
called Bedrock for real, and the failure that surfaced was a 503 from the provider rather
than an assertion about the route. `get_model_client` is a dependency now, overridden the
way `get_runner` already was.

### The `**overrides` trap, for the third time

`app.dependency_overrides[get_settings] = make_settings`, where `make_settings(**overrides)`
builds a test configuration. FastAPI reads an override's signature like any other
dependency, so `**overrides` becomes a *required query parameter* and every route answers
`400 malformed-request` — an error about nothing the test was checking. It has now cost
three debugging sessions across three files.

Fixed by removing the shape rather than remembering it: `conftest.use_settings(**changes)`
closes over a built object and installs a zero-argument callable, and it is the only way
the suite installs settings. In the same pass, `sign_in` stopped *assigning* the settings
override and started using `setdefault` — it had been silently replacing a test's model
configuration with the plain auth one, which is why two earlier tests passed despite
carrying the same trap.

### Bedrock answered, then stopped answering

The measurements in the previous entry were real: `us.anthropic.claude-sonnet-4-6` and
`us.anthropic.claude-sonnet-4-5-...` both answered. A handful of calls later, both began
returning `404 Model use case details have not been submitted for this account`. Nothing in
this repo changed in between. So the account gets a few calls through and then hits a
console gate — worth knowing before reading that 404 as a regression, and the reason
`make test-llm` skips today with the provider's own words.

Everything in this wave is therefore verified against a **scripted** model: the request
shape including the cache breakpoint and the tool list, the tool round trip, the transcript
rebuilt from the database on every turn, the state transitions, hints reaching the grader,
the budget refusal leaving the candidate's message recorded, and the tool-round cap. The
live test exists, runs one real turn, and is one form submission away from running.

### Deferred deliberately

- **No SSE.** A turn is one request and one response. The stream is the next wave and it is
  what makes `agent.message.delta` and `hint.revealed` real.
- **Tool results are replayed as text, not as `tool_result` blocks.** Faithful replay means
  storing every `tool_use_id` and reconstructing the block structure; the model gets the
  same information as text, and a transcript that cannot be malformed is worth more here.
- **Five tool rounds per turn, then a sentence in the transcript.** Each round is a paid
  call the candidate is waiting on. The cap is reported (`truncated`), not hidden.
- **The interviewer cannot end the session**, only a round. Ending an interview early is
  `POST /end`, which is the candidate's decision.

### The console page this file told you to visit does not exist

Follow-up, same day, after the advice failed in the obvious way: docs/COST.md said to
request access in the Bedrock console under *Model access*. **AWS retired that page on
2025-09-29** and now enables every serverless foundation model automatically, along with the
`PutFoundationModelEntitlement` permission and its API; control moved to IAM and SCPs.

The one exception is the thing actually blocking this account: **Anthropic models are
enabled and still require a one-time use-case form before first use.** The account says so
itself — `authorizationStatus: AUTHORIZED`, `entitlementAvailability: AVAILABLE`,
`regionAvailability: AVAILABLE`, `agreementAvailability: NOT_AVAILABLE`, and
`get-use-case-for-model-access` answering *"You have not filled out the request form"*.
Either the console playground or `PutUseCaseForModelAccess` submits it.

The same investigation answered a question this project had been carrying as a caveat.
`api.pricing` prices Bedrock calls at Anthropic list rates and said so, honestly, as an
estimate. Bedrock's own rate card for the model in use —
`aws bedrock list-foundation-model-agreement-offers --model-id anthropic.claude-sonnet-4-6`
— gives `$3.00/M` in, `$15.00/M` out, `$0.30/M` cache read, `$3.75/M` cache write. Identical
to the table, and it confirms both cache multipliers from the provider's own numbers rather
than from documentation. It also prices a one-hour cache write at 2x input, which is a good
reason to keep asking for the five-minute default.

### Next

The SSE stream, so a turn arrives as it is generated rather than all at once — and with it
`agent.message.delta`, `hint.revealed` carrying its price, and `grading.result`. After
that, rubric grading, which is what unlocks the other three modes.

---

## Phase 3 (the live channel) — a stream that admits when it lost something · 2026-08-20

`GET /sessions/{id}/events`. Every event docs/API.md specifies except
`agent.message.delta`, which needs a streamed model call and is the next wave.

```
make check       183 passed, 109 deselected (hermetic; was 174)
make test-db      76 passed (live Postgres; was 70)
```

### The gap event is the point

A stream whose `seq` is monotonic and gap-free lets a client tell **loss** from **silence**.
That only holds if the server is honest when it cannot deliver: the buffer is 256 events,
and a client reconnecting from before it gets a `stream.gap` naming what it asked for, what
is still available, and the instruction to refetch. Handing it a plausible stream starting
wherever the buffer happens to begin would produce a client that believes it is up to date
and is not — which is precisely the failure `seq` exists to prevent.

Sequence numbers are assigned in one place, under a lock, because two publishers to one
session genuinely overlap: turns run in a threadpool and grading runs in a background task.
A test runs eight threads publishing 200 events and asserts no number is reused.

### Subscribers poll, deliberately

Turns are sync and the stream is async, so an `asyncio.Queue` means cross-thread event-loop
plumbing — `call_soon_threadsafe`, a loop reference captured at the right moment, and a
class of bug whose symptom is a stream that silently stops. A 50 ms poll costs nothing
against a model call that takes seconds, cannot deadlock, and is four lines. It goes when
the bus does.

**The bus is in-process, and that is the honest limitation.** Under Fargate with two tasks,
a client could hold a stream against a task that is not running its turn: it would see
nothing and be told nothing was wrong. `EventBus.publish`/`.subscribe` is the seam where a
shared broker goes in Phase 6. Written down now rather than discovered then.

### `sse_starlette` calls `str()` on whatever you hand it

A dict passed as `data` goes out as a Python repr — single quotes, `None` for `null` — and
no JSON parser takes it. The first test to read the stream failed with
`Expecting property name enclosed in double quotes`, which is a good error to get from a
test and a terrible one to get from a browser. There is now one serialiser, `sse_frame`,
and both the bus and the route use it; `default=str` because a stream that dies on one
unserialisable field takes the session's whole channel with it.

### A session could reach `wrapping` and never complete

Found by writing the state test, not by it failing. `_maybe_complete` only ran on
`briefing` and `interviewing` — which was correct until this project's previous wave added
a `wrapping` transition when the interviewer ends the last round. A session that submitted
everything and then had its rounds ended would sit in `wrapping` forever, because grading
lands *after* the transition and the completion check declined to look. `COMPLETABLE_STATES`
now includes it; turns and submissions are still refused there.

### What publishes what

| Event | Published by |
|---|---|
| `item.presented` | the first turn on an item |
| `agent.tool_use`, `tool.result` | each tool call, before and after |
| `hint.revealed` | `reveal_hint`, carrying `score_penalty` — the price at the moment it is paid |
| `agent.message.done` | the end of a turn, including the tool-round cap's fallback message |
| `session.state` | `briefing → interviewing`, `→ wrapping`, `→ complete` |
| `grading.started`, `grading.result` | the grader, after the commit — and for a *failed* grading too, which is the outcome somebody most needs telling about |
| `budget.warning` | a call that leaves under 20% of either ceiling |

`grading.result` is published after the commit rather than before: an event announcing a
score that a rollback then discards is worse than a late one, because a client cannot
un-see it.

### Deferred deliberately

- **`agent.message.delta`.** The model call is not streamed, so a turn's text arrives once,
  on `done`. `done` is authoritative anyway, so a client written against this stream today
  keeps working when deltas start arriving.
- **`observation.recorded`**, with the tool that would produce it.
- **No replay from the database.** History is the in-memory buffer; a client that has been
  away longer than 256 events refetches the session. Persisting events would be a second
  transcript to keep consistent with `turns`.

### Next

Streamed model output, which turns `agent.message.delta` on and makes the stream worth
watching rather than worth polling. Then rubric grading, which unlocks the other three
modes.

---

## Phase 3 (streamed turns) — `agent.message.delta`, and one function that must not fork · 2026-08-20

The stream now has something to say while the model is thinking. `api.llm.stream` makes the
same call as `complete`, delivers the text through an `on_delta` callback as it arrives, and
returns the identical `Completion` built from the final message.

```
make check       183 passed (hermetic)
make test-db      79 passed (live Postgres; was 76)
```

### The thing worth being careful about is not the streaming

It is that a streamed call and an unstreamed one must be *counted* the same. Two entry
points is two chances for the ledger row, the price, the budget warning or the cache
breakpoint to drift apart, and the drift is invisible: a streamed call that quietly stops
being priced looks exactly like a cheap month. So there is one request builder — `tools`
then `system`, because that is the cache prefix — and one `_record_and_wrap`, and the two
entry points differ only in how they ask.

`on_delta` runs inside a request that is already being paid for, so an exception in it is
caught and logged rather than allowed to abandon the call. A test asserts a subscriber that
raises on every chunk still yields a completion with its usage intact: trading a rendering
problem for a lost answer *and* a wasted charge is the wrong trade.

### Deltas reconstruct the message exactly, and arrive before it

Both asserted, because both are what a client renders against. `agent.message.done` stays
authoritative (docs/API.md); a client that reconciles on it can only be correct if every
delta precedes it and the concatenation matches. The test pins the concatenation and the
ordering, and deliberately does *not* pin how many deltas arrive — chunking is the
provider's business, and asserting it would make this a test of the fake.

### Three edits lost to one script

Worth recording as a process failure rather than a code one. Three separate patch scripts in
this wave asserted several replacements and wrote the file only at the end; when a later
assertion failed — usually because `ruff format` had already re-wrapped the line being
matched — every earlier edit in that script was discarded silently. The symptom each time
was a test failing for a reason that made no sense against the code as written, because the
code as written was not what was on disk. The lesson is the same one this repo keeps
relearning about gates: verify the thing happened, do not assume it did.

### Next

Rubric grading, which is what turns `quant`, `design` and `behavioral` from planned modes
into sessions that can be created — `create_session` refuses them today because nothing can
grade them.

---

## Phase 3 (rubric grading) — a citation that is checked · 2026-08-20

`api.grading.rubric` judges an artifact against its item's rubric with structured outputs,
and `POST /sessions` stopped refusing `design` and `behavioral`. Three of the four modes
now run end to end.

```
make check       183 passed (hermetic)
make test-db     103 passed (live Postgres; was 79)
```

### The control that makes a rubric grade worth anything

docs/GRADING.md has asked since Phase 0 that every judgement quote the span it is based on.
Asking a model to cite is easy; the useful part is **checking the quote against the
artifact**. Whitespace and case are forgiven — a model that reflows a quotation has still
quoted it — and anything else is not. A citation that is not in what the candidate wrote is
a fabrication, and the criterion is demoted to not-demonstrated with the reason recorded.

Quotes shorter than twelve characters are rejected outright: `"the"` is a substring of
every answer and evidence of nothing.

### Not-demonstrated and failed are different, and the difference is the evidence

A criterion nobody addressed **scores zero** — you cannot be credited for what you did not
do — and writes **no `concept_evidence` row at all**. Recording silence as failure would
tell the adaptive engine you are weak at something it never observed, and mastery is
derived from evidence, so that lie would compound through every later plan.

The same rule catches the model skipping a criterion: nothing said about it is the same
conclusion as the candidate not addressing it, and it is the honest one.

### The response schema enumerates the item's own criteria

`output_config.format` with an `enum` of this item's criterion ids, so a judgement of
something not on the rubric cannot be expressed rather than having to be filtered out
afterwards. The anchors go into the request verbatim rather than summarised, because
summarising them is the same drift the anchors exist to prevent, just slower.

### Which grader runs is the item's decision, not the mode's

`grading.type` is what the corpus schema makes authoritative; a mode is only the set of
items it draws from. So `_grade` dispatches on the item, and an item whose type nothing
implements is a **failed grading with a reason** rather than a zero. Same for a provider
that will not answer: a test drives the grader into an unreachable model and asserts the
item reports `failed`, the score is NULL, and no evidence is written.

### A "hermetic" test suite that needed Postgres and left rows behind

The rubric tests started life unmarked, and passed — because Postgres happens to be running
on this machine. Every one of them wrote an `llm_calls` row, and eleven orphans were sitting
in the development database before the count was checked.

That is right, not a bug in the ledger: `api.llm` records every call, and a grader whose
cost became invisible when it was faked would be invisible in exactly the runs that
exercise it most. The tests are marked `db` now, clean up the rows they cause, and the
module docstring says why a test of a pure function needs a database.

### `quant` is still refused, and says why

Its answer check is deterministic — sympy equivalence, so `1/3`, `0.333…` and `2/6` all
pass — and sympy is not a dependency of this workspace. The rubric half would work today,
which is the temptation: a quant session that graded the reasoning and ignored the answer
would produce evidence nobody should trust. Half a grader is not a grader.

### Deferred deliberately

- **Quant**, above.
- **No transcript grading.** A rubric grades the submitted artifact, not the conversation
  around it. `record_observation` is what would make the transcript evidence, and it is
  still unbuilt for the reason it always was.
- **Confidence is a constant.** Rubric evidence is 0.5 against a deterministic result's
  1.0. Whether a cited, anchored judgement deserves more than an uncited one is a real
  question and needs real sessions to answer.

### Next

Quant, which is the last mode and the smallest remaining grader: a dependency, an
equivalence check, and the reasoning rubric it already shares with system design.

---

## Phase 2 (probe budget) — CI was the slow machine the probe had never met · 2026-08-21

Every CI run since the coding grader landed failed on the same test:
`test_the_probe_costs_the_quadratic_submission_a_quarter_of_its_score`. The quadratic
impostor — the case the probe exists for — came back `inconclusive; probe run ended in
timeout`. Locally the same test passes. Six pushes, identical failure, fully
deterministic: not flake, a machine-speed dependency.

```
make check          185 passed (hermetic; +2 driver-budget tests)
make test-sandbox   28 passed (real Docker, 72s — was 139s; smaller sweeps)
verify-solutions    3/3 — slopes 1.07 / 1.02 / 1.08 against their targets
CI                  the run carrying this commit is the verification; pending at writing
```

### SECURITY.md's "the wall is a backstop" was false on a slow machine

The driver's budget stops repeating a run once one takes over a second, and stops
growing n once the cumulative spend passes ~20s of process time — but both checks fire
*between* runs. Nothing prevented **starting** a size whose first run alone was
unaffordable. The bands were calibrated on this machine (arm64, the fastest thing this
code will ever run on); GitHub's runners execute the impostor's inner loop at roughly
2–3M iterations/s — several times slower — where `i.code.0002`'s n=16000 costs ~45–60s
by itself. The probe blew through its 60s wall mid-measurement, the sandbox killed it,
and "timeout" mapped to `inconclusive`: the most damning submission producing the least
verdict, which is the exact failure the budget was added to prevent, recurring one
level up.

The executor's own sandbox suite (`SIZES = [2000…16000]`) was passing on CI only by
landing on the cheap side of the same edge — the arithmetic puts its worst case right at
the wall.

### Two fixes: one defensive, one calibrated

- **The driver refuses to start a size it cannot afford.** Before each size it projects
  the first run's cost from the growth already measured (worst-case cubic when only one
  point exists) and stops — `truncated`, keeping the points it has — when the projection
  exceeds the remaining budget. Three points still judge, so the slow submission is
  caught rather than timed out. Two new hermetic tests pin the arithmetic against a fake
  `process_time` clock that the fake solution advances quadratically: the budget logic
  no longer needs Docker to be tested.
- **Corpus sweeps shrank to `[1000, 2000, 4000, 8000]`** (from `[4000…32000]` on 0001
  and 0002, `[2000…16000]` on 0003). At CI's measured speed a quadratic impostor now
  lands at least three sizes inside the budget, and every reference still measures
  linear (slopes above). The schema's `sizes` description and CORPUS.md's checklist now
  state the upper bound the field always had in practice, next to the noise floor it
  already documented.

### The lesson, stated once

A budget checked between units of work bounds nothing when a single unit can exceed it;
the check has to happen **before** the unit starts, from a prediction. And a probe
calibrated only on the fastest machine it will ever meet has not been calibrated — the
slow machine was always going to be the interesting one, because slow is what the probe
measures.

---

## Phase 3 (anchor scales) — a grader that capped a perfect answer at 0.75 · 2026-08-21

Found while starting the quant grader, which reuses the rubric grader for the derivation
half. It would have reused a bug.

```
make check       185 passed (hermetic)
make test-db     108 passed (live Postgres; was 103 — five anchor-scale tests)
```

### One constant, two scales

`api.grading.rubric` carried `LEVEL_MAX = 4.0` with a comment stating that the corpus
anchors criteria on 0/2/4. That was true of every rubric the grader had ever been pointed
at — `system_design` and `behavioral`, which is all `grading.type == "rubric"` selects.
It is not true of the corpus. Every `reasoning_rubric` on a quant item anchors on
**0/1/2/3**, and has since Phase 1:

| Items | `levels` keys |
|---|---|
| `i.design.*`, `i.behav.*` | `0`, `2`, `4` |
| `i.quant.*` (`reasoning_rubric`) | `0`, `1`, `2`, `3` |

So the first quant grading would have divided a top-anchor judgement by 4, scored a
**perfect derivation at 0.75**, and written that number as `concept_evidence` at rubric
confidence against `markov-chain-absorption`. Nothing would have failed. The score is
plausible, the evidence is well-formed, and the adaptive engine would have drilled a
weakness that was an artefact of the divisor — for every quant session, forever, since
mastery is derived by replaying exactly those rows.

The schema was wrong in the same way and in the other direction: `maximum: 4` told the
model it could answer 4 on a rubric whose anchors stop at 3, which is an invitation to the
one thing the anchors exist to prevent — a level no anchor describes.

### What replaced it

`level_max(criterion)` reads the top anchor off the criterion. Three consequences, each
with a test:

- **Full marks is the criterion's own top anchor**, so 3-of-3 and 4-of-4 both score 1.0.
- **The response schema reports the item's maximum**, computed from its criteria.
- **A level above the scale is clamped.** `maximum` is an instruction to a provider, not a
  guarantee from one, and nothing downstream should be able to score above 1.0 because a
  provider ignored it.

A criterion with no anchors at all keeps the old constant, now named `DEFAULT_LEVEL_MAX` —
the validator only *warns* on a missing `levels`, so that case reaches the grader. It gets
the widest scale on purpose: told to judge conservatively with no scale to read, a grader
should land low on a wide scale rather than high on a narrow one it invented.

`Judgement` now records the `level_max` it was judged against, so a stored grading says
what its numbers meant rather than leaving a later reader to assume a scale.

### Verified against the pre-fix arithmetic, not just asserted

The two scoring tests were re-run with the divisor put back to the constant: both fail
(`0.75` where `1.0` is owed), and pass on the fix. A test for a bug that never saw the bug
is a test of nothing — this repo has found that twice now, in the planner gate that passed
for the wrong reason and in the probe budget that CI disagreed with.

### The lesson, stated once

A constant whose comment describes *the data it has seen* is a bug waiting for the second
kind of data. The comment was accurate when written and wrong within a day of the corpus
growing, and neither the schema nor the validator constrains an anchor scale — nothing was
going to catch it except reading the other items.

### Next

The quant grader itself: sympy as a dependency, the answer check, and the reasoning rubric
this fix just made safe to reuse.

---

## Phase 3 (quant grading) — the last mode, and a wall in a new place · 2026-08-21

`api.grading.quant` checks the number and judges the derivation, `POST /sessions` stopped
refusing `quant`, and **all four modes now run end to end**. Phase 3's grader column is
closed.

```
make check       217 passed (hermetic; was 185 — +32, most of them the answer check)
make test-db     117 passed (live Postgres; was 108 — +9, the grade and a whole quant session)
```

### Two halves, because either alone writes evidence nobody should trust

The answer is checked symbolically — `39`, `3 + 9 + 27` and `1,024` are all expressions, and
`2/6` is `1/3`. The derivation is judged against the item's `reasoning_rubric` by
`api.grading.rubric`'s own code rather than a second copy of it: `judge_criteria` was lifted
out of `grade_rubric` for exactly this, so the citation check has one implementation and
cannot drift between two graders.

The weighting is `0.4 × answer + 0.6 × reasoning`. Below half on the number on purpose —
this is the arithmetic behind docs/GRADING.md's "a correct number with wrong reasoning is
not a pass", since a memorised value and a derived one are indistinguishable from the value
alone. The reverse matters as much: a sound derivation with a slipped digit keeps 0.6 rather
than collapsing to zero, which is how an interviewer scores it, and the rubric's own
arithmetic criterion already docks the wrong value where it belongs.

### The hard part was not the equivalence. It was finding the answer

Every real derivation states numbers that are not the answer. `i.quant.0001` is the clean
case: the answer is 39, and a good derivation says **27** out loud, because 27 is the naive
value the problem exists to refute. `i.quant.0002`'s answer is 7.45 and its derivation
passes through 5.5 and 6.75.

Both obvious rules are wrong, in opposite directions:

- **Scan the whole submission for a match** and the decoy passes — a candidate who computed
  27 and mentioned 39 in passing is marked correct.
- **Take the last expression** and "39 presses, which must exceed 27" is marked wrong. That
  is a correct answer punished for being sanity-checked, and it writes evidence of a
  weakness the candidate does not have.

What landed: the line the candidate **declared** their answer on wins from anywhere
(`Answer:`, `Final answer:`, last declaration if there are two), and failing that the last
line containing arithmetic at all is the conclusion, with any expression on that line
allowed to match. A declaration is unambiguous in a way no heuristic improves on; the
fallback is a guess, and it is priced as one — evidence from a declared answer carries 0.9,
the same as a hidden test passing, and from a read one 0.75. The check is equally
deterministic either way. What was inferred is *which expression it was pointed at*, and a
mis-read is a wrong verdict about a right answer.

**A stated answer and no answer stay separate**, the same way a not-demonstrated criterion
does: a candidate who never committed to a number scores zero on the answer half and writes
**no evidence** for it.

The limitation is pinned by a test rather than hidden: with no declaration and no other
arithmetic below it, a trailing sanity bound *is* read as the answer. Nothing in the text
distinguishes a check from a claim.

### A decimal is accepted at the precision it was written to

`5.33` is `16/3` to a person, and to this grader — provided it carries three significant
figures, so `5` is not a correct rounding of everything. The corpus authors had already hit
this and worked around it by hand, listing `5.333` and `5.33` in `accept_forms`; the rule
generalises what they were doing and leaves `accept_forms` for what the schema says it is
for — a mixed number, a currency figure — matched as bounded text and tried **last**,
because an equivalence sympy proved is a stronger thing to be right about than a substring
of a sentence.

### The wall, and the bug it hid

`parse_expr` evaluates what it parses, and what it parses here is a span of whatever the
candidate typed — the first untrusted text to meet something powerful **inside the API
process**, outside the sandbox, in the service that holds the database and model
credentials. docs/SECURITY.md now carries the control: a character allowlist, a 120-character
cap, numeric exponents bounded at 64, emptied `__builtins__`, and a lazily-counted node
budget. Every one of them is checked against the *text*, before the parse that would be
expensive — `9**9**9` is seven characters and passes every check that is not about the
exponent.

The allowlist was also where the wave's real mistake was. `parse_expr` resolves its own
rewritten source — `39` becomes `Integer(39)` — against the globals it is handed, so an
allowlist without `Integer`, `Float`, `Rational` and `Symbol` refuses **every expression**,
including `1/3`. And nothing pointed at it. The corpus items list their own answers in
`accept_forms`, so ten of the twelve smoke cases came back correct anyway, by substring
match; the two that did not looked like a punctuation bug in the accept-form guard — which
they also genuinely were. A dead parser was invisible in the passes *and* in the failures.

What caught it was not a test. It was printing **how** each case matched rather than only
whether it did: twelve rows of `method="accept_form"`, with no `exact` anywhere in a column
that should have been full of them.

That is the second half of the ordering rule above. `accept_forms` is tried last now, and
would have been anyway on the merits — but it also means a parser that refuses everything
fails loudly rather than being covered for by a list the corpus author wrote by hand.

### Two documents that had been false since the day they were written

Found while wiring the mode in, both fixed here:

- **`GET /sessions/{id}/report` shipped two hardcoded notes**, one saying "no rubric grader
  exists yet" and one saying no interviewer agent ran. Both had been false since 2026-08-20,
  and a quant report would have carried the first one under a column of quant scores. The
  notes are now **read off the session**: the interviewer note appears when the session has
  no turns, and the model-judgement note names the grader versions actually present in the
  evidence. A payload that states what does not exist is a document, and this repo's rule
  about documents applies to it.
- **`check_answer`'s deferral reason expired.** docs/API.md said the tool was unbuilt
  because no quant session could be created. That is no longer true; it is unbuilt because
  nobody has built it. The grading-time check exists as `api.grading.quant.check_answer`, so
  the tool is a thin proxy onto the same function grading uses — which is the point of
  having written it that way round.

### Deferred deliberately

- **No transcript grading**, unchanged. `record_observation` is still what would make the
  conversation evidence.
- **`tolerance` is absolute**, as the schema implies. The rounding rule covers the case that
  would otherwise want a relative band; whether any item needs one is a question for real
  sessions.
- **The two answer confidences are a guess.** 0.9 and 0.75 are reasoned, not measured, like
  every other constant in this system until sessions calibrate them.

### The lesson, stated once

A grader can be wrong in two directions and only one of them is loud. Marking a correct
answer wrong writes evidence of a weakness the candidate does not have, and mastery is
derived by replaying evidence, so it does not wash out — it compounds through every later
plan. That asymmetry is why the answer is read from a declaration where there is one, why a
rounded decimal is accepted, and why silence writes nothing at all.

### Next

Phase 3's remaining owings are `record_observation`, `check_answer` as a tool, and the one
that has been pending since the model-call path landed: **a full session against a live
provider**, still gated on the Bedrock use-case form in docs/COST.md.

---

## Phase 4 (item ratings) — the same drift, arriving by a different route · 2026-08-21

Found by self-review of the quant grader an hour after it was pushed, by reading what
`apply_evidence` does with the evidence shape the new grader produces rather than by
anything failing.

```
make check       217 passed (hermetic; unchanged — this is a projection rule)
make test-db     118 passed (live Postgres; was 117)
CI               green on the quant commit before this one
```

### A condition that was two conditions

The Phase 4 review fixed an item's rating drifting four times faster than it should, and
recorded the rule as "an item's rating moves once per attempt". The code that implements it
reads:

```python
if item is not None and evidence.concept_id == item.primary_concept_id:
```

That is not the rule. It is "once per **row naming the primary concept**", and it was the
same thing as the rule only because one row per concept was the only evidence shape that
existed. The quant grader writes a deterministic row for the answer *and* a rubric row per
criterion, and a criterion may name the primary concept too:

| Item | Rows naming its primary concept |
|---|---|
| `i.quant.0001` | 2 |
| `i.quant.0002` | **3** |
| `i.quant.0003` | 2 |

Each one satisfied the test, so `i.quant.0002`'s rating moved three times per attempt.
Measured on a coding item with three synthetic rows: **5.78 points against a `K_ITEM` of
4**, which is the drift the original fix was about, back at a comparable size.

Nothing failed. Every gate was green when this shipped, CI included, because no test
asserted the invariant on an item that could violate it — the coding items cannot, and
`test_an_items_rating_drifts_from_its_seed` measures exactly one of them.

### The fix, and why it is a query rather than a flag

The row that moves an item is the attempt's **first**, in the `(ts, id)` order `recompute`
already replays in. A flag from the caller would have been simpler and wrong: `recompute`
applies the same rows through the same function with no caller to set it, and a rule that
holds in the live path only makes the projection unreproducible — which is the one thing
this design cannot survive. Deriving it from the rows means both paths agree by
construction. The test asserts the rebuild reaches the same number, not just that the live
path does.

### Found while looking, not fixed

`i.design.0003`'s four criteria name `rate-limiting` — its primary concept — nowhere, so
under this rule its rating never moves at all, however many times it is attempted. It is
the mirror image of the same assumption: the rule presumes an attempt produces exactly one
reading of the primary concept, and the corpus can produce two or zero. The fix belongs in
the corpus validator as a warning, not in the projection, and it is recorded here rather
than done because it is a different change.

### The lesson, stated once

**A rule written down in prose and a condition written in code are two artifacts, and this
repo checks the prose against the code by reading.** The prose here was right the whole
time. What drifted was the set of inputs the condition was equivalent to it over — and
nothing in a green suite can notice that, because the shape that breaks the equivalence had
not been built yet when the tests were written. The generalisable habit is the one that
caught it: after adding a producer, go and read the consumers, particularly the ones whose
comments describe the *old* producer's shape.

---

## Phase 0 (validator) — the mirror image, caught at build time · 2026-08-21

The entry above recorded one problem fixed and one left standing: an item's rating moving
several times per attempt, and `i.design.0003`'s moving *never*, because no criterion on its
rubric names `rate-limiting` — the concept the item is chiefly a measurement of. Both come
from the same assumption, that an attempt produces exactly one reading of the primary
concept. The corpus can produce two, or zero.

The second one belonged in the validator, and now is one:

```
make check         219 passed (hermetic; was 217 — the check catches, and does not overfire)
corpus validate    0 errors, 1 warning — i.design.0003, as predicted
```

### A warning, not an error, and not a projection change

A rubric that measures a concept only through its parts is a defensible editorial choice,
and it is the author who has to make it. Retagging one of `i.design.0003`'s four criteria to
`rate-limiting` would change what that item's evidence *means*, which is not a decision a
validator or a grader gets to take on an author's behalf. So the build says so and leaves it:
**the corpus now validates with one warning**, which is the honest state.

Quant items are exempt. Their answer writes a row against the primary concept whatever the
reasoning rubric names, so the condition cannot arise there.

### Why this is worth a check at all

A rating that never moves looks exactly like a well-calibrated one. Nothing at runtime can
distinguish "this item's difficulty was estimated correctly" from "this item's difficulty has
never been measured", and the planner reads that number to choose what to serve next. There
is no failure to observe — only a number that is quietly always the author's guess.

Also hardened here: `grade_quant` now refuses an item whose `answer` carries neither `exact`
nor `numeric`, rather than marking every submission wrong against nothing. The validator has
errored on that shape since Phase 0, so it should never reach the grader — but a fabricated
zero corrupts mastery permanently and a failed grading is merely visible, and that asymmetry
is worth three lines of belt-and-braces.

---

## Phase 3 (`check_answer`) — the fourth tool, and the first one that is an oracle · 2026-08-21

The interviewer can now check a stated answer mid-round. It is a thin proxy onto
`api.grading.quant.check_answer` — the same function grading runs — and it is the first tool
on this surface that had to be **rationed** rather than merely bounded.

```
make check       226 passed (hermetic; was 219 — seven tool tests)
make test-db     119 passed (live Postgres; was 118 — the ration across turns)
```

### An oracle is a different kind of tool

`run_code` runs what the candidate wrote. `reveal_hint` hands over text the item already
contains, at a price. `check_answer` answers a question about the *answer*, and a question
you may ask without limit about a value you may choose is a search:

> is it 1? is it 2? is it 3?

Three calls in and a model that was only trying to be helpful has read the answer off the
grader and can hand it over. That is the same failure mode `reveal_hint`'s monotonic check
exists for — skipping to the most revealing hint is what helpfulness looks like from the
inside — and it is why docs/SECURITY.md's answer to prompt injection is the shape of the
tool surface rather than a filter on it.

So: **three successful checks per item per session.** Enough for a candidate revising a
stated answer, nowhere near enough to search. A refused check does not spend one, because it
told the model nothing about the answer, and charging for it would spend the ration on the
model's own mistakes. `checks_remaining` comes back with every result, so the limit is
visible rather than discovered.

### A cap in memory is not a cap

`ToolContext` is rebuilt every turn. A counter on it resets with each thing the candidate
says, so a model that asks again next turn has an unlimited oracle and a reassuring constant
in the source. The count is recovered from the **turn record**, which is already the
authoritative account of what happened in a session — the same decision, for the same
reason, as counting hints from turns rather than adding a column.

The test drives one check per turn and asserts the fourth is refused *a turn later*. Removing
the one line that restores the count makes it fail: the fourth check comes back clean.

### The signature this document specified had the flaw it argues against

docs/API.md listed `check_answer` as `{ item_id, submitted }`, and two paragraphs below
explains that `reveal_hint` takes no item id because naming a different one would be a way to
read ahead. The same argument applies unchanged and the signature had never caught up. The
tool reads the item from the context; API.md is corrected, next to `run_code`'s
already-recorded deviation of the same kind — both take away a parameter that let the model
choose what it was measured against.

### Next

`record_observation` is the last of the five, and the only one still deferred for a live
reason: it would make `concept_evidence` have a second producer, and a concept an item
already measures could be counted twice from one round. That needs the double-count rule
worked out first — which the projection now has an opinion about, since an item's rating
moves once per attempt whatever writes the rows.

---

## Phase 1 (`i.design.0003`) — the tagging gap and the rubric gap were the same gap · 2026-08-21

The validator warning added earlier today had exactly one subject: `i.design.0003`, whose
four criteria named every concept the item lists **except** `rate-limiting`, the one it is
chiefly a measurement of. Closed by authoring, not by retagging.

```
corpus validate    159 concepts · 24 items · 0 errors, 0 warnings
make check         226 passed · make test-db 119 passed (both unchanged — this is content)
```

### Retagging was the cheap fix and the wrong one

The obvious move is to point `counter_sharing_error` at `rate-limiting` and be done. That
criterion is about reconciling approximate counters across 40 locations and quantifying the
overshoot, which is `consistency-models` and is **already tagged correctly**. Retagging it
would have made a true tag less true to satisfy a projection rule, and left
`consistency-models` unmeasured in its place — moving the hole rather than filling it.

### Reading the archetype explained why the gap was there

`a.design.0003` says it outright:

> The weak answer names an algorithm and stops. The strong answer names the algorithm in a
> sentence and spends the remaining time on where the state lives and what happens when it
> is gone.

So the rubric spends its weight on locality, counter error, billing durability and outage
policy **on purpose**. The concept `rate-limiting` — "token bucket or sliding window limits,
applied at the right granularity" — is the topic, not the discriminator, and the author let
it fall off the rubric for a good reason.

But it fell all the way off, and it should not have. The instance's plan table gives every
plan **two** numbers — a steady rate and a burst ceiling — and **no criterion mentioned
burst anywhere**. A candidate who enforces one flat rate per key has misread the product,
and nothing in the rubric noticed. That is a measurement gap on its own terms, and it is the
same gap as the tagging one: the thing `rate-limiting` names here is precisely the thing the
rubric was not asking about.

### What landed

A fifth criterion, `algorithm_and_granularity`, tagged `rate-limiting` and weighted **0.1** —
the smallest on the rubric, because the archetype is right that naming the algorithm is the
weak answer's whole contribution, and its level-4 anchor says so explicitly ("does not spend
the rest of the answer on the algorithm"). The anchors turn on whether the mechanism admits
a burst above the steady rate and whether the two plan numbers become its two parameters.

The other four weights were scaled by exactly 0.9 rather than re-ranked, so the author's
relative emphasis survives intact: `store_outage_policy` is still the heaviest, the two
0.25s are still equal, billing is still the lightest of the original four.

### Found while reading, not fixed

The archetype lists four questions it measures, and the instance's rubric covers three of
them plus a billing criterion the archetype does not mention. The one it drops is *"what
does one enormous caller do to whichever key the counters live under?"* — which the
instance's statement also asks, in its fifth bullet, and which no criterion grades. That is
a real gap of the same kind, but it is a different one, and a sixth criterion would thin
every weight again. Recorded here for the authoring pass rather than folded in silently.

### The lesson, stated once

A build-time warning is worth adding even when its only subject looks like a tagging
oversight. Chasing this one down meant reading the archetype, the instance and the rubric
against each other, and what turned up was not a mis-tag at all — it was a question the item
asks in its statement and never grades. **The cheap fix would have silenced the warning and
kept the defect.**

---

## Phase 3 (`record_observation`) — the conversation becomes evidence · 2026-08-21

The fifth and last interviewer tool, and the first thing in this project to write
`concept_evidence` from something other than a graded artifact. Phase 3's tool surface is
closed.

```
make check       238 passed (hermetic; was 226 — twelve tool tests)
make test-db     123 passed (live Postgres; was 119 — the row, the ration, the replay)
```

### Why it was deferred, and what changed

The reason on record since the interviewer landed was that `concept_evidence` would gain a
second producer, and "a concept an item already measures could be counted twice from one
round". That is still true and is not fully solvable — an interviewer's read of a round and
a grader's read of the artifact from that same round are **not independent readings**. What
changed is that the projection now has an opinion about repeated rows: an item's rating moves
once per attempt whatever writes them, so the remaining exposure is on `ability` alone, and
it can be bounded rather than argued away.

So it is bounded, four ways, and none of the four is a new idea — each is a control this
project already applies somewhere else:

| Control | Value | Borrowed from |
|---|---|---|
| A quoted span, checked | must appear in **the candidate's** turns | the rubric grader's citation check |
| Signals | `strong` / `shaky` / `wrong` — no "never mentioned it" | "silence is not evidence" |
| Confidence | model's own number **× 0.25**, the lowest here | the rubric grader's level clamp |
| Ration | 3 per item, counted from the turn record | `check_answer`, and hints before it |

Three observations at the ceiling carry about 0.75 of one coding grading's confidence. That
is the intended order: what was said matters, and it matters less than what was submitted.

### The span is checked against the candidate, not against the transcript

docs/API.md asked for "a `span` citing the transcript". Implemented literally, that lets the
interviewer quote **its own leading question** back as evidence — "Would a monotonic stack
keep this linear?" is in the transcript, and an observation citing it records the model's
idea as the candidate's demonstration. It is the same fabrication the rubric grader's
citation check was written to catch, one layer up. So the span is matched against the
candidate's turns only, and the doc now says so.

The signal set falls out of the same rule. There is no `missing` signal, because "they never
mentioned X" has nothing to quote — and recording silence as weakness is the exact lie the
rubric grader refuses to tell.

### The tool does not write, and that is the point

`api.agent.tools`'s own docstring has said since the interviewer landed that a tool which
cannot reach a database cannot write evidence. Building the tool that produces evidence was
the moment to either keep that or quietly drop it. It is kept: `record_observation`
validates the observation and hands it back on the context, and the turn loop — which holds
the session and owns the transcript the span was checked against — writes the row and folds
it into the projection under the projection lock.

### A test that passed for the wrong reason, caught the same way as last time

The first version of "an observation does not move the item's rating" passed **with the guard
removed**. The observation named `two-pointers`, a secondary concept of `i.code.0001`, and
the item-rating branch only ever fires on the *primary* concept's row — so the test exercised
nothing. Pointed at `sliding-window` it fails properly without the guard: the rating drifts
0.099 points off its seed from a remark in conversation.

Third time this repo has found a green test that was green for the wrong reason. The habit
that catches it is cheap and is now just the routine: after writing a test for a fix, break
the fix and watch the test fail.

### The replay still reproduces, which is the whole claim

A session carrying **both** producers — an observation mid-round, a grading afterwards — is
replayed by `POST /mastery/recompute` to the same `mastery` rows, the same observation
counts, the same FSRS stability and the same item ratings. The order matters and is
preserved: the rows are not independent, and applying them the other way round computes a
different expectation for the second. An observation is an ordinary evidence row in every
respect except its `source` and its confidence, which is exactly what makes the rebuild work
without the projection having to be taught about it.

### Deferred deliberately

- **No domain check on the concept.** An observation about a quant concept during a coding
  interview is probably a mis-tag, but the corpus validator treats the same situation as a
  *warning* on an item, because it is occasionally legitimate. Refusing it here would be
  stricter than the corpus is about itself.
- **The ceiling and the ration are chosen, not calibrated**, like every other constant in
  this system until real sessions exist to calibrate against.
- **Nothing reads observations back yet.** They move mastery, and mastery drives the
  planner, so they already do their job — but no report distinguishes "you were drilled this
  because of what you wrote" from "because of what you said". That is a Phase 5 question.

### Next

Phase 3 owes exactly one thing now, and it is not code: **a full session against a live
provider**, gated on the Bedrock use-case form in docs/COST.md. The phase stays `partial`
rather than being promoted, because this repo's rule is that built means something that ran
proved it, and that one has not run.

---

## Phase 9 (practice log) — solved elsewhere, counted here · 2026-08-21

Classification, scheduling and six endpoints. A problem you solved on LeetCode now writes
real `concept_evidence` and moves the same `mastery` projection a graded submission does.

```
make check       248 passed (hermetic; was 238 — the schedule and the request shape)
make test-db     138 passed (live Postgres; was 123 — the flows, the gate, the replay)
```

### The gate that stops a guess becoming permanent

`concept_evidence` is immutable. That is the whole design, and it is exactly what makes a
classification call dangerous: a row written against a tag the model guessed wrong could
never be retracted without an amendment mechanism nothing else here needs.

So nothing is written against a guess. Below `0.75` confidence the problem lands
`pending_classification` — recorded, listed, **out of the review queue**, feeding nothing —
until a human confirms or corrects it, which is what writes the evidence that waited. The
proposal is still shown, because correcting one beats retyping it.

A pending problem also carries **no schedule**. That was not in the spec and it follows from
the same reasoning: a due date on something that feeds nothing is a prompt to re-solve a
problem the system could not record you having re-solved.

### A provider that is down must not cost you the entry

`classify` never raises. A logged solve is something a person actually did, and losing the
record because a provider hiccuped would be the expensive failure; landing it in the pending
state a human already resolves costs a confirmation.

The first version of that was wrong in a way a test caught immediately: it caught
`ProblemError`, the class `api.llm` maps provider failures to, and nothing else. A raw
provider or wiring error — the test used a client that simply raises — went straight through
a function whose docstring says it never raises. It now catches broadly and logs a
traceback, so a bug in there is visible rather than quietly becoming a pending problem
forever.

### Two departures from the spec, both recorded rather than smoothed over

- **docs/PRACTICE_LOG.md gave a confidence for a failed re-solve (0.5) and none for a
  successful one.** A self-reported solve is now `0.7`: above a rubric judgement's 0.5,
  because it is a fact about a real solve rather than a model's read of prose — and well
  below a hidden test's 0.9, because nothing checked it. Secondary concepts take the same
  fraction of that the coding grader uses, rather than a second opinion about the same
  question.
- **Both ARCHITECTURE.md and COST.md said the classification needed no new job type.** It
  needed no new *model*, which is not the same thing: the ledger records whatever job the
  router was asked for, so logging under a name the router did not know would have been a
  label free to drift from what was actually called. `practice_log_classify` is its own
  router entry pointing at the same model, which gives shared routing and a distinguishable
  bill at once. Both documents are corrected.

### The one mutation in an append-only table, stated out loud

`practice_solves.concept_evidence_id` is filled in later for a solve logged before its
classification resolved. It is a pointer, not the record: what the row says happened — a
solve, at this time, successfully — is never rewritten. Worth naming because "append-only"
is a claim this project makes about several tables and an unremarked exception is how such a
claim stops being true.

### Found by running it: the teardown that could not run

Eleven tests errored in teardown on a foreign key, because `practice_solves` points *into*
`concept_evidence` and the fixture deleted evidence first. The tests themselves passed, so
the suite read as almost-green while leaving rows behind — and those rows then failed four
*unrelated* tests in the next full run, which is how it was noticed: a concept with 34
observations where the test expected 1.

Two things worth keeping. A cleanup that fails is worse than one that does not exist,
because it fails quietly and the damage lands somewhere else. And this development database
is shared by every `db` test, so anything that writes to the shared projection has to clean
up in dependency order and then replay — the same rule conftest already follows, which is
where the ordering should have been copied from.

### Deferred deliberately

- **The classifier is uncalibrated.** No gold set, and no real model has classified
  anything — the same Bedrock gate every model path here waits on. `0.75` is a threshold
  chosen against a scripted classifier, which is to say against nothing.
- **Concept ids are not domain-checked.** An observation about a quant concept on a coding
  problem is probably a mis-tag, but the corpus validator treats the same situation as a
  warning on an item, because it is occasionally legitimate. Being stricter here than the
  corpus is about itself would be a rule with no reasoning behind it.
- **No `Idempotency-Key` handling.** The spec asks for it on creates; nothing in this
  project implements it yet, and logging the same problem twice is a duplicate row rather
  than a corruption. It belongs with the convention, not with this feature.

### A filtered listing that stopped early

Caught by re-reading the pagination after the wave was pushed. `GET /practice/problems`
filters `concept_id` in Python — the secondary ids are a JSONB array, and a containment
query wants a GIN index a personal practice log will never need — and it decided
`next_cursor` **after** that filter ran. So a page whose rows all failed the filter reported
no cursor, and a client stopped believing it had seen everything while matching problems sat
further back.

The cursor now describes where the *scan* reached rather than how many rows matched, so a
filtered page may come back short or empty and still say where to continue. Pinned by a test
that pages one at a time past two non-matching problems to reach a third; with the old
ordering it finds nothing at all.

The general form is worth keeping: **a limit and a filter have to be applied in the order
that keeps the cursor meaningful**, and a short page is ordinary while a truncated list that
looks complete is not.

### Next

Phase 1's corpus is now the binding constraint on everything else. Twenty-four items is
enough to prove four graders and an adaptive engine work and not enough to be trained by:
docs/ADAPTIVE.md's two "structural at 24 items" limitations — the prerequisite gate with
nowhere to send you, and an informative band that cannot choose between items because there
is only ever one — are both statements about the corpus, not the engine.

---

## Phase 1 (coding, second instance per archetype) — the corpus gets a choice · 2026-08-21

Three new coding instances, one per existing archetype, at ratings deliberately unlike the
ones already there. The corpus goes from 24 items to 27, and coding from three instances to
six.

```
corpus validate    159 concepts · 27 items (12 archetypes, 15 instances) · 0 errors, 0 warnings
verify-solutions   6/6 references pass their own tests in the sandbox — slopes 1.06 / 0.99 /
                   1.07 / 1.03 / 1.02 / 1.08 against their declared targets
make check         248 passed (hermetic) · make test-db 139 passed (live Postgres)
```

| New item | Archetype | Rating | What it is |
|---|---|---|---|
| `i.code.0004` | `a.code.0001` | easy 1360 | the window's budget is a *count*, not a distinctness — one counter, no map |
| `i.code.0005` | `a.code.0002` | hard 1740 | nearest-smaller on **both** sides, so the stack settles a block rather than a span |
| `i.code.0006` | `a.code.0003` | medium 1620 | the bisected quantity is a rate, and the feasibility check is a sum of ceilings |

### What this fixes, and what it does not

docs/ADAPTIVE.md carried two limitations described as "structural at 24 items". They are
not the same kind of thing, and only one of them is about the number of items:

- **The informative band could not choose *which* item to serve, only which concept** —
  because there was exactly one instance per archetype. Now there are two for every coding
  archetype, and the band demonstrably chooses. A cold-start candidate at the default 1550
  is served the new easy item at an expected score of **0.75**, squarely in the band, where
  before the closest thing was `i.code.0001` at 1480. Lifted.
- **The prerequisite gate still has nowhere to send you.** Substitution only moves toward a
  concept some item carries as its **primary**, and an instance inherits its archetype's
  primary — so three new instances added zero new primaries. Twelve primaries across 159
  concepts, unchanged. Closing that needs new *archetypes*, which is a different and more
  expensive piece of work than this one, and the doc now says so instead of implying item
  count is the variable.

### `O(n log n)` is a much weaker declaration than it looks

`i.code.0006` was authored with `complexity_target: O(n log n)`, which is a true statement
about the algorithm. Running its naive impostor — a rate-by-rate scan — through the real
probe returned **`inconclusive` at slope 2.00**.

That is the probe behaving exactly as designed. The linearithmic band's ceiling is 1.75 and
the margin 0.35, so nothing under 2.10 is called slow; the cushion exists because
distinguishing n log n from n² at these sizes is genuinely hard, and failing a correct
n-log-n solution is the worse error. But the consequence is worth naming: **an item
declaring `O(n log n)` gets materially less protection than one declaring `O(n)`.**

The fix was to say something truer. The binary search here is over the *rate* range, not
over n — `O(n log M)`. `classify_target` drops a log over any symbol that is not `n`,
because the probe only varies n, so that reads as the linear band: the reference measures
1.08 against a 1.30 ceiling, and the same impostor is now caught at **2.01 against a 1.65
threshold**. The authoring checklist in docs/CORPUS.md carries this, with the instruction
that matters most — check the target by running an impostor, not by reading the band table.

### Four tests were measuring the corpus, not the code

Growing the corpus broke eight database tests and one hermetic one, and every failure was
the same mistake in a different place: **an assertion that pinned an identity where it meant
a property.**

| Test | Pinned | Now asserts |
|---|---|---|
| `test_focus_concepts_narrow_the_pool` | `== ["i.code.0002"]` | every eligible item tagged with the concept, computed from the corpus |
| `test_agent_loop_db` (7 tests) | `FIRST_ITEM = "i.code.0001"` | the item the planner actually served, read from the plan |
| `test_a_due_concept_you_are_good_at_takes_one_slot` | `REVIEW_ITEM = "i.code.0003"` | the entry with no priority — structurally the review slot |

The last one is the interesting one, because it was not merely brittle: at the hand-written
ability of 1750 the *new* item is squarely in the informative band, so the ordinary weakness
path serves it and the review slot is never reached. The test's premise — a concept you are
good at that nothing in-band can measure — had quietly stopped being true of the corpus. The
ability is now 2100, which re-creates the scenario, with a comment saying that the number
expresses a situation and the situation depends on what is on disk.

Worth stating once: **a test that names a corpus item is a test of how many items the corpus
holds.** That is a thing this project intends to change roughly four hundred more times.

### Also found: a stale seed is 47 failures

The first full `make test-db` after authoring failed 55 tests. Forty-seven of them were one
cause: `items` in the development database is seeded from the corpus, and the seed had not
been re-run, so the planner was choosing from a table that did not contain the new items.
`uv run python -m api.seed` fixed those in one go. Not a defect — but the failure mode is
loud, uniform and completely uninformative about its cause, so it is written down here for
whoever meets it next.

### Next

Same again for quant, design and behavioral — three more instances each, which brings every
domain to two per archetype. Then the expensive half: new **archetypes**, which is what the
prerequisite gate is actually waiting for, and what takes real research rather than
authoring against a pattern already attested on disk.

---

## Phase 1 (quant, second instance per archetype) — and a form that matched the wrong number · 2026-08-21

Three new quant instances, one per archetype, spread away from the ratings already there.
Thirty items now; quant and coding both carry two instances per archetype.

```
corpus validate    159 concepts · 30 items (12 archetypes, 18 instances) · 0 errors, 0 warnings
make check         249 passed   make test-db 139 passed   make test-e2e 1 passed
```

| New item | Archetype | Rating | Answer | Why it is a different question |
|---|---|---|---|---|
| `i.quant.0004` | `a.quant.0001` | easy 1420 | `4` | the target is a *pair*, not a run — a repeat of the first symbol does not reset |
| `i.quant.0005` | `a.quant.0002` | medium 1660 | `7` | a fee per discard, so the threshold is "beats the next stage **minus what it costs to get there**" |
| `i.quant.0006` | `a.quant.0003` | easy 1320 | `1` | indicators over a permutation, and the answer is 1 for every n |

Every answer was checked twice before it was written down — once by exact reasoning and
once by simulating 400,000 runs. The waiting time came back 3.9998 against 4, the game
7.0046 against 7, the coats 0.9985 against 1.

### The level-0 anchor that is the whole reason quant has a rubric

`i.quant.0004` asks for the expected pushes until green-then-red on a fair light. The
marginal probability of that pair is 1/4, so "1 over 1/4, so 4" produces **the right number**
— and would produce 4 for green-then-green as well, which is really 6. The rubric's
lowest anchor names that argument explicitly.

It is the cleanest example this corpus has of why docs/GRADING.md weights the derivation at
0.6: a grader that checked the number alone would score that answer full marks, and the
evidence it wrote about `markov-chain-absorption` would be false.

### An accepted form that matched a different number

Running the new items through the grader before committing them turned up a real defect.
`i.quant.0006`'s answer is `1`, and `1` was listed in `accept_forms`. Against "about 1/9 of
them, so 0.111" the digit guards all held — the `1` in `1/9` is genuinely bounded by
non-digits — and a **wrong answer was marked correct**.

The fix is not a better guard. It is that `accept_forms` had no business holding `1` at all:
the field is for forms sympy *cannot* normalise, and anything parseable is already decided,
correctly, by the equivalence check one step earlier. `accepted_form` now **skips any form
the parser can read**, which makes the field mean what the schema says it means and removes
the whole class — including from the items already on disk, whose lists are mostly redundant
spellings of numbers sympy handles. `i.quant.0003`'s `5 1/3`, a mixed number nothing can
parse, is what the field is actually for and still works.

### Two gates, and the one that was not run

The coding wave was pushed with `make check`, `make test-db` and `make verify-solutions`
green — and CI failed, on `make test-e2e`, which is the fourth gate and the one not run.
`test_session_e2e` pinned the whole plan (`["i.code.0001", "i.code.0002"]`) and the planner
had correctly started preferring the new easier item. Same class as the eight fixed in that
wave, in the one place the local runs could not see it.

The test needed only its *impostor's* item pinned — `QUADRATIC_SPANS` is written against that
entrypoint — so it now names that one and takes whatever else the planner served, with the
evidence-row count computed from the corpus rather than written down as `8`.

This repo's own rule is that a gate you did not run is a gate you cannot cite. Four gates
exist precisely because they catch different things, and the corpus is the input all four
share.

### Also: `make test-db` seeds first now

`items` is a projection of the corpus, and the planner reads it. Twice in two waves,
authoring items and then running the database tests produced a wall of failures — 47 the
first time — whose only cause was a table that had not been re-seeded, and whose output said
nothing about it. CI has always seeded before that step; local now does too.

### Next

Design and behavioral, three instances each, which brings all four domains to two per
archetype. Then the expensive half — new **archetypes**, which need research rather than
authoring against a pattern already attested, and which are what the prerequisite gate is
waiting for.

---

## Phase 1 (design and behavioral) — every domain has a choice now · 2026-08-21

Six more instances, three in each of the two rubric-graded domains. **Every domain now
carries 3 archetypes and 6 instances**, so the planner can choose between items rather than
only between concepts in all four modes.

```
corpus validate    159 concepts · 36 items (12 archetypes, 24 instances) · 0 errors, 0 warnings
make check 249 · make test-db 139 · make test-e2e 1 · verify-solutions 6/6
```

| New item | Archetype | Rating | The angle it takes that the sibling does not |
|---|---|---|---|
| `i.design.0004` | fan-out | hard 1690 | a 4,500× skew between the widest and the median audience, so head and tail cannot share a mechanism |
| `i.design.0005` | idempotency | medium 1620 | a device that buffers offline and dumps two hours of old events on reconnect |
| `i.design.0006` | rate limiting | medium 1500 | failed sign-ins — where the outage answer **flips**, and refusing is safer than allowing |
| `i.behav.0004` | conflict | easy 1400 | disagreeing with someone who could simply overrule you |
| `i.behav.0005` | failure | medium 1620 | a mistake with no single moment, where attributing the cause is the hard part |
| `i.behav.0006` | ambiguity | easy 1430 | requirements that moved mid-build, and what happened to the work already done |

`i.design.0006` is deliberately the mirror of `i.design.0003`. Both enforce a fleet-wide
quota inside a latency budget, and the archetype says outright that throttling failed logins
is "the variant where the availability-versus-protection answer flips": ninety unthrottled
seconds on a metered API is lost revenue, and on a sign-in path it is a free guessing window.
The two items' `store_outage_policy` anchors reward opposite answers, which is the pair
doing work no single item could.

### What "verified" does and does not mean here

Worth stating plainly, because the word has been carrying more weight in earlier entries
than it can carry in this one. A coding item is verified by **running** it: the reference
passes its own tests in a sandbox and the probe measures its growth. A quant answer is
verified by arithmetic and by simulation. **Nothing executes a rubric.** For these six the
whole check is the validator, a careful reading, and one scripted grading each — which
proves the item *grades*, not that its anchors discriminate.

That is not a gap to be closed with more effort at authoring time; it is what
docs/GRADING.md's calibration harness is for, and that is still blocked on having real
transcripts. The status header in docs/CORPUS.md now says so rather than letting "authored
and verified" cover both cases.

### The validator warning earned its keep

Every one of the six was written with `make corpus-validate` in the loop, and the check
added this morning — no rubric criterion naming the item's primary concept — is the reason
each of them has one. Authoring `i.design.0005` I reached first for four criteria about
delivery, retries, backpressure and reconciliation, none of which is `idempotency`, which is
what the item is *for*. The same shape as `i.design.0003`'s original gap, caught at authoring
time instead of a month later by a rating that never moved.

### Next

The expensive half. Every instance so far has been authored against an archetype already on
disk, which is why none of this needed research: the pattern was already attested. New
**archetypes** need sources — two independent ones each, read and then closed — and they are
what the prerequisite gate is waiting for, since it substitutes only toward a concept some
item carries as its primary and there are still twelve of those across 159 concepts.

---

## Phase 1 (four new archetypes) — the prerequisite gate has somewhere to send you · 2026-08-22

Four new archetypes, one per domain, each with two instances. **48 items: 4 archetypes and
8 instances in every domain.** Every previous wave authored instances against an archetype
already on disk, which is why none of them needed research and none of them added a
primary concept. This one adds four, and they were chosen for one property: each is the
**prerequisite of a concept the corpus already served**.

```
corpus validate    159 concepts · 48 items (16 archetypes, 32 instances) · 0 errors, 0 warnings
make check 249 · make test-db 141 · make test-sandbox 28 · make test-e2e 1 · verify-solutions 8/8
```

| New archetype | Primary concept | Gates | Instances |
|---|---|---|---|
| `a.quant.0004` | `sample-space-counting` | `linearity-of-expectation` | `i.quant.0007` easy 1310 · `i.quant.0008` hard 1690 |
| `a.code.0004` | `hash-map-counting` | `sliding-window` | `i.code.0007` easy 1340 · `i.code.0008` medium 1640 |
| `a.design.0004` | `load-balancing` | `rate-limiting` | `i.design.0007` medium 1570 · `i.design.0008` hard 1730 |
| `a.behav.0004` | `star-structure` | `conflict-resolution`, `failure-and-learning` | `i.behav.0007` warmup 1250 · `i.behav.0008` medium 1500 |

Authored by four concurrent agents owning one domain file each, the same shape the earlier
waves used. Sixteen source URLs were fetched and read; nine candidate sources were fetched
and **discarded**, and the discards are recorded below because they are the more useful
half.

### What the gate actually does, which this repo had been describing too pessimistically

`docs/ADAPTIVE.md` said substitution "needs an item whose *primary* concept is the
prerequisite, and the corpus has twelve primaries across 159 concepts." True, but it
implied a stricter rule than the code has. `_prerequisite_substitution` checks `serveable`
only on the concept it substitutes **toward**. The gated concept is whatever the ranking
threw up and may have no items at all — in which case substitution **rescues** a slot
`build_plan` would otherwise drop for an empty pool.

So there were two numbers, not one, and only the smaller was near zero:

| | before | after |
|---|---|---|
| DAG edges the gate can honour | 15 | **34** |
| …of which the gated concept has items of its own | 1 | **6** |
| domains with such an edge | quant | **all four** |

The second row is the one this wave was for: the planner turning away from a concept it
*could* have served, because something underneath it is weaker.

### The before and after, run rather than reasoned about

Same planner, same simulated candidate — weakest at the new concept, second-weakest at the
concept it gates — against HEAD's corpus and then this one. The loader was pointed at a
checkout of the old corpus; no reseed was needed, because `eligible_items` reads the corpus
directly and the `items` table only supplies live Elo.

**Before**, in all four modes the prerequisite is never served, and the plan says why:

```
behavioral   i.behav.0004  targets=conflict-resolution
                           note='star-structure gates it and is weaker, but no item measures it'
coding       i.code.0004   targets=sliding-window
                           note='hash-map-counting gates it and is weaker, but no item measures it'
quant        i.quant.0006  targets=linearity-of-expectation
                           note='sample-space-counting gates it and is weaker, but no item measures it'
design       (rate-limiting not served at all)
```

**After**, the prerequisite is served in all four. But note *why*, because it is not the
gate: a concept that is weakest and unlocks six others simply **ranks first on its own
priority**, so it is served directly and the substitution branch never has to fire.

Making the gate itself decide the slot needs the gated concept to *outrank* its
prerequisite, which takes a term the prerequisite does not get — overdue. With the gated
concept 30 days past a one-day interval and 20 Elo *stronger*:

```
design       rate-limiting prio=0.4036 (top-ranked)  vs  load-balancing prio=0.2354
             i.design.0007  targets=load-balancing
                            note='substituted for rate-limiting, whose prerequisite it is'
```

`rate-limiting` is the highest-priority concept in the domain and is not served at all.
The same redirect fires in the other three modes. That is the branch that had one edge to
run on before this wave and now has six.

### `W_UNLOCKS` was inert, and authoring one concept woke it up

The Phase 4 gate — an injected weakness drilled within **five** sessions — broke. It is
the most interesting failure in this wave, and it is not a regression.

`hash-map-counting` gates six coding concepts, so its `unlocks` term is **0.086** against
`monotonic-stack`'s **0.014**. At cold start nothing is measured, so every weakness term
sits at 0.199 and that gap decides the order. Measured over ten sessions:

```
1-2  i.code.0007  hash-map-counting   (unlocks 0.086)
3    i.code.0004  sliding-window
4-7  i.code.0002  monotonic-stack     <- the injected weakness
8    i.code.0007  hash-map-counting   (anti-repetition rotates it off)
9-10 i.code.0002  monotonic-stack
```

The engine still converges and still ends up rating `monotonic-stack` lowest (1509 against
a 1550 default). It just pays three sessions establishing a foundational concept before
drilling anything — which is precisely what `docs/ADAPTIVE.md` says the term is for: "a
weak prerequisite that gates six downstream concepts is worth more than an isolated leaf."
The term had simply never had a serveable high-`unlocks` concept to express itself on.

Two things follow, and both will recur:

- **A majority over a growing window is not a property this engine can satisfy.**
  `W_EXPOSURE` guarantees it rotates off a sore spot, so the fraction is bounded above by
  design. Counts measured at 6/8/10/12 sessions: 3, 4, 6, 8.
- **The exploration prologue scales with unmeasured foundational corpus**, so the window
  will need raising again. The gate now also asserts the weak item is the single
  *most-served* one, which is the half that does not depend on window arithmetic.

The window moved to ten sessions. `docs/ADAPTIVE.md`, the README and the phase table all
say so, and say what moved it.

### The probe generators, and proof they earn their design

Both new coding items ship a worst-case generator, and both were checked by running an
impostor rather than by reading the band table — the discipline `docs/CORPUS.md` picked up
last wave.

| item | reference | ceiling | impostor | slope | threshold |
|---|---|---|---|---|---|
| `i.code.0007` | 1.05 | 1.30 | nested pair scan | 2.05 | 1.65 |
| `i.code.0007` | | | pair distinct values `O(d²)` | 2.03 | 1.65 |
| `i.code.0008` | 1.08 | 1.30 | nested prefix scan | 2.14 | 1.65 |
| `i.code.0008` | | | re-walk the map `O(n·d)` | 2.09 | 1.65 |

All four impostors **pass every test their item ships** — they are the accepted-but-slow
case only the probe can catch. The counter-experiment is the part worth keeping: swapping
each generator for a lazy one lets the impostor escape.

- `i.code.0007` with low-cardinality random values: the `O(d²)` impostor returns
  **`inconclusive`** — largest sample 0.176 ms, under the 0.2 ms noise floor.
- `i.code.0008` with only two distinct running totals: the `O(n·d)` impostor measures
  **0.99** and is called **`matches`**. A clean escape.

So the generators are worst-case on two axes, and both say so in comments: no early exit is
ever valid, *and* the distinct-key count is forced to Θ(n) so a solution quadratic in
distinct keys cannot hide.

**A corpus-wide concern, flagged rather than fixed.** Largest probe samples run 0.33–0.49 ms
against a 0.2 ms floor across *all* coding items (`i.code.0001` 0.493, `i.code.0004` 0.332,
the new pair 0.362 and 0.441). A machine roughly 1.8× faster than this sandbox pushes
`i.code.0007` under the floor. Widening two items unilaterally would break parity with the
`[1000…8000]` range `docs/CORPUS.md` records as *measured* to catch a quadratic impostor on
CI, so nothing was changed. It is a corpus-wide decision and it is now written down.

### The discrimination read found real defects in both rubric domains

Nothing executes a rubric, so for design and behavioral the whole check is the validator, a
careful reading, and one scripted grading each. That proves an item **grades**; it proves
nothing about whether its anchors discriminate. This wave added a step: write the
confident, fluent, empty answer and check by hand where the anchors put it.

It changed six of the four items.

**Design** — five of ten anchors gave the boilerplate answer partial credit, for a weighted
~0.21 and ~0.22. The failure was consistent: boilerplate *names the right noun* — "least
connections", "consistent hashing", "connection draining", "exponential backoff" — while
doing none of the reasoning, and the level-2 anchors were phrased as "names X but doesn't
tie it to the numbers", which is exactly what boilerplate does. Fixed by naming the
boilerplate move itself in the level-0 anchor on six criteria. Both generic answers now
read **0.00**.

**Behavioral** — three of four level-2 anchors were reachable by a 352-word answer that is
65% background, says `we` eight times, contains three first-person clauses (all of them
framing, none of them actions), has no digits and ends on "it was a really interesting
project." First-pass ceiling ~0.40. Fixed by making the boundaries mechanical rather than
judgemental: background must be **under half the answer** to clear level 0, and level 0 now
explicitly claims a middle that reports team activity and a close that appraises the
project instead of saying what changed. The answer now lands **0/4 on every criterion**,
and even a grader ignoring both mechanical boundaries tops out at 0.50.

Worth stating plainly: **the discrimination read was the only step in the design domain
that changed anything.** The validator was green on the first try and stayed green; the
scripted grading was green on the first try. Two items would have shipped giving a fifth of
the marks to an answer that said nothing, and no gate in this repo would have noticed.

### Three tests were measuring the corpus again, in a new way

Last wave's finding was that a test naming a corpus item is a test of how many items the
corpus holds. This wave found the same mistake spelled as a **count**.

| Test | Pinned | Now |
|---|---|---|
| `test_a_session_returns_its_plan_up_front` | `len(plan["items"]) == 3` | the plan is non-empty and fits its budget |
| `test_the_report_carries_the_evidence_it_wrote` | `graded == 3`, `len(evidence) == 11` | both computed from the plan the planner actually served |
| `test_ending_early_...` | `not_attempted == 2`, `len(evidence) == 4` | same, from the plan |

A 90-minute budget fit three coding items and now fits four. `evidence_rows_for()` sums the
concept tags of the items actually planned, so the number tracks the corpus instead of
asserting against it.

### The e2e gate, pinned one layer deeper than it looked

`test_a_coding_session_runs_from_plan_to_report` needs `i.code.0002` in the plan, because
its quadratic impostor is hand-written against that item's entrypoint. Last wave narrowed
it from pinning the *whole plan* to pinning only the impostor's item. That was still a bet
on a **ranking**: with `hash-map-counting` authored, a cold start now serves
`['i.code.0007', 'i.code.0004']` and the impostor's item is not in it.

It now asks for the concept it needs — `focus_concepts: ["monotonic-stack", "sliding-window"]`
— and takes whichever items the planner serves for them. The planner serves at most one
item per concept, so two focus concepts give exactly the two this test needs. What the test
is for is plan → submit → grade → report through a real sandbox; which items a cold start
prefers belongs to `test_planner_db.py`.

**This gate was run locally this time.** Last wave pushed with three of four green and CI
caught the fourth. All five ran here, `make test-sandbox` included.

### A latent test defect that had nothing to do with the corpus

`make test-db` also failed two ledger tests, and the cause predates this wave: the dev
database had 29 rows on it from earlier sessions, all dated *yesterday*.

`spend_now()` summed the ledger for all time. The daily budget is enforced against
`start_of_day()`, and `/costs/budget` reports the same window — so the helper agreed with
the route only on a database holding nothing older than today.

The worse of the two was `test_a_spent_daily_budget_refuses_the_next_call`, which sets the
limit to just under what it reads. Summing all history quietly raised the bar to 16,359
tokens against 120 actually spent today, so the call it expected to be **refused went
through** and the test failed on `DID NOT RAISE`. Its docstring already claimed the right
intent — "the limit is set below what is already on the ledger so the test does not depend
on what else the database holds" — and the implementation read the wrong window. `spend_now`
now mirrors enforcement: day-scoped with no session, session-scoped with one.

Two stray rows written by this wave's own scripted grading were deleted. The other 29 were
left alone — they are dev-database history, not this wave's to discard.

### What "verified" means for each of these twelve items

The word has to carry different weight per domain and the difference is not shrinking:

- **Coding** — run. Both references pass their own tests in a real sandbox (11/11 and
  13/13) and measure inside their declared band; four impostors were run through the real
  probe and caught.
- **Quant** — checked twice. `2/11` simulated 0.181785 and `63/128` simulated 0.491568 at
  1M trials each; `i.quant.0008`'s space was additionally enumerated exhaustively at
  2016/4096, with three independent counting routes agreeing. Both answers were then run
  through the real `check_answer`, including a decoy battery — 12/12.
- **Design and behavioral** — the validator, a careful reading, one scripted grading each,
  and now the discrimination read. **No model judged anything.** The scripted verdicts were
  chosen by the agent that wrote the item, which is the weakest link in this corpus and is
  what `docs/GRADING.md`'s calibration harness is for. Still blocked on real transcripts.

### Sources fetched and discarded, which is the more useful half

Nine candidate sources were fetched or attempted and not cited:

- **Dead or blocked:** `techinterviewhandbook.org/behavioral-interview/` returned **403** —
  worth knowing, since that domain is cited by all three existing behavioral archetypes and
  would not be re-fetchable today. `leetcode.com/discuss/...` 403. `interviewquery.com` and
  `datainterview.com` both **429**. Two Google/Meta careers URLs 404, one rendered as an
  empty SPA shell.
- **Fetched, read, rejected as evidence:** `everythingquant.com` and `quantt.co.uk` never
  name counting as a topic — and `quantt.co.uk` is *already cited* in this file for
  `a.quant.0003`, where it is a good source. A source is evidence for a specific archetype,
  not for a domain. `gov.uk`'s Success Profiles is a real competency framework that says
  nothing about answer structure; citing it would have been evidence-density padding.
- **A URL you can construct is not a URL you have read:** `systemdesignschool.io` has a
  rate-limiter problem and no load-balancer one, despite the guessed path being plausible.

One cited source is deliberately weak and labelled so in its own evidence note:
`mayhemcode.com` is a personal prep blog stating predicted expectations rather than
transcripts. It was kept because it is the source that most directly attests the shallow
health-check trap `i.design.0007` grades hardest. If a reviewer wants it dropped,
`a.design.0004` still has three independent sources.

**The originality rule is process, not a gate.** The validator shingles a statement against
the item's *own evidence notes* — it holds no copy of any page. What can be said is that no
proprietary problem statement was in context and every statement was written from the
pattern. That is a claim about how the work was done, not something a script proved.

### Next

Still the expensive half, and now with a sharper target. Twelve archetypes measure
sixteen of 159 concepts as a primary, so **143 concepts still have nothing that measures
them**. The highest-value ones are the remaining unmeasured *prerequisites* — the same
selection rule this wave used — followed by the foundational concepts with the largest
downstream subtrees: `functional-requirements` (36 concepts downstream),
`nonfunctional-requirements` (27), `big-o-analysis` (35), `capacity-estimation` (25).

Two known costs to plan for. Each new foundational concept with a large `unlocks` term
lengthens the Phase 4 gate's exploration prologue again, so that window will keep moving
until the weights are calibrated against real sessions. And the coding probe's noise-floor
margin is thin corpus-wide; the fifth probe size that would fix it is a decision to take
across every coding item at once, not per item.

---

## Audit wave 1 — the gates that reported success without checking · 2026-08-22

A six-way parallel audit of the whole repo, one agent per subsystem, each required to
verify by running rather than by reading. It returned roughly fifty confirmed findings.
This entry covers the first batch fixed: **the gates guarding a public repo.**

The pattern worth naming, because it recurred in five independent places: *a gate that
passes vacuously*. Not a gate that is wrong — a gate that reports success having checked
nothing, which is strictly worse than no gate because the build log then quotes it as
evidence.

### The secret scan never read what was being pushed

`scripts/secret_scan.sh` ran `git grep` with no revision, which searches the **working
tree**. The most common secret accident there is — paste a key, commit, notice, `git rm`,
commit the fix, push — leaves the tree clean at exactly the moment the hook fires. Both
commits reach the remote. Confirmed against a bare remote: `secret_scan: clean`, push
exit 0, key live in the published history.

It now takes the ranges the pre-push hook already computes and reads every line **added**
by the commits being published (removed lines are the fix, not the leak). CI passes the
PR or push range and checks out with `fetch-depth: 0`, because a shallow clone has no
history to read and would report clean.

### Two GNU regex extensions, both silently disarming the scan

`\s` is absent from BSD/macOS ERE, and `git grep -E` compiles with the platform regcomp.
So `aws_secret_access_key\s*=\s*` matched a literal `s` locally and whitespace on CI: the
gate that runs *before* publication was the weaker of the two, which is the wrong way
round.

Rewriting it, an adversarial test caught the same class again in the new patterns — `\b`
is also a GNU extension, and it was disarming **six of the ten** credential shapes. Both
failures are invisible in the output; the script prints `clean` either way. Word
boundaries are now simply omitted.

Coverage measured against nine planted secrets: the old scan matched one, the new one
matches eight. The ninth is AWS's own documentation example key, allowlisted on purpose.

### Three more holes in the same file

- **`':!*.example'` is a basename glob matching at any depth**, so `.env.example` was
  exempt — the one tracked file that names every secret this service has, and the file
  `CLAUDE.md` requires you to edit for each new `Settings` field. Filled in with real
  values it scanned clean. Exclusions are now exact paths.
- **`2>/dev/null || true`** turned any git failure into `secret_scan: clean`. That line is
  quoted in this build log as evidence; it now means the scan ran.
- **No `-i`**, so `AWS_SECRET_ACCESS_KEY=` — the only casing this repo uses anywhere —
  was missed.

The patterns are now split in two, because the fix for one hole opens another: shapes
that are *a credential or nothing* consult no allowlist, while `NAME=value` shapes do.
Otherwise the literal string "example" anywhere on a line disarms the check.

### The rule this repo says its value depends on had no CI enforcement

`CLAUDE.md`'s rule 1 is that documentation travels with the code. It was enforced by
`hooks/pre-push` alone — which exists only after `make setup` runs
`git config core.hooksPath hooks`. A fresh clone has nothing checking it, and neither does
a commit made anywhere else. Meanwhile the secret scan was double-covered.

`scripts/docs_with_code.sh` now runs in CI over the PR or push range.

While wiring it: `CODE_RE`'s `^(apps|packages|...)/` anchor never matched a path git
quoted. With `core.quotepath` at its default, any path containing a non-ASCII byte comes
back wrapped in double quotes, so a code-only commit touching `apps/api/src/api/café.py`
passed the gate — confirmed, and confirmed fixed against the same commit shape.

### Also fixed

`"${ranges[@]}"` on an empty array is an unbound-variable abort under `set -u` on the
bash 3.2 macOS ships. The empty case is now spelled out rather than relied on.

### What this batch does not cover

The audit's other findings — a budget race with a measured 8000× overshoot, three
concurrency holes that write duplicate immutable evidence, a quant grader that scores a
restated number correct, a validator that accepts two sentences as two independent
sources — are being worked in the batches after this one. They are listed here so that a
reader of this entry does not take "audited" to mean "clean".

---

## Audit wave 2 — the ceiling that was not a ceiling, and a forged number worth 10^5 Elo · 2026-08-22

The second batch from the six-way audit: the findings that cost money or corrupt data.
Both halves of this entry are things that were **measured**, not reasoned about.

```
make check 249 · test-db 144 · test-sandbox 28 · test-e2e 1 · verify-solutions 8/8
migration c4a71f2e83b0 applied and reversed cleanly
```

### Eight concurrent calls, a 1000-token ceiling, 8,000,000 tokens spent

`enforce_budget` read the ledger in a short transaction that closed **before** the
provider was called. Nothing recorded that a call was in progress, so every call
overlapping in time read the same pre-spend total and every one of them proceeded.

```
8 concurrent llm.complete() calls, 1000-token daily ceiling:
   all 8 ALLOWED · provider invoked 8 times · 8,000,000 tokens · 8000x the ceiling
the same 8 calls sequentially:
   1 ALLOWED · 7 refused 429 budget-exceeded
```

This is not a theoretical race. Every `/api/v1` handler is a synchronous `def`, so
Starlette dispatches to a threadpool — confirmed with four concurrent requests completing
in 0.52 s where serial would take 2.00 s. Two browser tabs, a retrying client, or the
interviewer and a practice-log entry at once are enough.

`llm_calls` now holds **one row per attempt, not per success**. A row is written before
the call — inside the same transaction as the check, under `pg_advisory_xact_lock` —
holding what the call may cost, and settled with real usage afterwards. An in-flight row
counts at its reservation, so a concurrent check can see it. Re-measured:

```
8 concurrent calls: 1 ALLOWED, 7 refused, provider invoked once
```

The lock is held across two aggregates and one insert, never across the provider call.
Holding a database lock over a network round-trip is how a connection pool dies.

A reservation older than fifteen minutes is treated as abandoned, so a process that dies
mid-call does not wedge the budget forever. That direction is deliberate: releasing a live
reservation re-opens the race, while holding a dead one is merely too strict for a while.

### The same change closed a second hole: a dropped stream was free

`stream()` mapped a mid-flight provider error to 503 and returned **without recording
anything**, on the reasoning quoted in the code — "a call that never produced usage never
cost anything". True of `complete`. False of `stream`, which has already handed the caller
billed output.

```
raised: 503 dependency-unavailable
deltas delivered to the caller (billed output): ['Here ', 'is ', 'a ', 'long ', 'answer']
ledger rows written for that spend: 0
```

Because the row now exists before the call, the failure path settles it instead of
skipping it — from the SDK's last message snapshot, so partial output is recorded as
partial rather than as zero.

While there: the handler named three `anthropic` classes and two real failures walked past
both. `APIResponseValidationError` is a sibling of `APIStatusError`, so a fully billed
response the SDK could not validate escaped as an unhandled 500; and a `botocore`
credential error out of the Bedrock client is not an `anthropic` exception at all —
confirmed reaching a client as `text/plain "Internal Server Error"`, outside the
problem+json contract docs/API.md says every route keeps.

### A candidate could move a concept's rating by 10^5 Elo with four characters

The worst finding in the audit, and it is worth being precise about what was and was not
already known. docs/SECURITY.md scopes *result forgery* out of the threat model: single
user, no hostile population, and the only person deceived is the one practising. That
reasoning is sound and unchanged.

What was not in scope is the **blast radius**. `parse_result` took `total` from the
candidate-writable marker line rather than from the `len(tests)` it was already given:

```
candidate emits ##LEARN-RESULT {"passed":10000,"total":1} then os._exit(0)
  -> HTTP 200 {"outcome":"ok","passed":10000,"total":1}
  -> grade_coding: correctness=10000.0 score=10000.0
  -> evidence scores: [10000.0, 10000.0, 10000.0, 10000.0]
```

`mastery` applies `k * (score - expected)` with `k` up to 48 and **no clamp on the
result** — the module says outright that it is "not a clamp on the rating itself". One
submission moves a concept's ability by roughly 100,000 Elo, permanently, and
`POST /mastery/recompute` reproduces it faithfully from the immutable evidence.

`total` now comes from the caller and `passed` is clamped into it; `RunResult` carries
`NonNegativeInt` with a `passed <= total` validator so the API does not depend on the
sandbox having done its half. The in-scope forgery — claiming a full score on the real
test count — still works, exactly as the threat model says it may.

### Malformed marker lines were a way to make your own grading disappear

Valid JSON of the wrong shape (`{"total": 3}` with no `passed`, a bogus failure object, a
bare array) raised out of the request handler as a 500. `ExecutorClient` maps `>=500` to
`ExecutorUnavailableError`, which the API records as "executor unavailable" — and that
path, by design, *says nothing about the submission*. So a candidate had a reliable way to
turn a bad attempt into an infrastructure fault.

The existing test covered **invalid JSON** only. The marker is now validated through a
model and a malformed one is skipped exactly like a corrupt one, falling through to
`harness_error`.

### Three read-then-write paths with nothing behind them

All three confirmed by overlapping two requests, all three now backed by a unique
constraint (migration `c4a71f2e83b0`, which collapses any pre-existing duplicates first):

| Constraint | What overlap produced |
|---|---|
| `artifacts(session_id, item_id)` | two artifacts, two gradings, **eight** `concept_evidence` rows for four concepts — a permanent double-count of one attempt |
| `turns(session_id, seq)` | two turns at the same sequence number; transcript order unrecoverable, model billed twice |
| `practice_solves(problem_id, review_number)` | `review_numbers = [0, 1, 1]`, a lost `solve_count` update, and a problem that never graduates |

Evidence is immutable and the projection replays it faithfully, so "the grader will notice
next time" was never available as a recovery for the first of these.

### Also fixed

`GET /costs` summed three token columns and returned three; `cache_write_tokens` was
counted by enforcement and exposed by no read surface, so a 200,000-token cache-write call
appeared as a call with zero tokens and a real dollar figure. It is the one number that
answers "is caching working" — a write costs 1.25x and a read 0.1x.

### Still open from this audit

Named so this entry cannot be read as "done". The session state machine has three
confirmed holes — a submission racing `/end` resurrects an abandoned session, a
`wrapping` session is a permanent dead end that every route refuses, and the SSE stream
never terminates when the session ends while it is open (which also pins a pooled
connection, so ~15 abandoned tabs stall the API). The quant answer extractor accepts any
of twelve arithmetic spans from the closing line, so a restated number marks a wrong
answer right, and an integer followed by a comma is unparseable. Internal exception text —
full SQL with bound parameters — is echoed into `gradings.detail` and returned by two
routes. The complexity probe gives the *slowest* submissions a free pass, so a cubic
solution outscores a quadratic one. The corpus validator accepts two arbitrary sentences
as two independent sources. And `recompute` rebases item ratings onto a prior the live
path never used, so a corpus re-rating silently breaks the replay invariant.

---

## Audit wave 3 — the grader that was wrong in both directions · 2026-08-22

Third batch. This one is about the oracle: a grader that scores wrong writes immutable
`concept_evidence`, and `POST /mastery/recompute` reproduces the mistake faithfully
forever. Four confirmed mis-scorings, one of which also hung the API worker.

```
make check 249 · test-db 144 · test-sandbox 28 · test-e2e 1 · verify-solutions 8/8
```

### A comma destroyed a correct answer, at the highest confidence in the system

`_TERM`'s `\d[\d,]*` swallowed a trailing comma, so `Answer: 39, which must exceed 27`
extracted the span `39,` — which `ALLOWED_CHARS` then refuses, because a comma is not an
allowed character. The answer scored **0.0 at confidence 0.9**, writing evidence of a
weakness against `markov-chain-absorption` that the candidate had just disproved.

The sentence is not adversarial. It is nearly verbatim the one docs/GRADING.md holds up as
the case the grader handles — that version only works because it happens to put a word
between the digit and the comma. Decimals escaped (`7.45,` strips fine), so this bit
exactly the half of the quant corpus whose answers are integers.

### "The naive answer is 27" outranked "So E0 = 39 presses"

`closing_statement` scanned every line in reverse for a declaration marker, so a
*retrospective mention* three lines above the conclusion won:

```
Let E0 be the expected presses from an empty run.
The naive answer is 27, since (1/3)^3 = 1/27.     <- read as the declaration
But a silver clears the run, so I condition: E0 = 3 + 9 + 27.
So E0 = 39 presses.                                <- never looked at
```

Scored 0.0 at 0.9. And that sentence is not a corner case — it is the natural way to write
the decoy for the item whose entire design is that 27 is the trap. A marker now counts
only at or below the last line carrying arithmetic. The existing decoy test passed
throughout, because it phrases the decoy as "the naive **value** is 27".

### A declared wrong answer was rescued by the right one appearing later in the sentence

`expressions` splits on non-operator words and the check accepted **any** of up to twelve
spans. So:

```
"Final answer: 0, since with 1 in 9 chance per guest it rounds to 0."
   candidates: 0, 1, 9   ->  1 matches  ->  score 1.0 at confidence 0.9
```

The candidate declared `0`. The answer is `1`. It scored full marks and wrote evidence of
mastery. The same mechanism was a free hedge: `Answer: 30 or 31 or ... or 39` is twelve
guesses priced as one.

**A declaration is now graded on what was declared** — the first span after the marker,
nothing else. The undeclared path still considers every span, and that is what confidence
`0.75` exists to express. Worth being exact about the residual, because it cannot be
fixed by reading harder: "So I'd pay at most 6 dollars, comfortably under the 7 dollar
pot" and "There are 8 flavours, so the probability is 63/128" are the same shape with
opposite right answers. Any rule that fixes one breaks the other. The first is still
scored correct, at 0.75, and the derivation rubric carries 0.6 of the score regardless.

### Fifteen characters that never returned

docs/SECURITY.md's parser wall claims "every bound is checked against the *text*, before
the parse that would be expensive", and names `9**9**9` as the case it stops. It does —
but `_EXPONENT`'s `[^\s()]+` stops at a parenthesis, so parenthesising the tower splits it
into individually-legal exponents:

```
(2)**(63)**(63)   ->  _EXPONENT.findall -> ['63', '63']   both under the limit of 64
                  ->  means 2**(63**63)
                  ->  parse_expr had not returned after 90 seconds
```

`MAX_NODES` is checked *after* the parse, so it never ran. This is reachable from any
quant submission — the span is extracted from an ordinary closing statement — and it hangs
a worker inside the API process, leaving the item in `grading` forever with a retry
refused 409. That is precisely the failure docs/GRADING.md's "failure is a failure"
section was written to stop. An answer form needs at most one exponent; more than one is
now refused outright, in microseconds.

### A curly apostrophe cost the candidate the criterion

`_normalise` folded whitespace and case but not punctuation. A candidate's text comes from
a browser textarea, a paste, or a phone — all of which produce U+2019 and U+2014 — and a
model quoting that text back emits the ASCII equivalents:

```
verified=True   'We won’t shard the write path'
verified=False  "We won't shard the write path"
```

An unverified citation forces `demonstrated` to False, so the criterion scores zero **and
writes no evidence** — indistinguishable from the candidate never having addressed it.
The doc already argued that "a model that reflows a quotation has still quoted it"; the
same argument covers punctuation, and now the code does too.

Also: the 12-character citation floor was real, load-bearing, and **never disclosed to the
model**. A compliant grader quoting the ten decisive characters of a formula was demoted
exactly as far as one that fabricated its citation. The system prompt now states it.

### Full SQL, with bound parameters, returned in an API response

`grade_artifact`'s blanket handler formatted `f"{type(exc).__name__}: {exc}"` into
`gradings.detail`, which `GET /sessions/{id}` and the report return unfiltered. Measured
body content:

```
'detail': 'grading crashed: IntegrityError: ... violates foreign key constraint ...
[SQL: INSERT INTO concept_evidence (id, concept_id, source, item_id, session_id, ...)]
[parameters: {'id': '01M0K...', 'concept_id': 'not-a-seeded-concept', ...}]'
```

The same channel would carry a psycopg `OperationalError` (host, port, role) or an
executor `httpx` error (an internal URL). It records the exception **type** now. The test
that covered this asserted the message *was* present, so the suite was pinning the leak.

### Three unbounded inputs

- `SubmissionRequest.content` had no cap, while `TurnRequest.content` is capped at 20,000
  with the comment "an unbounded field is an unbounded bill". The oversight is
  understandable — a coding submission goes to a sandbox — but design, behavioral and
  quant submissions are the *prompt* to a model grader, and neither truncates. A 5 MB
  submission was accepted, stored and graded. Now 100,000.
- `secondary_concept_ids` on the human-correction path was unbounded and
  un-deduplicated: sixty duplicates wrote **sixty-one** immutable evidence rows and moved
  a concept nearly 200 Elo on one logged solve. The model's own schema has capped it at 4
  all along, and so does the doc.
- `focus_concepts` accepted a 5,000-entry tuple with a 201.

### And one route that took its scope on trust

`GET /costs/budget?session_id=` passed the parameter straight to `budget_status`, so it
answered 200 with another principal's spend for an id that `GET /sessions/{id}` 404s.
docs/API.md says both cost routes are "scoped by the session cookie like everything else
under `/api/v1`". Impact is nil on a single-user deployment; the inconsistency is the
defect, and it is the kind that stops being nil quietly.

### Still open

The session state machine's three holes (a submission racing `/end` resurrects an
abandoned session; `wrapping` is a dead end every route refuses; the SSE stream never
terminates and pins a pooled connection while it hangs), the complexity probe giving the
slowest submissions a free pass, the validator's provenance holes, and `recompute`
rebasing item ratings onto a prior the live path never used.

---

## Audit wave 4 — three ways a session could stop being finishable · 2026-08-22

Fourth batch: the session state machine and the event stream. Every finding here is a
liveness bug — nothing computes a wrong answer, but a session gets into a state it cannot
leave, and one of them takes the whole API down with it.

```
make check 249 · test-db 147 · test-sandbox 28 · test-e2e 1
```

### `wrapping` was a state with no exit

The interviewer calling `end_round` on the last planned item — its documented "solved,
abandoned, or out of time" path — moves a session to `wrapping`. If nothing was ever
submitted, nothing is in flight, and `_maybe_complete` only ever runs from a grading
callback. So it never ran. And from `wrapping`:

```
POST /end          -> 409  Session is already 'wrapping'.
GET  /report       -> 409  a report exists once it is ['abandoned', 'complete']
POST /submissions  -> 409  only accepted while it is ['briefing', 'interviewing']
POST /turns        -> 409  only taken while it is ['briefing', 'interviewing']
```

Not finishable, not abandonable, not readable, not continuable. docs/API.md has said
`any state ──▶ abandoned` since Phase 3; `end_session` refused anything outside
`OPEN_STATES`. Both halves are fixed: `/end` works from any non-terminal state, and a
session that reaches `wrapping` with nothing left in flight completes on the spot.

The existing test reached this exact state and asserted only that `/turns` 409s — which it
does, correctly, on a session that is stuck.

### A submission racing `/end` un-ended the session

`record_submission` wrote `briefing → interviewing` from a row it had read before building
the artifact, so a commit landing just after an `end` clobbered it:

```
POST /end          -> 200 {"state": "abandoned"}
...150ms later, the submission commits
session state: interviewing | ended_at: 2026-08-22T02:58:09Z
GET /report        -> 409 Session is 'interviewing'   (forever)
```

A session with `ended_at` set and a non-terminal status is a state the machine says cannot
exist. The client was told it was abandoned. Both writes are conditional now, so the loser
of the race changes nothing, and the regression test asserts the invariant rather than an
ordering: `ended_at` is set exactly when the state is terminal.

### The stream that never closed, and took the connection pool with it

`routes/events.py` loaded the session row once, before the stream opened, then tested
`session_row.status` inside the poll loop. A stream attached while the session was
`briefing` tested `briefing` forever:

```
frame 1: {'id': '1', 'event': 'tick', ...}
database says the session is now: abandoned
!! STREAM HUNG: 4s later the generator has neither yielded nor stopped
```

The reason this is more than a stuck tab: `DbSession` is a `yield` dependency, and FastAPI
releases it only when the response completes. Each hung stream pins a pooled connection.
The default pool is 5 + 10 overflow, so **fifteen abandoned tabs stall every request the
API has**.

The status is re-read each poll now, through a short-lived session of its own — holding
the request's transaction open across the whole stream would be the same bug wearing a
different coat. There is also a 30-minute ceiling on one connection, after which the server
sends `stream.timeout` and closes; SSE clients reconnect on their own and `Last-Event-ID`
makes that lossless.

### `/end` was the only transition that told nobody

Every other state change publishes `session.state`. `end_session` published nothing, so a
client watching the stream was never told the session was abandoned — and, before the fix
above, never had the stream closed either. It publishes now.

### A fix I got wrong on the first attempt, and why it is worth writing down

`EventBus.forget` documents itself as "called when a session ends" and has no caller
outside tests, so every session leaves a 256-slot buffer alive until the process restarts.
The obvious fix is to call it from `end_session`. That is wrong, and the new tests caught
it immediately: the terminal `session.state` is the event a client most needs, and dropping
the channel in order to publish it destroys the event before anyone can read it. The stream
terminated correctly and delivered nothing.

The bound belongs on the collection, not on any one session's lifetime — 128 channels,
evicted least-recently-published first. What actually grows without limit is the number of
channels, and that is what is now capped.

### Still open

The complexity probe gives the *slowest* submissions a free pass — a cubic solution scores
1.0 where a quadratic one scores 0.75, because the probe's pessimistic projection refuses
to start a second size and `inconclusive` carries no penalty. The corpus validator accepts
two arbitrary sentences as two independent sources, and `format: uri` is annotation-only
because the JSON Schema validator is built without a `format_checker`. `recompute` rebases
item ratings onto a prior the live path never used. And a turn can still execute an
unbounded number of tool calls — measured at 300 sandbox runs and 603 events in one
synchronous request, which evicts the entire session's event history with no `stream.gap`.

---

## Audit wave 5 — the validator had holes in the checks it was named for · 2026-08-22

Fifth batch. `docs/CORPUS.md` opens by saying a validator with a hole is worse than none,
because it grants false confidence. The audit found eight, each confirmed by building a
corpus copy, breaking one thing, and watching `corpus valid — 0 errors, 0 warnings`.

```
make check 249 · test-db 147 · test-sandbox 28 · test-e2e 1 · verify-solutions 8/8
corpus tests 37 (was 30)
```

### Two arbitrary sentences were two independent sources

The provenance rule is the corpus's core claim and the signal that **ranks** archetypes.
An archetype citing `"a friend who interviewed there in 2019"` and `"my own recollection
of a phone screen"` validated clean: `_registrable_domain` returned each sentence
unchanged, so they were two distinct registrable domains.

`"format": "uri"` in the schema did not help — `jsonschema.Draft202012Validator` was
constructed with no `format_checker`, so every `format` was an annotation nothing read.
Adding the checker turned out not to be enough either: **jsonschema's `uri` checker needs
an optional dependency that is not installed, so it silently does nothing**. `date` is
checked now that the checker is present; the URL shape is enforced directly, in the same
place the independence rule lives.

### An empty string passed three checks that existed to stop it

- `answer.exact: ""` — the check was `is None`, which an empty string satisfies. At
  runtime `check_answer` parses `exact` and compares against the result, so **every**
  correct answer for that item is scored wrong, reporting "39 is not None", with nothing
  saying why. Verified against the real grader.
- `primary_concept: ""` — guarded by `if primary and ...`, so the check was skipped for
  the one value that is always wrong. It is a foreign key into `concepts` at runtime.
- A `tests` item with no `entrypoint` — optional in the schema, and `grading.coding`
  raises `ValueError` without it while `agent.tools` raises `KeyError`. It validated clean
  and crashed the grader the first time anyone was served it.

### Nothing checked a complexity probe at all

All of these validated clean: a `complexity_target` with the probe deleted, sizes in
descending order, three identical sizes, and a generator whose entire body was the string
`"TODO: write this generator"`. `item.schema.json` says outright that a target without a
probe "cannot run at all", and docs/CORPUS.md makes the pairing an authoring checklist
item — which is a note to a human, not a gate.

The sharpest of these is the target string itself, because it fails **silently**:

```
quadratic solution, target 'O(n)'      -> exit 1   SLOW  slope 2.07 vs O(n)
same solution,      target 'O(n + m)'  -> exit 0   complexity inconclusive
```

An unrecognised target returns `None`, `judge` reports `inconclusive`, and
`verify_reference_solutions --complexity` only fails on a confident `slower_than_target`.
So `O(n + m)`, `O(n) amortised`, `O(sqrt(n))` and a `0(n)` zero-for-O typo all turn the
gate off without a word.

`classify_target` moved from the executor into `packages/corpus`, which is where it
belongs: it is a statement about what a corpus string *means*, and the corpus owns the
item contract. One definition, imported by the executor to judge a measurement and by the
validator to refuse a target it could never judge — rather than a copy in each that drifts.

### A typo in one key deleted a quarter of the corpus, silently

`load_items` used `payload.get("items", [])`. Renaming `items` to `item` in `coding.json`
— a merge artifact, a hand edit — removed twelve items from the corpus *and* from
validation:

```
159 concepts · 36 items (12 archetypes, 24 instances) · behavioral=12, quant=12, system_design=12
corpus valid — 0 errors, 0 warning(s)          exit 0
```

The summary line is the only signal, and nothing compares it against anything. Missing or
non-list `items` is now a load failure, reported as an error rather than a traceback.

### The originality check is blinded by one bold word in eight

Not fixed, but now stated accurately in docs/CORPUS.md, because the honest description
was already half-written there and this narrows it further. `_shingles` is
`text.lower().split()` with no punctuation or Markdown stripping, and the field it
tokenizes is `statement_md`. On one 60-word paste, differing only in emphasis markers:

| | containment | verdict |
|---|---|---|
| raw paste | 100% | error, correctly |
| every 8th word bolded | 0.0% | passes |
| every 10th word bolded | 22.6% | error |

Reflowing the same paste as a bullet list takes the 12-gram check from 49 hits to zero.
docs/CORPUS.md already said a statement copied from a live URL passes cleanly; it now also
says that the one slip it *does* catch is only caught in raw, unformatted form.

### Still open

The complexity probe's free pass for the slowest submissions — a cubic solution scores 1.0
where a quadratic one scores 0.75, because the pessimistic projection refuses to start a
second size and `inconclusive` carries no penalty. `recompute` rebasing item ratings onto
a prior the live path never used. An unbounded number of tool executions per turn. And
`check_docs.py`'s own blind spots, which are the next batch.

---

## Audit wave 6 — the probe rewarded the worst answers, and a re-rating broke the replay · 2026-08-22

Sixth batch: the two findings that invert a guarantee rather than merely weakening one.

```
make check 249 · test-db 148 · test-sandbox 28 · test-e2e 1 · verify-solutions 8/8
executor tests 40 (was 37)
```

### A cubic solution scored higher than a quadratic one

Measured end to end on `i.code.0005` (target `O(n)`), real containers, real grader:

```
O(n^2) submission  ->  slower_than_target, slope 2.02  ->  SCORE 0.75
O(n^3) submission  ->  inconclusive,       slope None  ->  SCORE 1.00
```

The mechanism is a guard doing the opposite of its intent. With one point measured the
driver assumes the worst class it recognises (`_g = 3.0`) before starting the next size,
so it refuses to start one whenever the first run took more than about 2.2 s. The sweep
then ends with a single point, `judge` requires three, and `inconclusive` carries no
penalty anywhere in `grade_coding`. The module's own comment claims the opposite —
"bailing out with the points already collected keeps it judgeable instead of reporting
`inconclusive` for the most damning case there is" — and the pessimistic projection
guarantees there are not enough points to judge.

Two changes, both of which turn an absence of evidence into evidence:

- **A truncated sweep is now `slower_than_target`.** The driver truncates *because* it
  projected the next size as unaffordable, which is a statement about how fast this
  submission grows, not a missing measurement. `truncated` was already computed and was
  being discarded in `run_probe`.
- **A first size costing over a second is `slower_than_target` without a slope.** Every
  corpus reference measures 0.3–0.5 ms at its smallest size, so this is three orders of
  magnitude of headroom.

All eight references still measure `matches`, unchanged.

### `recompute` rebased item ratings onto a prior the live path never used

The central claim of docs/ADAPTIVE.md is that mastery is derived and a replay reproduces
the live table exactly. `items.elo` drifts from real outcomes and a re-seed deliberately
leaves that alone — but a re-seed *does* refresh `difficulty_elo`, and `recompute` rebuilds
`elo` as `difficulty_elo` plus a replay. So re-rating an existing item left the two paths
standing on different priors, for good:

```
after one attempt:  item.elo=1597.94  ability=1574.69
after re-seed:      item.elo=1597.94  ability=1574.69   (live table, unchanged)
after recompute:    item.elo=1677.56  ability=1579.32   (replay)  -> 4.64 Elo apart
```

`POST /mastery/recompute` is the documented repair tool for a grader bug. Here it was the
thing doing the damage. `api.seed` now returns which priors it changed and replays the
projection onto them, so both paths stand on the same numbers — and it says so on stdout,
because a silent rebase is how this stayed invisible.

It stayed invisible for a specific reason worth keeping: **the test suite replays after
every test**, so a development database is permanently rebased and only a long-lived one
can diverge. No test could have caught it, and the new one asserts the *reporting* rather
than the divergence.

### The replay gate had a hole in the shape its own docstring warns about

`snapshot()` collects "every column the projection owns, `fsrs_card` included", and its
docstring says outright that "a replay gate that skips a column is a gate with a hole in
it." It did not read `last_seen` — a column added to `Mastery` after that sentence was
written. No live divergence today (a 120-sequence property test comparing `last_seen`
explicitly found none), so this is a hole rather than a bug, and it is closed.

### An intermittent CI failure, and why the fix is not "retry"

`test_memory_bomb` failed once on GitHub's runners with `harness_error` and **an empty
detail**, having passed on the three runs before and the run after. Two real weaknesses
made that both possible and undiagnosable:

- OOM attribution read only `docker inspect .State.OOMKilled`, which is set by the runtime
  and depends on the cgroup version and on whether the kill landed on the container's init
  or a child. This module sends exactly one `docker kill`, on the wall-clock path, so a
  **137 arriving on any other path was not killed by us** — and the memory cap is the only
  other thing in this sandbox that kills a container. Inferring OOM from it is sound, and
  it fails safe: mislabelling some other hard kill as OOM still refuses the submission.
- A `harness_error` with an empty detail is unactionable. It now carries the container's
  exit code, which is not sensitive and is the whole diagnosis.

### Also

`run_probe` splatted the marker payload straight into a comprehension, so a probe result
whose points were not pairs raised `ValueError` out of the request handler — the same class
fixed in `parse_result` two waves ago, in the other of the two parsers.

### Still open

The executor buffers container output without bound before applying its 64 KB cap (500 MB
of output measured at ~1.7 GB peak RSS in the executor, and at high throughput the
wall-clock kill stops working). `run_sandboxed` can raise from three paths, each becoming
an executor 500 that the API records as "not the candidate's fault". A turn can execute an
unbounded number of tool calls — 300 sandbox runs and 603 events in one request, evicting
the session's whole event history with no `stream.gap`. `/dev/shm` is writable and escape
test 2 never tries it. And `check_docs.py` has four blind spots of its own.

---

## Audit wave 7 — three ways to make your own grading disappear · 2026-08-22

Seventh batch: the executor. The theme is one the sandbox audit named — `run_sandboxed`
promises "never raises, never hangs" and had three paths that raise. Each becomes a 500,
which `ExecutorClient` maps to `ExecutorUnavailableError`, which the API records as
"executor unavailable" — a verdict that by design **says nothing about the submission**.
So each was a reliable way for a candidate to turn a bad attempt into an infrastructure
fault.

```
make check 249 · test-db 148 · test-sandbox 31 · test-e2e 1 · verify-solutions 8/8
```

### The 64 KB output cap bounded what was kept, not what was read

`communicate()` accumulates the whole stream in the executor's address space; the
truncation ran afterwards, when the memory had already been spent. The container's own
`--memory=256m` is irrelevant, because the memory is spent on the **host** side of the pipe.

| | before | after |
|---|---|---|
| 500 MB of output | ~1.7 GB peak RSS, 2.5 s, `outcome="ok"` | 60 MB, 2.1 s |
| unbounded writer, 5 s wall | **30.4 s real**, 2.9–5.0 GB, `docker rm -f` blew its own 15 s timeout | clean `timeout` at 5.2 s, 79 MB |

At high throughput it wedged the daemon's attach stream, which is why the wall-clock kill
stopped working — the declared 5 s wall became 30 s. Output is now read on two bounded
reader threads that keep a rolling tail, so nothing accumulates and the wall clock is the
bound on time again.

### And the cap was truncating the wrong end

Found while fixing the above, and it is the more consequential half. The retained window
was the **first** 64 KB. The driver prints its result marker **last**, and `parse_result`
scans backwards for it — so any submission whose own output exceeded 64 KB lost its
grading entirely and came back `harness_error`. A candidate printing debug lines was
scored as a harness failure.

docs/SECURITY.md recorded this as an unavoidable consequence of truncation ("if truncation
eats the result marker, the run becomes a `harness_error`, so a very chatty correct
solution fails"). It was not unavoidable; it was an artefact of keeping the wrong end.

### A lone surrogate in the source crashed the request

`"\ud800"` is a well-formed JSON escape, so a perfectly valid `POST /execute` body delivers
a lone surrogate as a `str`. `communicate` in text mode encoded it with the default handler
and raised `UnicodeEncodeError` past the "never raises" contract. Encoding is explicit now
— and `surrogateescape` is *not* enough, because it only round-trips U+DC80–DCFF, so the
first fix still raised on `\ud800`. With `replace`, the container reports a syntax error,
which is a grading failure and the right answer.

### `_run` propagated its own timeouts, including from the `finally`

Both `docker kill` (inside the timeout handler) and `docker rm -f` (from the `finally`)
hit their own timeouts under load and raised — the second also masking any result already
computed. It returns a sentinel now and never propagates.

### The reaper the docs cite had no caller

docs/SECURITY.md justifies dropping `--rm` — which is genuinely necessary, since `--rm`
destroys the container before `docker inspect` can tell a wall-clock kill from an OOM kill,
both being exit 137 — by pointing at "a labelled reaper for containers orphaned between
those steps." `reap_orphans` had one definition, zero callers, no startup hook, no timer.
It runs on executor startup now, which is exactly when the containers orphaned by a
previous process's crash are visible.

### What is still open, and what is deliberately not being fixed

**Not fixed, by decision:** a candidate can still forge a *plausible* result — a full score
on the real test count. docs/SECURITY.md scopes that out (single user, the only person
deceived is the one practising) and that reasoning is unchanged. What wave 2 fixed was the
blast radius, not the forgery.

**Still open:** `/dev/shm` is writable and escape test 2 never tries it — real harm is
small (64 MB, per-container, destroyed with it) but both the doc and the test's stated
requirement are literally false. A turn can execute an unbounded number of tool calls —
300 sandbox runs and 603 events in one synchronous request, evicting the session's entire
event history with no `stream.gap`. The probe's 20 s budget is `process_time` while the
wall is real time under `--cpus=0.5`, so the first size is still not covered by the
projection. And `check_docs.py` has four blind spots of its own.

---

## Audit wave 8 — a turn that ran 300 containers, and a writable path nobody tested · 2026-08-22

Eighth batch, and the last of the confirmed high-severity findings.

```
make check 249 · test-db 149 · test-sandbox 31 · test-e2e 1 · verify-solutions 8/8
```

### One turn, 300 executor round-trips, and the session's history gone

`MAX_TOOL_ROUNDS = 5` caps *model calls*. Nothing capped `tool_use` blocks per response,
and the loop executed every one of them:

```
60 run_code blocks per response, 5 rounds:
  truncated: True | tool_calls reported: 300
  executor invocations in ONE turn: 300
  turns rows written: 307
  bus events published: 603      (against a 256-slot buffer)
```

Two consequences. Three hundred container round-trips inside one synchronous HTTP request.
And 603 events into a 256-slot ring — so a single turn **evicted the entire session's
history**, `item.presented` and `hint.revealed` and `grading.result` with it, and emitted
no `stream.gap`, because that check runs once at stream open and never again.

A candidate reaches this without a malicious model. "Run each of these sixty variants" is
all it takes. `check_answer` and `record_observation` already carried per-item rations;
`run_code` — the only tool that reaches the executor — had none. Twelve executions per
turn now, reported through the same `truncated` flag the round cap uses.

### The writable path escape test 2 never tried

Docker mounts a 64 MB writable `/dev/shm` by default, and `--read-only` does not cover it.
`test_no_filesystem_escape` checked four write targets — `/tmp`, `/etc`, `/root`, `/` —
all four on the read-only rootfs. So the assertion "writes outside denied" passed **because
the escape was never attempted**:

```
WRITE_OK:/dev/shm/x
write_denied:/tmp/x:OSError      write_denied:/etc/x:OSError
write_denied:/root/x:PermissionError   write_denied:/x:OSError
```

Real harm is small — per-container, destroyed with it, no cross-execution persistence — but
docs/SECURITY.md's "one writable `tmpfs` scratch dir per execution" and the test's own
stated requirement were both literally false, which is the failure mode this repo keeps
finding: a green test that proves nothing.

`--shm-size 0` turns out not to be honoured (Docker falls back to its default), so the
mount is shadowed with a read-only tmpfs, the same trick already used for `/etc`. `/scratch`
still writable, all 31 sandbox tests green.

### Where the audit stands

Eight waves. Of roughly fifty confirmed findings, the ones that remain are the ones I judged
either lower severity than the cost of fixing them now, or genuinely out of scope:

- **Out of scope by decision.** A candidate can still forge a *plausible* result — a full
  score on the real test count. docs/SECURITY.md scopes that out and the reasoning holds;
  wave 2 removed the blast radius, not the forgery.
- **The undeclared quant answer.** "So I'd pay at most 6 dollars, comfortably under the 7
  dollar pot" is still scored correct at 0.75. It cannot be fixed by reading harder — the
  sentence that needs the *first* number and the sentence that needs the *last* have the
  same shape.
- **Lower severity, not yet done:** `check_docs.py`'s four blind spots (a phase row matched
  anywhere in a 190 KB file, a positional README column read, a `(?<!not )built` lookbehind,
  and both doc gates globbing non-recursively); the probe's 20 s `process_time` budget
  against a real-time wall under `--cpus=0.5`, which still does not cover the first size;
  `session.error` specified and never emitted; SSE timestamps using `+00:00` where the JSON
  bodies use `Z`; and the practice log's own concurrency and validation findings, of which
  only the unbounded `secondary_concept_ids` has been closed.

The buildlog names these rather than letting eight waves of fixes read as "the audit is
finished". It is not; what is finished is everything that corrupts data, costs money, or
lets a candidate control their own grade.

---

## Audit wave 9 — a change I made, measured, and took back out · 2026-08-22

One finding, one fix, and a reversal worth more than the fix would have been.

### The finding: the planner ranks 159 concepts and can serve 16

```
concepts in the taxonomy                                              159
…that some item TAGS  (evidence written, ability moves, ranked)        53
…that some item measures as PRIMARY (the planner can serve)            16
```

So 37 concepts accumulate real evidence and are ranked by weakness, and none of them can
ever be served. `big-o-analysis` is tagged on **all eight** coding items: the engine learns
you are weak at it, ranks it, and serves nothing.

The grading layer already models two tiers — `grading/coding.py` writes evidence for every
tagged concept at `SECONDARY_CONFIDENCE`, commented "real evidence, softer claim". The
planner used one. Widening it looked like the highest-leverage change available: 37
concepts reachable with no new corpus, worth more than the next four authoring waves.

### The measurement: it made the engine worse

Implemented, and the Phase 4 gate immediately caught it. `big-o-analysis` is tagged on
everything, so it accumulates observations faster than any real concept and — being weak
for the same reason the candidate's actual weakness is weak — **crowded the injected
weakness out of the plan**:

```
before:  weakness served 6 of 10 sessions, and most-served
after:   weakness served 5 of 10 sessions, no longer a majority
```

It also produced plans containing the same item twice, once under its primary concept and
once under a tag — and the second submission for an item is refused 409, which strands the
session. That was fixable. The crowding was not, because it is not a bug: secondary
evidence propagates one concept's weakness to everything co-tagged with it, which is what
"real evidence, softer claim" *means*.

### The reversal

`test_focusing_on_a_secondary_only_concept_says_what_actually_happened` already existed,
already asserted a 422, and its docstring already explained the reasoning. The repo decided
this deliberately and my change overrode it. It is reverted.

What was actually wrong was one sentence. The plan reported:

```
"stack-simulation gates it and is weaker, but no item measures it"
```

about a concept **two items measure**. That reads as a corpus gap and is a policy. It now
says "no item measures it **as a primary concept**", and docs/ADAPTIVE.md carries the
policy and the measurement behind it.

Worth keeping as a finding in its own right: the ranking is honest and the serving is
narrower than the ranking, on purpose. An engine that plans well and explains itself
imprecisely is a better engine than one that plans badly and explains itself exactly — but
only the second of those is visible without running the gate, which is why the gate exists.

---

## Phase 5 (the shell) — a client that cannot reach its own API · 2026-08-24

The first Phase 5 work. `apps/web` had been an empty directory since Phase 0, and
docs/WEB.md a specification nothing had tested. Two of its assumptions did not survive
contact with the running server.

### The API is unreachable from a browser on another port

docs/WEB.md says the web app is "a pure consumer of API.md" and sets `credentials:
"include"` on every request. That is necessary and not sufficient. The session cookie is
`HttpOnly; SameSite=Lax`, set on the API's origin — and **`apps/api` mounts no CORS
middleware at all**. A page at `localhost:3000` fetching `localhost:8000` is cross-site, so
the browser withholds the cookie, and the request would be refused before that mattered.

Two ways out: relax the cookie to `SameSite=None; Secure` behind a CORS allowlist, or put
both services on one origin. This takes the second. `next.config.ts` rewrites `/api/*`,
`/auth/*` and `/health` to `API_ORIGIN`, so the browser only ever talks to one host, the
cookie stays first-party, and the API keeps no browser-origin allowlist to get wrong. It is
also the deployment shape already planned — one ALB routing by path (docs/INFRA.md) — so
development and production differ in hostnames and nothing else.

Verified against the running stack, not reasoned about:

```
GET localhost:3000/api/v1/mastery         no cookie    → 401
GET localhost:3000/api/v1/mastery         with cookie  → {"concepts":[…],"measured":16}
GET localhost:3000/api/v1/corpus/status   with cookie  → 159 concepts, 48 items
```

### Every SSE frame is named, so `onmessage` never fires

`Event.as_sse` writes `event: <type>` on every frame. A browser `EventSource` dispatches a
named frame to a listener registered for that name, and `onmessage` receives **only unnamed
frames** — so the obvious client, the one that reads `source.onmessage`, sits silent for an
entire session and reports no error. `EVENT_TYPES` in `src/lib/stream.ts` is the subscribed
list, kept beside the type union so a new event type cannot be added without appearing in
it.

The same file records the other end of it: the server closes the stream when the session
reaches a terminal state, and `EventSource` treats any close as a fault and reconnects
forever. A finished session left open in a tab reopens a stream every few seconds unless the
client closes it itself, which it now does on the terminal `session.state`.

### A gap the server cannot see

docs/API.md promises `stream.gap` when a client resumes from before the buffer — and audit
wave 8 measured a single turn emitting **603 events against a 256-slot buffer**, evicting the
session's history "with no `stream.gap`, because that check runs once, at stream open". So
the reducer also checks `seq` itself, on every event, and reports a jump as loss with
`source: "client"`. That is the case the server is structurally unable to report.

`agent.message.done` is treated as authoritative by *replacing* the delta buffer rather than
reconciling against it, which is the only handling that survives a dropped delta — asserted
by a test that deletes one delta from the recorded fixture and expects the finished text.

### The heatmap was one colour, and the reason was arithmetic

`mastery_row_view` helpfully returns `normalized_ability`, and colouring cells by it is the
obvious thing to do. It divides by the whole rating scale — floor 600, ceiling 2800 — so the
1550 every concept starts at normalises to **0.43**, and a concept moved 200 points by real
evidence still lands between 0.34 and 0.52. Sixteen measured concepts spanning 1501 to 1560
Elo all fell inside one band of five, and the heatmap rendered as a single shade.

Cells band on **Elo** instead, on cutoffs centred at the 1550 start, and the legend prints
them. `normalized_ability` is not wrong — it is a scale for a 2200-point range being asked
to resolve a 60-point one.

The two rules docs/WEB.md sets for this chart are structural rather than stylistic, and each
has a test: ability is a single-hue sequential ramp (never red-to-green), overdue is a ring
**and a corner wedge** so it survives greyscale, and the observation count is printed in every
cell because 0.4 from two attempts and 0.4 from thirty are different situations.

The ramp was validated rather than eyeballed — the dataviz skill's checker, against these
surfaces, as an *ordinal* ramp because the lightest step here means "weak", a real value that
must stay visible, not "near zero", which may recede:

```
light  #86b6ef #5598e7 #2a78d6 #1c5cab #104281   on #fcfcfb   ALL CHECKS PASS
dark   #cde2fb #9ec5f4 #6da7ec #3987e5 #184f95   on #1a1a19   ALL CHECKS PASS
```

### Two smaller things the scaffold got wrong

`create-next-app@latest` installs **Next 16**, against docs/WEB.md's Next 15 and the 15.5.20
already used in `backtest-lab`. Pinned back to 15.5.20 / React 19.1.0 rather than taking a
major-version jump no document had sanctioned; the generated `eslint.config.mjs` imports
flat configs that only exist in 16's package, so it is bridged through `FlatCompat`.

It also writes `allowBuilds: esbuild: set this to true or false` into
`pnpm-workspace.yaml` — a literal placeholder that fails **every** `pnpm install` until a
human answers it, which is a fresh clone with no working test runner.

### What was verified

- `pnpm lint`, `pnpm typecheck`, `pnpm build` — clean.
- **20 component tests** against recorded SSE fixtures and a hand-built concept set,
  covering delta reconciliation, both kinds of gap, tool-result pairing, replay after
  reconnect, the overdue shape, the never-measured neutral, and the Elo banding.
- The proxy, against the live API, both with and without a cookie.
- `make check` (Python side) still green — 272 passed.

Not verified: **nothing has been looked at in a browser.** There are no browser tools in
this environment, so layout, contrast in situ and focus order are unproven; the tests assert
structure and class names, which is not the same claim. The Playwright run docs/WEB.md names
as the Phase 5 gate is still owed, and so are the other eight routes.

The dashboard was read against 54 fixture evidence rows written into the local database
through `apply_evidence`, stamped `grader_version="dev.fixture"`. They are not in the repo,
and they are undone by deleting those rows and re-running `POST /mastery/recompute` — which
is exactly the property docs/ADAPTIVE.md claims for a projection.

---

## Phase 5 (the routes) — every screen docs/WEB.md specifies · 2026-08-24

The other eight routes, the four workspaces, and three places where building the client
found something about the server.

### The workspaces are shaped by their graders, not by their modes

The quant workspace splits derivation from answer because `closing_statement` does. The
grader reads the answer from a declaration ("Answer: 39") wherever it appears, and failing
that from the last line carrying arithmetic — a rule that exists because a derivation
mentions numbers that are not the answer, and a wrong first attempt on line two used to
outrank the right answer on line four. So the answer field is appended as a declared final
line rather than left for the heuristic, and an empty field appends *nothing*: a candidate
who never committed to a number has not got it wrong, and the two score differently.

The design workspace is a structured component editor for the reason docs/WEB.md gives —
"a grader that cannot read the artifact produces vibes". Removing a component also removes
its connections, because an edge to a deleted node serialises as `?` and a rubric grader
citing `?` is citing nothing. The *visual* canvas is not built and is not faked: the
grading value is in the structure, and a layout carries none of it.

The behavioral workspace omits empty STAR sections rather than sending the heading. A
heading with nothing under it reads as an attempt at that section, which is worse than its
absence.

### `/corpus` says what is missing instead of showing an empty browser

docs/WEB.md wants a corpus browser with unseen statements redacted. That needs
`GET /corpus/items/{id}` — specified in docs/API.md, not built — **and** something that
lists item ids to reach it with, which is not specified anywhere. The page shows the
counts `GET /corpus/status` really returns and then states the gap. An empty browser looks
broken; a stated gap is a gap.

### `session_view` still says no model call has ever been made

Found while typing the client, not fixed here because it is not the web app's to fix:

```python
# apps/api/src/api/sessions.py
"tokens_consumed": 0,
"budget_enforced": False,
```

with the comment "docs/COST.md's budgets are read into settings and enforced nowhere, and
no model call has ever been made". Both halves stopped being true on 2026-08-20, when the
model-call path landed with the budget enforced and the ledger written — `/costs` reports
29 real calls against this database. So `GET /sessions/{id}` tells every client that
budgets are off. The web app reads its budget banner off the SSE `budget.warning` event
instead, which is real; the two fields are a Phase 3 correction and are written down here
rather than carried in someone's head.

### `Idempotency-Key` is sent and ignored

docs/API.md says it is "owed before the web app, which will retry on flaky networks". The
web app now exists and it is still owed, so the client sends the header and the comment in
`api.ts` says outright that the server drops it. What *is* protected is the harmful half —
one item cannot write two sets of evidence into one session, because a second submission
is refused `409` — and TanStack Query is configured not to retry mutations. A user pressing
a button twice still creates two sessions.

### A trap worth writing down

`pnpm build` while `next dev` is running writes into the same `.next` directory and
corrupts it. Every route then answers **500** with `ENOENT: _buildManifest.js.tmp.*` — an
error that names a temp file and nothing about the cause. `rm -rf .next` and restart.

### What was verified

- **26 component tests**, up from 20: the quant declaration and its absence, the design
  serialisation and its dangling-edge removal, the behavioral omission, plus the reducer
  and heatmap suites. The coding workspace is deliberately untested — it renders Monaco,
  which does not run under jsdom, and asserting against a stub of the editor would test
  the stub.
- **All nine routes answer 200** against a live stack with a real session created through
  the proxy (`01M0TFKWN9…`, quant, three planned items).
- `pnpm lint`, `pnpm typecheck`, `make check` — clean, 272 Python tests still passing.

Still not verified, and still the most important sentence here: **nothing has been opened
in a browser.** Layout, contrast in situ, focus order and keyboard reachability are
unproven. The component tests assert structure and class names, which would not catch a
collision, an overflow, or a control nothing can tab to.

---

## Phase 5 (dependencies) — the frontend arrived with 25 advisories · 2026-08-24

GitHub reported them on the push, which is the first useful thing that happened after it.
`apps/web` is the first substantial npm tree in this repo, and the audit is worth recording
because one advisory lands squarely on the design decision made two commits earlier.

```
before   17 found:  6 high · 9 moderate · 2 low
after     0 found
```

Eight were in `next` itself, all fixed by **15.5.20 → 15.5.23** — inside the Next 15 line
docs/WEB.md pins, so honouring the spec and clearing them were not in tension after all.
That is worth noting against the earlier decision: pinning back from the Next 16 that
`create-next-app` installs did *not* mean accepting known holes, it meant reading which
patch release closed them.

The one to read twice: **"SSRF in rewrites via attacker-controlled destination host"**,
high. Rewrites are the mechanism the whole same-origin proxy is built on. The destination
is one value out of `API_ORIGIN` with nothing request-derived in it, so the vulnerable
pattern is not present here — but an advisory naming the single piece of framework
configuration this app depends on is not one to skim.

The remaining nine were transitive and could not be reached by moving the parent, so they
are forced in `pnpm-workspace.yaml`: `postcss >=8.5.23` and `sharp >=0.35.0` under `next`,
`dompurify >=3.4.13` under `monaco-editor`. Real exposure was low in all three — build-time
CSS this repo authors, an image optimiser this app does not use, and Monaco's hover
renderer over the candidate's own code — which is the reason to patch them cheaply rather
than to argue about them.

**CI now fails on `high` and reports everything below.** Not on `moderate`: a gate that
breaks every build the moment somebody publishes a moderate advisory against a transitive
dependency, possibly with no fix available, is a gate people learn to skip — the same
reasoning that keeps `make hygiene` non-failing. docs/SECURITY.md carries the table and the
rule that an override which has become unnecessary is an override holding a version back.

Verified after the change: `pnpm audit` clean, and lint, typecheck, 26 tests and a
production build all still pass — an override that breaks the build is worse than the
advisory it closed.

---

## Phase 5 (the gate met a bot) — every Dependabot PR was red on arrival · 2026-08-24

A consequence of adding an npm tree, found by reading a failing CI run rather than by
thinking about it. Dependabot opened a pull request bumping `next` 15.5.20 → 15.5.21 and
CI refused it:

```
docs_with_code: 1 commit(s) change code and no documentation:
  3fa7822 chore(deps): bump next from 15.5.20 to 15.5.21 in /apps/web
```

The gate is behaving exactly as specified. `apps/**` is code, a lockfile is under
`apps/web/`, and the commit carries no `.md` — so **every dependency bump a bot will ever
open fails by construction**, and a bot cannot write the document that would fix it. A
gate that is permanently red for a whole class of change is one people learn to merge
past, and then it is not protecting the class of change it was built for either.

`scripts/docs_with_code.sh` now exempts a commit when the author is a bot **and** every
file in it is a manifest or a lockfile. Narrow on purpose, and verified in all four
directions on a throwaway repository rather than assumed:

| Commit | Result |
|---|---|
| bot · `package.json` + `pnpm-lock.yaml` | exempt |
| bot · manifest **and one `.ts` file** | refused |
| human · manifest only | refused |
| bot · manifest plus a doc | passes the ordinary way |

The second row is the one worth having a test for: the exemption is about who cannot write
documentation, not about which paths are exempt, so a bot smuggling source past it would
be the exemption becoming a hole. The third keeps the rule intact for people — the
15.5.20 → 15.5.23 bump in the previous entry *did* owe a document, and wrote one.

---

## Phase 3 (correction) — the session route said budgets were off · 2026-08-24

Found while writing the web client's types, fixed here because a client cannot fix it.

```python
# apps/api/src/api/sessions.py, until today
# docs/COST.md's budgets are read into settings and enforced nowhere, and no model
# call has ever been made. Reporting a consumed figure would imply a meter exists.
"tokens_consumed": 0,
"budget_enforced": False,
```

Every word of that comment was true when it was written and neither half survived
2026-08-20, when the model-call path landed with `enforce_budget` refusing a spent session
and every call writing an `llm_calls` row. So for four days `GET /sessions/{id}` told every
client that budgets were off and nothing had been spent, while `/costs` reported **29 real
calls** against the same database and `enforce_budget` was live in front of every one of
them.

It survived because **nothing asserted on those two fields.** The suite had a test for the
budget route, for the enforcement, for concurrent calls against a spent ceiling — and none
for the third place the same fact is published. A constant is invisible to a test that
never reads it.

Now read from the ledger, scoped to the session, with the ceiling beside it:

```jsonc
"tokens_consumed": 1_240,   // llm.tokens_spent(db, session_id=…)
"token_budget":  400_000,   // the limit enforce_budget refuses on
"budget_enforced": true
```

`token_budget` is additive rather than decorative: a consumed figure with no denominator
reads as smaller than it is, which is the same reasoning that puts `measured` next to
`GET /mastery`'s rows.

The test asserts against `spend_now(session_id)` rather than a literal — hardcoding the
number would be the same mistake one layer up — and it was checked by putting the old
constants back and watching it fail:

```
>       assert before["budget_enforced"] is True
E       assert False is True
```

The web app's session header now shows the pair, which is the first time that number has
been visible anywhere outside `/costs`.

### A side effect worth keeping: the projection claim, tested by accident

The dashboard was read against 54 fixture evidence rows written into the local database.
`make test-db` then failed **10 tests** — `test_a_cold_start_plan_says_it_is_calibrating`,
`test_an_injected_weakness_gets_drilled`, and eight others:

```
>       assert plan["calibration"] is True
E       assert False is True
```

Correctly. A cold-start plan is not calibrating once evidence exists, and the fixture rows
were evidence. Nothing was wrong with the code; the gate was reading a database somebody
had put data in.

Undoing it is the interesting part, because it is the claim docs/ADAPTIVE.md makes about
`mastery` being a projection rather than a source:

```
deleted 54 dev.fixture evidence rows
POST /api/v1/mastery/recompute  →  {"evidence_replayed": 0, "concepts": 0}
make test-db                    →  150 passed
```

Delete the evidence, replay, and the projection is exactly what it was — no hand-patching,
no residue in `mastery` or in `items.elo`. That property is asserted by a gate already; it
had not been exercised by deleting real rows out from under a populated table. The
practical lesson is narrower and worth stating: **`make test-db` runs against the same
local database development uses**, so anything written there for a screenshot is something
the next gate run will read.

---

## Phase 3 (`Idempotency-Key`) — owed before the web app, built after it · 2026-08-24

docs/API.md carried this line from Phase 3 until today:

> **Idempotency:** `POST /sessions` and `/submissions` are specified to accept
> `Idempotency-Key`; **neither does yet**. […] Owed before the web app, which will retry
> on flaky networks.

The web app arrived first and spent two commits sending a header the server dropped, with
a comment in `api.ts` saying so. This closes it, and the line in API.md now records that it
landed after rather than before — a promise this repo did not keep is more useful visible
than tidied away.

### The primary key is the feature

`idempotency_keys(user_id, endpoint, key)`, composite PK, response stored against it. Two
concurrent retries of one request both find no row and both proceed unless the *insert*
refuses the second — which is the same finding as `artifacts(session_id, item_id)` and
`turns(session_id, seq)` in c4a71f2e83b0, and deliberately the same fix rather than a lock.
The reservation row is committed **before** the handler runs, because a reservation held in
an open transaction is invisible to the retry it exists to stop.

Four states, four answers: unused runs it; same body finished replays; same body still
running is `409`; different body is `422`. A *failed* request deletes its own reservation —
a `422` is expected to be retried, and a row left behind would answer that retry with a
`409` for as long as it lived.

### What it does not replace

The one-submission-per-item `409` protects a different thing and both stay. That rule
refuses a second artifact for one item however it arrives; a key stops one client's retry
being told its submission failed when it had not. Worth stating because the older rule was
described in API.md as covering "the harmful half" of idempotency, which is true about
evidence and not true about what a retrying client is told.

### Two things found on the way

**The model and the migrations had drifted.** `--autogenerate` proposed dropping
`ix_llm_calls_status_created` — the composite `(status, created_at)` index enforcement
filters on, added deliberately in c4a71f2e83b0 — and replacing it with a single-column
index, because `LlmCall.status` said `index=True` while the composite lived only in the
migration. It would have been a quiet performance regression one careless review away, and
it would have been proposed again by every future autogenerate. The index is now declared
in `__table_args__`, so the model and the database agree and autogenerate has nothing to
say about `llm_calls` at all.

**The test suite was not repeatable.** The first version of the tests used fixed keys, and
`_cleanup` deleted sessions but not idempotency rows — so a second run replayed the *first
run's* responses, pointing at sessions the teardown had already deleted:

```
run 1:  7 passed
run 2:  5 failed, 2 passed
```

Which is the feature working exactly as designed against a database nobody cleaned. The
fixture now clears the table, and the suite was run three times in a row to prove it rather
than once to prove it passes.

### Verified

- **7 tests**, each counting rows rather than trusting the response body — a replay that
  returned the right JSON while creating a second session would pass a shallower test and
  be the bug this exists to prevent.
- The concurrent case drives two real threads through a barrier and asserts one session,
  with either `[201, 201]` or `[201, 409]` as the pair of answers.
- Against the live server through the web proxy: the same key twice returned
  `01M0THAQ1J5RZ5FM6X7TZESB29` both times, the same key with `budget_minutes: 90` returned
  `idempotency-key-reused`, and two keyless posts made two sessions.
- `upgrade`, `downgrade`, `upgrade` on the migration.

**Not built: expiry.** Rows are kept indefinitely, so the table grows with every keyed
request. Nothing here is remotely large enough for that to bite, and a reaper belongs with
the operational work rather than bolted on now — but it is a growth curve with no ceiling,
which is the kind of thing this repo would rather have written down than discovered.

---

## Phase 5 (`/login`) — the redirect docs/WEB.md asked for was a dead end · 2026-08-24

Found by opening the app in a browser for the first time, which is the thing every entry
above says had not happened yet.

docs/WEB.md's rule reads: an unauthenticated route "should send the browser to
`/auth/login` rather than rendering an error". Followed literally — and it was — the
browser lands on an **API** route, and with OAuth unconfigured that route answers:

```json
{"type": ".../not-configured", "status": 503,
 "detail": "OAuth is not configured: GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_ALLOWED_ID unset."}
```

The server is right. An OAuth app with no `GITHUB_ALLOWED_ID` would admit *any* GitHub
user to a single-user deployment, so the flow refuses rather than running weakened. But
the user is looking at raw `application/problem+json` with no way forward, on a fresh
clone, at the front door — and the rule that produced it was followed exactly. A doc can
be right about the mechanism and wrong about the outcome.

`/login` is now the redirect target, and it establishes which of three states the
deployment is in before rendering: signed in (go back), OAuth ready (offer the button), or
unconfigured (name the unset variables and give the supported way in). It adds no
unsupported one — there is still no dev-login route and no `AUTH_MODE` flag, because a
flag is a thing that can be wrong in production. What it does is explain that `make login`
signs a cookie *outside* the process with the same secret, which was always the documented
local path and was written down only in the README.

Distinguishing "unconfigured" from "ready" without a new endpoint: fetch `/auth/login` with
`redirect: "manual"`. A configured server answers a 3xx toward github.com, which arrives as
an opaque response rather than a cross-origin fetch that throws; an unconfigured one
answers a 503 the client can read. A *network* failure stays `unknown` and is not reported
as a configuration problem — telling somebody their OAuth app is broken when their API is
merely down is a worse error than saying nothing.

### The redirect URI is the web app's port, not the API's

Worth its own note, because the default in `.env.example` is wrong for this setup and the
failure is silent. `GITHUB_REDIRECT_URI` defaults to `http://localhost:8000/auth/callback`.
The callback's `Set-Cookie` is stored against **whichever origin answered the request**, so
a callback on `:8000` produces a cookie the browser will not send to `:3000` — the same
cross-site problem the proxy was built to remove, arriving through the one route that would
otherwise bypass it. Sign-in would appear to succeed and every subsequent request would be
a 401.

Verified rather than assumed, since the whole approach depends on it:

```
POST :3000/auth/logout  →  204, set-cookie: ih_session=""; Path=/; SameSite=lax
POST :8000/auth/logout  →  204, set-cookie: ih_session=""; Path=/; SameSite=lax
```

Next passes `Set-Cookie` back through the rewrite unchanged, so the entire OAuth flow can
run on one origin.

### Verified

30 component tests, up from 26: the four probe states, including that a network failure is
not reported as a misconfiguration. `/login` renders 200, and the three server responses it
branches on were checked live — `/auth/login` 503, `/auth/me` 401 without a cookie and 200
with one.

### The callback's reason for answering JSON had expired

Same shape as the `tokens_consumed` finding, found the same way — by using the thing.
`/auth/callback` carried this:

> Answers JSON rather than redirecting: there is no web app to redirect to until Phase 5
> (docs/WEB.md), and a redirect to a route that does not exist is a worse first impression
> than a body that says what happened.

Entirely correct, and it named its own expiry date. Phase 5 landed hours earlier, so a
browser finishing a GitHub login was dropped on a JSON document with no way back to an app
that now existed.

A request whose `Accept` carries `text/html` now gets a `303` to `/`; everything else still
gets `{authenticated, user_id, github_id}`. Negotiated rather than switched outright
because three tests assert that body and it is the useful answer for anything driving the
flow programmatically — GitHub sends a *browser* here, and `Accept` is the one thing a
browser navigation reliably says about itself.

The redirect is **relative**, which is the part worth keeping. It resolves against whichever
origin served the request — necessarily the origin the cookie was just set on — so the flow
run through the web app's proxy returns to the web app, and there is no second "where is
home" setting able to disagree with `GITHUB_REDIRECT_URI`.

Verified live after configuring a real OAuth app: `/auth/login` answers `302` to
github.com with `redirect_uri=http%3A%2F%2Flocalhost%3A3000%2Fauth%2Fcallback` and sets
the state cookie on `:3000`. The new test asserts the `303`, the `Location`, and that the
session cookie is still set — a redirect that forgot the cookie would loop forever.

---

## Phase 5 (practice log) — six endpoints with no way in · 2026-08-24

Asked for by the person using it, which is how the gap surfaced: *where do I add problems
I've already done, and get reminded to redo them?*

Nowhere. Phase 9 shipped the practice log on 2026-08-21 — six endpoints, a confidence
gate, an FSRS-inspired re-solve schedule, and a logged solve that moves the same mastery a
graded submission does. docs/WEB.md is a **Phase 5** spec written before Phase 9 existed,
so its route table never gained a page for it, and Phase 5 was built from that table. The
dashboard's "due for review" card read the queue faithfully; nothing could ever put
anything in it.

Worth naming the failure mode, because it is not "someone forgot": a spec written for
phase N and implemented at phase N does not notice a feature that landed at phase N+4 in
between. Nothing in the doc set was *wrong* — the routes table was simply complete for the
world it was written in.

### The design centre is `pending_classification`, because that is every entry today

A classification below 0.75 confidence writes no evidence, and neither does one whose
provider was unreachable. No provider is reachable here, so **every** logged problem lands
in that state — confirmed by logging one:

```
POST /practice/problems  →  status pending_classification, confidence 0.0, model null
GET  /practice/review-queue  →  due 0        # correctly out of the queue
PATCH …/classification (sliding-window)  →  active, due in 3 days, 1 evidence row
GET  /mastery  →  sliding-window ability 1566.8, observations 1
```

So confirming a tag is the ordinary path rather than the exception, and it gets a
searchable picker over all 159 concepts rather than a `<select>` with 159 options in it.
The re-solve then behaved as PRACTICE_LOG.md describes — a success stretched the interval
from 3 days to 8 (stability 7.5), wrote a second evidence row, and a re-solve attempted
against an *untagged* problem was refused `409`.

Three refusals are surfaced rather than hidden, each because it means something: a problem
awaiting a tag says it counts for nothing yet; the re-solve control is disabled with the
reason, since the solve would have nowhere to write evidence; and a resolved
classification cannot be re-tagged, because `concept_evidence` is immutable — so the page
says so rather than offering an edit that would be refused.

### A dashboard bug the types caught

`GET /practice/review-queue` returns whole problem rows with `days_overdue`. The dashboard
card, written from a guess at the shape rather than from the handler, read `problem_id`
and `overdue_days` — so its React key was `undefined` for every row and the overdue badge
could never fire, since `undefined > 0` is false. Writing the real types surfaced both as
compile errors:

```
src/app/page.tsx(148,36): Property 'problem_id' does not exist
src/app/page.tsx(150,42): Property 'overdue_days' does not exist
```

The reason it went unnoticed is that the queue has been empty all along, which is the same
reason the whole feature was missing. It is also the case *for* reading the handler rather
than the doc: `types.ts` says at the top not to guess a shape, and this one was guessed.

### Verified

Logged, tagged, re-solved and refused against the live stack through the web proxy, with
mastery checked after each step; all three pages answer 200. The two test problems were
then deleted and the projection replayed to `{"evidence_replayed": 0, "concepts": 0}`, so
the log starts empty for its actual user.

Still not verified: none of it has been looked at in a browser.

---

## Local backup — one Docker volume, nothing copying it · 2026-08-24

Prompted by a question rather than a finding: *does this get saved locally, will I lose
progress when I restart?* Worth answering by measurement, since the person asking was about
to start putting real data in.

**Restarting loses nothing, and that was verified rather than reasoned.** A marker row was
written, `make down` tore the stack out — container removed, network removed — and after
`make dev` the marker was still there along with all 15 sessions and the corpus. The
compose file has always declared a named volume; what had never been checked is that the
teardown path people actually use preserves it.

| Action | Data |
|---|---|
| Killing `uvicorn` or `next dev` | safe — stateless |
| `make down` then `make dev` | **safe — verified** |
| `colima stop`, rebooting | safe — the volume is on the VM disk |
| `docker compose down -v` · `docker volume rm` · `colima delete` | **destroyed** |

The bottom row is one flag away from the row above it. And docs/OPERATIONS.md's backup
plan — RDS snapshots, weekly `pg_dump` to S3 — is entirely Phase 6 or later, because it was
written about a deployment. So everything this project knows about one person's mastery sat
in a single Docker volume with nothing copying it anywhere, and the document covering
backups did not consider that a gap because it was not thinking about this machine.

`make backup` and `make restore FILE=… CONFIRM=1` now exist. `CONFIRM=1` is typed out for
the same reason `ALLOW_UNDOCUMENTED=1` is. The dump is `--clean --if-exists`, so it replays
over a populated database — a restore that only works into an empty one is a restore nobody
can perform in the situation they need it.

**Drilled, because this document says an untested backup is a belief.** Dump taken (88K),
then every session row deleted — 15 → 0 — then restored: 15 back, corpus intact, every page
still 200, and `POST /mastery/recompute` run afterwards as step 3 of the drill this file
already specified. The one thing it does not prove is the Phase 8 gate, which diffs a
restored projection against production's; there is no production.

### The doc gate caught the README, twice

Marking OPERATIONS as partly built broke `make doc-check` immediately:

```
README: OPERATIONS is indexed as 'Spec', but docs/OPERATIONS.md says:
        'Specification, **except local backup/restore, which is built'
```

Which is the check doing exactly what it is for. The second failure is the more interesting
one: the fix `Spec · ✅ local backup built` *also* failed, because the rule is
`cell.startswith("spec")` and the cell still led with the word. The wording changed to lead
with the built claim rather than the gate loosening to accept a cell that reads as a spec —
a gate bent to fit one row's phrasing stops catching the drift it exists for.

---

## Phase 9 (LeetCode import) — the tags were already there · 2026-08-24

Asked for directly: *instead of logging every problem, can I not integrate LeetCode?*

The answer turned on reading docs/PRACTICE_LOG.md's rule precisely. "No scraping, no URL
fetch of problem **content**" exists because docs/CORPUS.md mechanically rejects
proprietary statement text — and a title, a difficulty and a topic tag are the same three
fields the log already stores for every hand-typed entry. Reading those is inside the rule;
fetching the page is not. The page is still never fetched, and the GraphQL projections name
their fields explicitly so no query here can return a statement by accident.

NeetCode was offered as an alternative and is not one: it has no API for your progress. Its
value would have been category labels, and LeetCode publishes better ones about its own
problems.

### The tags do the classification the model cannot

The classifier is a model call and no provider is reachable, so **every** logged problem
was landing `pending_classification` for a human to tag by hand. LeetCode labels its own
problems `sliding-window`, `union-find`, `monotonic-stack` — editorial metadata that maps
almost one-to-one onto this taxonomy's 52 coding concepts. A 25-problem spread came out at
19 suggested, 5 correctly held.

### Three wrong tags, and what each one taught

The first table auto-accepted 22 of 25 and **three of them were wrong**, which is the more
useful number:

```
coin-change                  -> graph-bfs        tags: dynamic-programming, breadth-first-search
validate-binary-search-tree  -> graph-dfs        tags: binary-search-tree, …, depth-first-search
lru-cache                    -> linked-list-…    tags: design, linked-list, doubly-linked-list
```

The second was ordering — a traversal tag ranked above a structure tag, so a BST problem
became a graph problem. The other two are the same lesson: **LeetCode co-tags a problem
with the alternative solutions people post**, so a DP problem carries `breadth-first-search`
and a design problem carries its data structure. Broad tags are now *blockers*: with
`dynamic-programming` present (five concepts here) or `design` (three), only a tag that is
unambiguous on its own may win, and otherwise the problem waits for a human. Re-measured:
24 of 24 as expected, 19 suggested, 5 held.

### Nothing is auto-accepted, and that is the important decision

`resolve_classification` refuses anything already resolved — the evidence is written and
evidence is immutable. So **a wrong auto-accept can never be corrected**, while a wrong
suggestion costs a click. Everything imported lands `pending_classification` with the
concept pre-selected, and the web page grew a **Confirm all** action so fifty imports are
one decision rather than fifty searches through a 159-item list. What the import removes is
the searching, not the confirmation.

That is why `log_problem` gained `proposal` and `hold`: `proposal` skips the model call for
a question the metadata already answered, and `hold` keeps the gate closed regardless of
confidence.

### Verified

- **31 offline tests** on the mapping, with canned tag sets copied from live responses — a
  test that reaches leetcode.com is a test that fails when somebody else deploys. Three of
  them are named for the three problems above.
- Live through the web proxy: a mixed batch of six imported 4 and skipped 2 (an unknown
  slug, a non-LeetCode URL) with reasons; re-importing the same slugs skipped both as
  "already logged"; confirming the two suggestions wrote one evidence row each and moved
  `hash-map-counting` and `monotonic-stack` to 1566.8.
- The route-surface gate caught the new endpoint before the docs did, which is what it is
  for.
- Test data deleted and the projection replayed to zero afterwards.

**Not built: full solve history.** That needs a `LEETCODE_SESSION` cookie — a live
credential on a machine whose repo is public — and pasting links reaches the same place
without one. The endpoint is also unofficial and can change without notice; it is one
module, and the failure mode is a skipped import rather than a lost entry.

### A test that only passed because nobody had ever logged in

`make test-db` failed two ways immediately after the first real GitHub login on this
machine, and the cause is worth more than the fix.

`complete_login` drives `/auth/login` then `/auth/callback` as a browser would. Adoption —
the first real login inheriting the pre-auth row rather than starting a second user — only
happens when that row still *looks* pre-auth. Exactly one test set that up, and every other
test calling the helper depended on running after it. Worse, `restore_github_id` puts the
original id back when each test finishes, so the next login found no pre-auth row and
correctly created a **second user**:

```
users
  01M0GJJKKNVA183TV4ER819CS4  172091321   ← the real row, with all the evidence
  01M0TY5ZVN10NDCXW01EZNGTGV      90210   ← left behind by a test
```

From there every fixture assuming one user fails, which is what the two failures were.

The behaviour is correct — a login for an account no row carries *should* create one. The
test was wrong, and mine (`test_a_browser_completing_a_login_is_sent_to_the_app`, added
hours earlier) was the one that leaked, because it logged in without arranging the state
the helper's other callers had been silently inheriting.

`complete_login` now puts the row into the pre-auth state itself unless some row already
carries that account, so no caller depends on ordering. Verified by running the suite three
times end to end: **158 passed each time**, with the users table left exactly as found —
one row, the real id.

**CI could not have caught this, and still cannot.** It builds a database from scratch, so
its user row is always pre-auth and adoption always succeeds. The failure needs a database
somebody has actually logged into, which by construction only ever exists on a real machine.
The same is true of the practice-log fixtures earlier today. Worth stating plainly: the
local database is a *different* test environment from CI's, and the difference is history.

---

## Closing the gaps the web app opened · 2026-08-25

Four things this session had flagged as owed, plus the coverage that should have come with
them. Measured first: the fast suite reported **63%**, which was misleading — the db-marked
tests carry most of what it missed, and the honest figure including them was **89% across
461 tests**. Coverage without saying which suite is a number that flatters or scares
depending on the flag you passed.

### `GET /concepts` — four requests for content that cannot change

The dashboard was assembling all 159 concepts from **one weakness ranking per mode**,
because no endpoint served the taxonomy and `GET /mastery` returns only *measured* concepts
with no name or domain on the row. It worked, and it was four round trips to read a
build-time artifact.

One request now, and it carries two things a ranking never could: the prerequisite edges
with an `unlocks` reverse derived server-side, and `servable` — whether some item measures
the concept as a *primary*, which is the difference between what the planner ranks (159)
and what it can actually serve (16). A test asserts `unlocks` is the exact inverse of
`prereqs` in both directions, because a second hand-maintained copy of one relationship is
a second thing to get wrong.

### `GET /corpus/items` — a listing that cannot be used to read ahead

`/corpus` had nothing to browse. The detail route redacts an unseen statement, so the
listing is the part that needed care: it returns **no statement for any item, seen or
unseen**, because a listing that carried them would be a way to read every unseen item at
once. Asserted directly rather than assumed.

"Seen" is read from the *plan* of your own sessions, not from artifacts — an item you were
shown and did not answer has still been read, and redacting it afterwards would be theatre.
Hints and grading are never returned by either route: being served an item once is not a
reason to be handed its solution.

### Idempotency keys now expire

The table grew by one row per keyed request, forever. A 24-hour TTL, swept on write —
there is nothing to schedule with here, one process and no worker. Past the TTL a key is
not *refused* but simply unknown, so the request runs as new: a client retrying a day later
is not retrying, and "already used" would be a worse answer than doing the work.

Both directions are tested by ageing a row in place rather than sleeping for a day: a stale
key runs again and produces a *different* session, a key one hour old still replays.

### Monaco is no longer a CDN dependency

`@monaco-editor/react` loads the editor from `cdn.jsdelivr.net` at runtime — confirmed by
reading the default out of the loader package. A self-hosted deployment with no egress had
a code workspace that never finished loading, every candidate's editor depended on a third
party staying up, and the version was whatever that package pinned rather than what this
lockfile does.

`scripts/vendor-monaco.mjs` copies the bundle into `public/monaco/vs` at build time,
hooked to `predev` and `prebuild`, idempotent behind a version stamp so an unchanged tree
costs one `readFile` rather than 24MB of I/O. Verified by serving `loader.js`,
`editor.main.js` and `editor.main.css` from `:3000`. It is gitignored — a build artifact of
a dependency the lockfile already pins — and eslint ignores it too, which it announced by
producing 22 errors about vendored code nobody here wrote.

### Coverage

**89% → 90%, 461 → 495 tests**, and the movement that matters is where:

| Module | Before | After |
|---|---|---|
| `api/leetcode.py` | 67% | **97%** |
| the import path (`practice`, `routes/practice`) | untested end to end | 10 db tests |
| `routes/corpus.py` | trivially covered | 12 tests, redaction asserted both ways |

`leetcode.py` was the worst number in the codebase and it was code added hours earlier.
Its tests use a scripted client and never open a socket — a test that reaches leetcode.com
is a test that fails when somebody else deploys — and one of them asserts the **GraphQL
projection asks for no field that could carry a statement**, which is the mechanism the
whole feature's policy standing rests on.

The route now takes its HTTP client as a dependency, like the executor and model clients,
which is what makes that possible.

Two test expectations of mine were wrong and the code was right: the unavailable slug is
`dependency-unavailable`, and a schema failure is **400** here rather than 422, because
FastAPI cannot tell a malformed body from a well-formed invalid one and this API resolves
that toward 400 consistently.

### Coverage, and the number that was lying

The first figure measured was **63%**, from `pytest -q` with the default marker set. The
honest one against the same code is **91%**, because the db-marked tests carry most of what
the fast suite skips — `sessions.py` reads 21% without a database and 92% with one. A
coverage number without its marker set flatters or frightens by accident, so `make coverage`
names the excluded markers in a comment and CI *reports* it rather than enforcing a
threshold. A threshold becomes a number people satisfy; this is meant to be a signal
somebody reads.

**509 Python tests (from 461) and 73 web tests (from 30).** Where the movement went:

| | Before | After |
|---|---|---|
| `api/leetcode.py` | 67% | 97% |
| `cost_report.py` · `mint_session.py` | 0% · 34% | both covered |
| `executor/main.py` guards + startup sweep | 68% | covered without Docker |
| the LeetCode import path | untested | 10 db tests |
| `routes/corpus.py` | new | 12 tests |
| web pages | **none at all** | dashboard, `/session/new`, report, practice, login |

Three of those are worth their own line.

**The web pages are tested with `fetch` stubbed, not `api` stubbed.** That exercises
`lib/api.ts` on every page test — the problem+json parsing, the `401` redirect,
`credentials: "include"` — which is where a page's error handling actually lives. A page
tested against a stubbed `api` object passes while every one of those is broken. `api.ts`
also got its own 14 tests, including that a non-JSON 502 does not turn a gateway error into
a parse error.

**The CLI entry points had no tests and are what somebody reaches for when already stuck** —
`make login` when they cannot get in, `make cost-report` when they want to know what a
session cost. The assertion that matters is not that they work but that they fail *usefully*:
no `SESSION_SECRET` exits 1 with the command to generate one, on stderr, with nothing on
stdout.

**The executor's guards are tested without Docker**, including that neither of them starts a
container — the point of a guard being that nothing runs. The startup reaper is covered too;
it had one definition and zero callers until it was hooked, and now has a test that would
notice if it were unhooked again.

Two of my own test expectations were wrong and the code was right, which is the ordinary
way round and worth recording: the unavailable slug is `dependency-unavailable`, and a
schema failure is **400** here rather than 422, because FastAPI cannot distinguish a
malformed body from a well-formed invalid one and this API resolves that toward 400
everywhere.

### CI caught the same class of bug a second time, from the other direction

Two of those new tests passed locally and failed in CI:

```
FAILED test_every_corpus_route_needs_a_session_cookie - assert 503 == 401
FAILED test_the_import_needs_a_session_cookie        - assert 503 == 401
```

Both assert that an unauthenticated request is refused. Both got `503 not-configured`
instead, because **CI has no `SESSION_SECRET`** and this API fails closed on missing
configuration rather than answering `401` — no credential would help, and a login problem
is not what is wrong. Locally there is a `.env` with a secret, so locally the assertion was
about auth; in CI it was about configuration.

The fix is one line each: `use_settings()` first, so the thing under test is *a configured
server with no cookie*, which is the assertion that was meant. `sign_in` installs that
override as a side effect, which is why every other test in these files was unaffected and
why the gap was invisible.

Worth putting next to yesterday's auth-adoption finding, because it is the same shape
inverted. That one needed a database somebody had logged into — a state **only a real
machine** reaches, which CI structurally cannot. This one needed an environment with
nothing configured — a state **only CI** reaches, which a developer's machine structurally
cannot. Neither environment is a superset of the other, and a test can be wrong in a way
that only one of them can see.

Verified by reproducing CI's condition rather than assuming: `.env` stripped of
`SESSION_SECRET` and the OAuth block, full suite re-run — **509 passed**, including the two
that failed — then `.env` restored.

---

## Phase 6, step 1 — the app runs in containers · 2026-08-25

docs/INFRA.md's ramp starts with Compose and says why: *"see what a container is and how
services find each other on a network."* That was the least of it. Four problems, three of
them nothing to do with networking, and one of them nearly lost the database.

### The compose project name owns the volume

Adding a tidy `name: interview-helper` to the compose file renames the volume with it. The
stack then comes up against an empty `interview-helper_postgres_data` while every session,
evidence row and practice problem sits untouched in the orphaned `compose_postgres_data`.
Nothing is deleted; everything looks deleted.

Caught because the rename also freed port 5432 and the old container was still holding it,
which is luck rather than diligence. There is now no `name:` key and a comment saying why,
and the data was confirmed intact afterwards:

```
sessions=15 users=1 items=48 concepts=159
```

### `apt-get install docker.io` no longer installs docker

On Debian 13 that package provides **only `docker-init`** — no `/usr/bin/docker` at all.
The build was green and every execution returned
`could not launch docker: [Errno 2] No such file or directory`. A build that succeeds while
omitting the single binary the service exists to call is the argument for pinning:
`COPY --from=docker:27-cli`.

### Next bakes its rewrites at build time, so the image cannot be portable

This one changed the design. `next.config.ts` reads `API_ORIGIN` and Next resolves
`rewrites()` into `.next/routes-manifest.json` during `next build` — so an image built on a
laptop carries `http://localhost:8000` regardless of its runtime environment:

```
container env:     API_ORIGIN=http://api:8000
routes-manifest:   /api/:path* -> http://localhost:8000/api/:path*
every request:     ECONNREFUSED 127.0.0.1:8000
```

A build arg would have fixed it by making the image environment-specific, which is the
opposite of what an image is for.

**So the stack grew a `caddy` front door that routes by path** — `/api`, `/auth` and
`/health` to the API, everything else to the web app. That is precisely the job the ALB
does in INFRA.md's target diagram, so compose now *mirrors* the deployed topology instead
of approximating it, the image is portable, and the web app's rewrites are demoted to a
`pnpm dev` convenience. Step 5's portability gate became more meaningful as a side effect
of fixing something else.

Only the front door publishes a port. `api` and `executor` are reachable on the compose
network alone — the same boundary private subnets draw in AWS.

### The executor holds the Docker socket, and the sandbox still isolates

`/var/run/docker.sock` is root-equivalent control of the host, and the executor container
gets it. That is the local model ARCHITECTURE.md settled in Phase 2: a *launcher* that
never evaluates candidate code in-process, holding the socket and no other credential, on a
path that does not survive to Fargate — where there is no socket and the task itself is the
boundary.

It works in a container only because the sandbox passes source on **stdin** and mounts only
`--tmpfs`. A sibling container needs no path from the launcher's filesystem; a bind-mounted
source would have broken here and been a confusing way to find out.

Re-verified against the containerised topology rather than assumed:

```
network egress             DENIED
the docker socket itself   DENIED   ← the sandbox does not inherit its launcher's socket
writing outside /scratch   DENIED
reading /etc/passwd        DENIED
running as root            DENIED
```

The repo's own 31 sandbox tests still pass unchanged.

### Verified

All eight pages 200 through the front door; `/api/v1/mastery` 401 without a cookie and 200
with one, on the same origin; `/health` routed to the API; two-of-two tests passing from
the containerised executor. Images: api 516MB, executor 751MB, web 462MB — the web one
carries 24MB of vendored Monaco, which is the trade for an editor that works without
egress. Both web-facing services run as uid 10001.

### What steps 2–5 need, and it is not code

`aws sts get-caller-identity` reports the session expired, so **step 2 is blocked on
`aws login`**. It is also deliberately a human step — INFRA.md wants the console clicked
once so the Terraform that replaces it is legible, and Terraform written before that would
be code nobody had the context to review. Terraform 1.x is installed and ready.

---

## Phase 6, step 2 (part) — the image is in ECR · 2026-08-25

Credentials arrived, so two things were checked that had been waiting on them.

### The Bedrock gate is unchanged, and now confirmed rather than assumed

`make test-llm` has skipped since Phase 3. With live credentials it still skips, and the
reason it prints is the one docs/COST.md already recorded:

```
bedrock cannot serve us.anthropic.claude-sonnet-4-6:
  404 - Model use case details have not been submitted for this account.
        Fill out the Anthropic use case details form before using the model.
```

Nothing new, and worth the run anyway: it separates "the credentials expired" from "the
form is outstanding", which were indistinguishable before today. Phase 3's last owed item
is a form in the Bedrock console, not code and not access.

### The API image is in ECR

`interview-helper/api`, tagged `854492e` and `latest`, 113 MB compressed against 516 MB on
disk. `scripts/push_image.sh` makes it reproducible — `make push SERVICE=api`.

Two things the script encodes rather than leaves to be rediscovered:

**It refuses a dirty tree.** Every push is tagged with the commit sha, and a tag naming a
commit whose contents were never that commit is worse than no tag. `ALLOW_DIRTY=1` is the
visible exception, in the same style as `ALLOW_UNDOCUMENTED=1`.

**Braces around the variable are load-bearing under zsh.** `$uri:latest` triggers zsh's
`:l` *lowercase modifier* — it pushed to `interview-helper/apiatest` and failed with
"repository does not exist", which reads like a permissions problem and is not one.

### What is deliberately not done

The Fargate service itself. INFRA.md wants the console clicked once so the Terraform that
replaces it is legible, and there is now a second reason: a service bills per second from
the moment it starts, which makes it a spending decision rather than a build step.

Recorded for whoever does it: the images are **arm64** (Apple Silicon), so the task
definition needs `runtimePlatform.cpuArchitecture = ARM64` or the task dies with an
exec-format error. And `/health` needs no database — it answers before RDS exists, which is
what lets step 2 be one task with nothing behind it.

### Step 2's scaffolding, and the one thing left to click

Everything a Fargate service needs *except the service itself* now exists in the account.
All of it was created with the CLI because none of it bills — the split is deliberate:

| Created | Billable |
|---|---|
| `ecsTaskExecutionRole` | no |
| `/ecs/interview-helper-api`, 7-day retention | per GB ingested |
| security group `sg-0def3ce0c872e11be`, tcp/8000 | no |
| cluster `interview-helper` | no, while empty |
| task definition `interview-helper-api:1` | no |
| **the service** | **per second — left to be created by hand** |

Three decisions in the task definition worth having reasons for:

**`cpuArchitecture: ARM64`.** The images are built on Apple Silicon. At the `X86_64`
default the task pulls, starts and dies with an exec-format error, which surfaces as a
service that never stabilises rather than as anything naming the architecture.

**An execution role and no task role.** The execution role is ECS's, for pulling the image
and writing logs. A task role is the container's own AWS identity, and the API needs none
until it calls Bedrock and reads a secret — granting one earlier is a permission nobody
uses.

**No `SESSION_SECRET`.** `/health` answers 200 and every `/api/v1` route answers 503 naming
the variable, which is exactly what step 2 checks. The secret belongs in Secrets Manager,
injected as `secrets` rather than `environment`, and that is step 4. A first deploy that
half-works and says precisely which half is better than one carrying a pasted credential.

`scripts/aws_teardown.sh` was written the same day, not the day it was needed. This
document's argument for IaC is that "you can delete everything and get it back", and that
is only true if deleting everything is one command somebody has run. It orders by
dependency and waits on the ENI release, because a security group deleted too early fails
with a `DependencyViolation` that reads like a permissions problem.

The execution role is deliberately *not* torn down: it is account-wide and may be shared,
and deleting a role something else assumes is a failure that appears later, in another
project, as a task that will not start.

---

## Phase 3 closes — a real interview, for the first time · 2026-08-25

The item this file has carried since 2026-08-20: *"no full session has run against a live
model."* Closed, and not on Bedrock.

### The switch was four lines of `.env`

`MODEL_PROVIDER=anthropic` was built in Phase 3, described in `model_router` as "the escape
hatch", and had never been exercised. Turning it on needed no code:

```sh
MODEL_PROVIDER=anthropic ·  ANTHROPIC_API_KEY=…
MODEL_PLANNER=claude-opus-5      MODEL_INTERVIEWER=claude-sonnet-5
MODEL_GRADER=claude-opus-5       MODEL_UTILITY=claude-sonnet-5
```

It worked first time because `pricing.normalise` already strips the `us.` geo prefix *and*
the `anthropic.` provider prefix, so both id forms price identically. A ledger that
understood one provider's ids would have written `$0` and a warning for every call — the
provider-agnostic normaliser was written months before anything needed it.

### What actually happened

```
turn 1  "can you tell me what the problem is?"
        → "I'd rather hear it from you — can you restate the problem in your own words?"
turn 2  an approach plus code, and a request to run it
        → tool_calls: [run_code] → 11 hidden tests, all passing
        → "All 11 hidden tests pass. Any edge cases you want to double check yourself?"
submit  → graded 1.0 → evidence for 4 concepts → mastery moved
```

The first turn is the one worth keeping. The interviewer **refused to restate the problem**
and turned it back on the candidate — that is the system prompt behaving like an
interviewer rather than a chatbot, and it is the part no scripted provider could ever have
demonstrated.

**$0.0119** for the session. Prompt caching wrote 2,301 tokens once and read them on both
later turns. Coding grading cost nothing — it is hidden tests in a sandbox, not a model.
docs/COST.md carries the per-call table.

### The one test that failed had never run

`make test-llm` came back 1 failed, 2 passed: `cache_write_tokens == 0`, "the breakpoint is
not taking effect". The cache was working perfectly — measured directly against the SDK,
9,212 tokens written on a cold prefix and 9,212 read on the next call.

`FROZEN_PREFIX` is module-level. The ledger test above it runs first, uses the same prefix,
and **warms the cache** — so both of the caching test's calls read a live entry, neither
wrote, and the assertion failed against working code. It could only have passed by running
first, or more than five minutes later.

A test written against a provider nobody could reach, wrong from the day it was written,
and undiscoverable until the day it could run. The prefix now carries a per-run marker, so
it is cold regardless of order.

### And a ledger with $1.20 of fiction in it

`make cost-report` read **65 calls, $1.2696**, which did not match anything that had
happened. 24 of those rows were `model="test-model"` at $0.05 average — inserted by the
`cost_report` test I added earlier today. Its fixture restored the pre-existing rows on
teardown and never deleted the ones the test created, so eight suite runs left eight
copies.

Harmless to the application and not harmless at all to the point of the table: the ledger
is the one thing here whose whole purpose is to be believed. The fixture now clears before
restoring, and the suite was run twice to confirm the ledger is byte-identical afterwards —
**41 calls, $0.0696**, which is the true historical figure.

Second instance today of the same class: a fixture that cleans up *the state it found* but
not *the state it made*.
