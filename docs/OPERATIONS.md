# Operations

> **Status:** Specification, **except local backup/restore — built and drilled
> (2026-08-24), scheduled nightly with retention (2026-08-29), and used for a real
> recovery the same day**. The rest lands in **Phase 8**, though the deployed backup
> pieces become real as soon as Phase 6 deploys.
> Related: [INFRA](INFRA.md) (what is being operated) · [COST](COST.md) (spend alarms) · [SECURITY](SECURITY.md) (incident boundaries)

Running this thing after it exists. Single operator, so the goal is not a formal on-call
rotation — it is that **six months from now you can fix it without re-deriving how it
works.**

## What is actually irreplaceable

Worth being precise, because it determines what backup effort is justified:

| Data | Replaceable? | Consequence of loss |
|---|---|---|
| `concept_evidence` | **No** | Months of graded history. Mastery is derived from it, so losing it resets the entire adaptive engine |
| `sessions`, `turns`, `artifacts` | No | Your transcripts. Also the input if a grader is ever re-run |
| `mastery` | **Yes** — derived | Rebuild with `POST /mastery/recompute` |
| Corpus | Yes — in git | Re-seed from `packages/corpus/` |
| `llm_calls` | Mostly | Cost history; annoying, not fatal |
| Infrastructure | Yes — Terraform | `terraform apply` |

