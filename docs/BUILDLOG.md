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
| `apps/api/src/api/models.py` | All 15 tables from ARCHITECTURE's data model, plus the two practice-log tables |
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
- **pgvector is installed in the container and the extension is created, but no table has
  an embedding column.** Semantic retrieval lands with the code that needs it.

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
