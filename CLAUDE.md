# Working in this repo

Two rules govern every change here, and both exist because this project's value is that
its documents can be trusted. A doc that describes something which does not exist is worse
than no doc, and work that lives only in one working tree is work that does not exist.

**1. Documentation travels with the code, in the same commit.**
**2. Commit at every checkpoint, and push after every commit.**

The rest of this file is what those mean concretely, and which parts a script enforces.

## 1. Documentation travels with the code

A unit of work is not done until its documentation is. The doc change belongs in the
**same commit** as the code — a follow-up commit is a promise, and the failure mode this
repo keeps finding is that nothing collects on it.

### Which doc owes an update

| A change to | Owes |
|---|---|
| **anything whose behaviour differs** | `docs/BUILDLOG.md` — a wave entry, or a line in the open one |
| a phase's state | `docs/BUILDLOG.md`'s table **and** README's build status — a gate compares them |
| an endpoint, its contract, its errors | `docs/API.md` |
| the schema or a migration | `docs/ARCHITECTURE.md` (data model) |
| a grader, a score, what it writes as evidence | `docs/GRADING.md` |
| rating maths, scheduling, priority, the planner | `docs/ADAPTIVE.md` |
| the sandbox, isolation, an escape test | `docs/SECURITY.md` |
| the corpus schema, a validator check, item shape | `docs/CORPUS.md`; the taxonomy, `docs/CONCEPTS.md` |
| model routing, budgets, the ledger | `docs/COST.md` |
| a `make` target, a CI step, a gate | README's quick start, and the doc that owns the gate |
| a term used in more than one place | `docs/GLOSSARY.md` |
| a `Settings` field | `.env.example` — a test compares them |
| a new doc | README's documentation table — a gate compares them |

### The rules that keep the set coherent

- **`docs/BUILDLOG.md` is the only document that always describes reality.** If any other
  doc disagrees with it about what exists, the other doc is wrong and gets fixed.
- **Record what was verified, not what was written.** If something is unverified, say so.
  If a gate was skipped, say that too. "Built" means something that runs proved it.
- **Every doc opens with `> **Status:**`** — one line telling a reader how much of what
  follows exists. It is the first thing to update and the first thing to go stale.
- **Corrections stay.** A claim this repo got wrong is kept alongside the fix, because the
  reason it was wrong is usually the most useful sentence on the page.
- **The phase table's state column is a controlled vocabulary** — `complete`, `built`,
  `partial`, `not started` — with the nuance in prose after a dash. The verdict has to sit
  somewhere a script can read; the sentence after it is for a human.

### What a script checks, and what it cannot

`make doc-check` (also in CI) compares claims that exist in two places: every doc carries
a status header, README's table indexes exactly the docs on disk, README's build status
and the buildlog's phase table agree phase by phase, a doc claiming to be built is not
indexed as a specification, and "Where things stand" is not older than the newest entry
under it. `make doc-links` proves every internal link and anchor resolves.

The pre-push hook refuses a push whose commits change code — `apps/`, `packages/`,
`scripts/`, `infra/`, `hooks/`, `.github/`, the `Makefile`, `pyproject.toml` — and no
`.md` file. The gates are on that list deliberately: every commit in this repo's history
that changed code and documented nothing was a change to a gate.

None of that can check whether a document is **true**. That is the rule above, and it is
kept by reading.

## 2. Commit at every checkpoint, push after every commit

Commit when a feature or fix is complete and working, before starting a risky refactor,
when wrapping up a session even mid-progress, and at least every 20–30 minutes of
substantive work. Push after every commit — never end a session with unpushed work, and
never let a backlog of unpushed commits build up.

Subject lines take a type prefix: `feat:` `fix:` `update:` `refactor:` `docs:` `chore:`
`test:` `wip:`. Say what changed and why it matters, not which files moved — the history
here reads as a sequence of findings, and that is worth keeping.

Before pushing: `make check`, plus whichever heavier gate the change touches —
`make test-db` (live Postgres), `make test-sandbox` (real Docker), `make test-e2e`,
`make verify-solutions`. A gate you did not run is a gate you cannot cite.

**`wip:` is exempt from the documentation gate.** A checkpoint commit is not a unit of
work, so mark it `wip:` and the hook lets it through. For the rarer case of a real commit
that genuinely owes no documentation, the exception is typed out where it is visible:

```sh
ALLOW_UNDOCUMENTED=1 git push
```

`make hygiene` (the tail of `make check`) reports what is uncommitted and what is
unpushed. It never fails — a nudge that can break a build gets deleted.

## Orientation

`docs/GLOSSARY.md` → `docs/ARCHITECTURE.md` → `docs/BUILDLOG.md`. The glossary defines the
vocabulary the others assume; the buildlog is the one to trust.
