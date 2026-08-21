# Operations

> **Status:** Specification — nothing here is exercised yet. Lands in **Phase 8**,
> though the backup and rollback pieces become real as soon as Phase 6 deploys.
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