Exactly two tables are irreplaceable. Everything else is derived, in git, or in code.
That is the point of the projection design in
[ADAPTIVE.md](ADAPTIVE.md#evidence-not-scores) — it shrinks the backup problem to
append-only history.

## Backups

### Locally, today

Everything this project knows about one person's mastery lives in a **single Docker
volume** (`compose_postgres_data`) with nothing copying it anywhere. That was true from
Phase 3 and the plan below did not cover it, because the plan is about a deployment that
does not exist yet — so the gap was between "what is written down" and "what is running on
the machine actually holding the data".

```sh
make backup                                     # backups/interview_helper-<stamp>.sql.gz
make restore FILE=backups/… CONFIRM=1           # replaces the database with that file
make backup-schedule                            # launchd runs the dump nightly at 21:00
make backup-unschedule                          # stop scheduling it
```

`CONFIRM=1` is typed out for the same reason `ALLOW_UNDOCUMENTED=1` is: the destructive
thing should be visible in the command that does it. The dump uses `--clean --if-exists`,
so it replays over a populated database — a restore that only works into an empty one is a
restore nobody can perform in the situation they need it.

**Nightly since 2026-08-29.** `make backup-schedule` loads a launchd job
(`com.interview-helper.backup`) that runs the same dump at 21:00; macOS coalesces a
missed run to the next wake, so a laptop closed at 21:00 dumps when the lid opens rather
than skipping the night. Output lands in `backups/backup.log`, dumps prune to the newest
60 (`BACKUP_KEEP`), and `make restore` now dumps the database it is about to replace
before replacing it. The 2026-08-26 buildlog entry ended by calling the missing schedule
the open item, and 2026-08-29 re-proved it: when the volume was recovered that day, its
last write was six hours newer than the newest dump anyone had thought to take.

The dump follows the machine's **daemon pin** (`.docker-context` —
[INFRA](INFRA.md#one-daemon-per-machine)) even under launchd, which knows nothing about
make. Without that, a nightly job on a machine with two Docker daemons archives whichever
database the ambient context points at — including, faithfully and forever, an empty one.

**What survives, measured rather than assumed** — a marker row was written, the stack was
torn down with `make down`, and it was still there afterwards:

| Action | Data |
|---|---|
| Killing `uvicorn` or `next dev` | Safe — both are stateless |
| `make down` then `make dev` | **Safe — verified** |
| `colima stop`, or rebooting the machine | Safe — the volume is on the VM's disk |
| The stack up on a *second* Docker daemon | **Looks destroyed** — intact in the other daemon's volume; pinned and refused since 2026-08-29 ([INFRA](INFRA.md#one-daemon-per-machine)) |
| `docker compose down -v` | **Destroyed** |
| `docker volume rm compose_postgres_data` | **Destroyed** |
| `colima delete`, Docker Desktop "reset" | **Destroyed** |

The last three are one flag or one menu item away from the first three, which is the
argument for `make backup` existing before Phase 6 rather than after it.

### The restore was drilled, not assumed

This document's own rule is that an untested backup is a belief. So, against the live
stack: dump taken, **every session row deleted** (15 → 0), restored, and 15 came back with
the corpus intact and the app still serving. `POST /mastery/recompute` was run afterwards
as step 3 below, and the app answered 200 on every page.

The one thing that drill does *not* prove is the Phase 8 gate below, which diffs a restored
projection against production's. There is no production.

**And then it was performed in anger (2026-08-29).** Docker Desktop, installed two days
earlier, had taken the active context; the stack came up on its daemon against a
brand-new empty volume, and for the third time everything looked deleted. The recovery
was this page's own advice run for real: a raw tar of the orphaned volume before anything
else touched it, a `pg_dump` from a throwaway Postgres started on that volume, then the
stack repointed at the daemon holding the data. 47 applications, 54 stage events and 15
sessions came back intact — nothing had ever been deleted. The full account, and the
guard that ends the failure mode, are in [BUILDLOG](BUILDLOG.md).

### Deployed, later



- RDS automated backups with point-in-time recovery, 7-day window.
- A weekly `pg_dump` to S3 with versioning and lifecycle rules, as a second mechanism.
  One backup system is a single point of failure.

**The restore drill is a Phase 8 gate, not a checkbox.** An untested backup is a belief,
not a backup:

1. Restore the latest snapshot into a scratch database.
2. Point a local API at it.
3. `POST /mastery/recompute` and diff the projection against production's.
4. Record the wall-clock restore time in [BUILDLOG.md](BUILDLOG.md).

Step 3 is the real test. It proves the restored evidence is not merely present but
*sufficient* — that mastery genuinely rebuilds from it.

## Deploy and rollback

- CI builds and pushes images tagged with the commit SHA. **No `latest` tag in
  production** — it makes "what is deployed?" unanswerable.
- Deploy updates the ECS task definition to a new SHA; the service rolls tasks with
  health checks gating the cutover.
- **Rollback is re-pointing at the previous task definition revision.** Practise it once
  in Phase 6 so it is not first attempted during an incident.
- Migrations run as a one-off task *before* the service rolls, and must be
  backward-compatible with the running version — expand, deploy, contract. A migration
  that breaks the old version turns every deploy into an outage.
- **CI runs the chain up, all the way back down, and up again.** A rollback that cannot
  take the schema with it is not a rollback, and developing against a long-lived local
  database only ever exercises the forward direction.

## Monitoring

| Alarm | Threshold | Why |
|---|---|---|
| API 5xx rate | >2% over 5 min | Something is broken |
| Executor unavailable | any | Coding grading stops entirely; the other three graders need no sandbox |
| Grading failure rate | >10% over 1h | Grader bug — **stop and investigate before more evidence is written** |
| Session token budget hit | any | Either a runaway loop or budgets set too low |
| Bedrock spend rate | > daily projection × 2 | Runaway loop; catch in minutes, not at month end |
| AWS Budgets — credits | 50% / 75% / 90% | Credit exhaustion is the project's real cost cliff |
| RDS storage / connections | 80% | Ordinary saturation |

The grading-failure alarm is the one that matters most. A broken grader does not go down
loudly — it writes plausible, wrong evidence, and mastery degrades silently. **When it
fires, stop sessions first and diagnose second.** Bad evidence is expensive to unwind.

## Grader calibration

The other thing that gets worse without failing. Rubric graders drift as prompts and
models change.

- Maintain a held-out set of hand-scored transcripts, one per mode.
- Re-run on every rubric or prompt change, and on every model change, reporting per-
  criterion drift.
- Bump `grader_version` on any change so old evidence stays interpretable.
- Drift beyond a threshold blocks the change.

Corpus refresh runs quarterly as a scheduled Claude Code job
([RESEARCH.md](RESEARCH.md#refresh)) — append-only, reviewed as a diff before merge.

## Runbook

**Grading failures spiking**
Stop new sessions. Check executor health and recent `gradings` rows for a common
`grader_version`. If a grader is at fault, fix it, bump the version, and replay affected
evidence — do **not** hand-edit `mastery`.

**Costs climbing unexpectedly**
`GET /costs` by model and job. Check `cache_read_input_tokens` first: a silent prompt-cache
invalidation is the most likely cause and shows as near-zero cache reads
([COST.md](COST.md#prompt-caching)).

**Executor wedged**
It holds no state, so restart the service. If it recurs, look for a submission that
defeats a limit — then add that case to the escape tests in
[SECURITY.md](SECURITY.md#the-six-escape-tests).

**Mastery looks wrong**
Do not adjust it. Read `GET /mastery/{concept}` to see the evidence behind the number.
Either the evidence is wrong (a grader bug — fix and replay) or it is right and the
number is correct. The projection is never the thing to edit.

**Credits exhausted**
Flip `MODEL_PROVIDER=anthropic` to fail over to the direct API, or stop sessions. The
provider switch is config, not code, precisely so this is a one-line change.

## Cost hygiene

Fargate bills for idle services. Options if this sits unused for stretches: scale the
service to zero tasks between sessions, or accept the floor as the price of always-on.
Decide in Phase 6 against measured numbers rather than guesses — and record the decision
here.
