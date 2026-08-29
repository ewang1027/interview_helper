# Glossary

> **Status:** Current. Updated as terms are introduced.

Project vocabulary in one place. Several of these are ordinary words used in a narrow
sense here, which is exactly when a glossary earns its keep.

## Content

**Concept** — a unit of mastery: something you can be separately good or bad at, and that
a graded artifact can produce evidence about. `sliding-window` is a concept; "arrays" is
not, because it names a data type rather than a competence. Ids are permanent because
evidence is keyed on them. → [CONCEPTS](CONCEPTS.md)

**Archetype** — a recurring interview *pattern*, attested by at least two independent
sources. Carries no tests. It is a claim that this pattern is really asked, plus the
evidence for the claim. → [CORPUS](CORPUS.md)

**Instance** — a concrete, gradeable problem realizing an archetype. Original statement,
tests or answer key or rubric, reference solution, concept tags. Every instance must point
at an archetype.

**Item** — an archetype or an instance. The corpus contains items.

**Evidence density** — the ranking signal for archetypes: how many independent sources
attest one, weighted by recency. A count, not an opinion, which is the whole point.
→ [RESEARCH](RESEARCH.md#4-rank-by-evidence-density)

**Independent sources** — sources on distinct registrable domains. Five pages on one site
are one source.

**Originality rule** — statements are original prose; sources justify the archetype and
never supply text. Upheld primarily by *process*: read the source, close the tab, write
from the pattern. The validator is a backstop, not a guarantee — it shingles the statement
against the item's own `sources[].evidence` **note**, not the live page, so **a statement
copied verbatim from a URL passes cleanly.** Thresholds: any shared 12-gram, or >15%
containment of the evidence note's 8-grams, is an error.
→ [CORPUS](CORPUS.md#the-originality-rule)

**Modality** — which runtime and grader serve an item: `coding`, `quant`, `design`,
`behavioral`. One-to-one with **domain**, which names the body of knowledge
(`coding`, `quant`, `system_design`, `behavioral`).

## Adaptation

**Concept evidence** — an immutable row written by every graded artifact: concept, item,
session, score, confidence, timestamp, grader version. **The source of truth.** Never
updated, never deleted. It has **three producers**, distinguished by `source`: session
grading (`item_id` + `session_id` set), the interviewer's mid-session observations
(`interviewer_observation`, same columns, lowest confidence), and the practice log
(`practice_problem_id` set). `item_id`/`session_id` are nullable and a CHECK constraint
requires exactly one of `item_id`/`practice_problem_id`. Only a grading moves an item's
rating; the other two are not attempts at it. → [ADAPTIVE](ADAPTIVE.md#evidence-not-scores)

**Mastery** — a *derived projection* over evidence, recomputable from scratch. Never
hand-edited. When it looks wrong, the evidence is wrong.

**Ability** — an Elo rating per concept answering *how hard should the next item be*.
Items carry ratings too, so difficulty self-calibrates from outcomes.

**Stability / due_at** — FSRS state answering *when should I see this again*. Separate
from ability because fluency decays independently of whether you ever understood it.

**Confidence** — how much a piece of evidence should move the estimate. A hidden-test pass
is near-certain; an LLM rubric's read on a soft skill is not. Weights the Elo update.

**Weakness priority** — the planner's ranking: weak, weak *lately*, overdue, blocking
downstream concepts, minus recent exposure.

**Informative band** — the expected-score window (~0.6–0.75) the planner targets. Below
it you fail for uninformative reasons; above it the item only confirms what is known.

**Calibration plan** — the cold-start session plan used before enough evidence exists to
detect weakness.

## Practice log

**Practice problem** — an external (LeetCode/Codeforces) problem you logged manually
after solving it: title, URL, notes, and a taxonomy classification. Never stores the
problem's own statement text. → [PRACTICE_LOG](PRACTICE_LOG.md)

**Review queue (practice log)** — practice problems that are `active` and past their
`due_at`, ranked most-overdue first — the problem-level analog of the planner's
weakness ranking. → [PRACTICE_LOG](PRACTICE_LOG.md#rest-endpoints-and-state-machine)

**Graduation (practice log)** — a practice problem leaving the review queue for good
after being solved 3 times; `due_at` is cleared and it is never prompted again.
→ [PRACTICE_LOG](PRACTICE_LOG.md#spaced-re-solve-scheduling)

## Job applications

**Application** — one company/role pair you applied to, tracked in `job_applications`.
Writes no `concept_evidence` and moves no mastery, deliberately ([JOBS](JOBS.md)).

**Stage** — where an application stands. Seven **ladder** stages in order — `applied`,
`oa`, `phone_screen`, `round_1`, `round_2`, `final`, `offer` — and three **terminal** ones
off the ladder: `rejected`, `withdrawn`, `ghosted`. Terminal stages are deliberately
unranked; ranking them would count every withdrawal as progress.

**Furthest stage** — the highest ladder rung an application ever reached, as opposed to
`current_stage`, where it is now. The funnel counts this one, so a rejection after an onsite
still counts as an onsite reached. Counting the funnel off `current_stage` instead would
make it improve every time something went badly.

**Stage event** — an append-only row in `job_application_events`. The events are what
happened; the three stage columns on the application are a projection over them, in the same
sense `mastery` is a projection over `concept_evidence`.

**The parse** — the Sonnet 5 structured call that turns a pasted list into tagged rows
(`job="job_parse"`). Runs on every import.

**The research pass** — the Opus 5 call with the **web search** tool that completes a long
list from the real postings (`job="job_research"`). Runs only above
`JOBS_RESEARCH_THRESHOLD` rows, cannot cost the import when it fails, and does not exist on
Bedrock.

**Category / sub-category** — two levels of tagging: `swe` · `ai` · `quant` · `other`, and a
sub-category under each. The model picks only the sub-category and the category is derived
from it, so an inconsistent pair is unrepresentable.

## Execution and the sandbox

**Sandbox vs executor** — `apps/executor` is the *service*; the **sandbox** is the
throwaway container it launches per execution. `executor.sandbox` decides *how safely*
something runs (the Docker flags); `executor.harness` decides *what* runs and what the
result means, and is importable without Docker. Under Fargate the task itself becomes the
boundary — `run_sandboxed` is the seam where that swaps.

**Escape test** — one of the six tests in `apps/executor/tests/test_sandbox_escape.py` that
must **fail closed**: network egress, filesystem escape, PID exhaustion, memory bomb,
wall-clock timeout, cross-execution contamination. Three of the six were re-run against a
deliberately weakened sandbox to prove they can fail; a seventh sanity control guards the
opposite error, where a sandbox so broken it runs nothing makes every escape test pass.

**Outcome / `is_gradeable`** — every `/execute` run returns an `outcome`: `ok`, `timeout`,
`out_of_memory`, `pid_limit`, `compile_error`, `harness_error`. **Only `ok` is gradeable.**
A timeout is a *failed grading*, never a 0/3 — scoring one would write evidence of weakness
against a concept the candidate may know perfectly well.

**Result marker** — the `##LEARN-RESULT ` prefix the in-sandbox driver prints its JSON
verdict on. The **last** marker line wins, and the driver flushes then `os._exit(0)`s, so
neither candidate output printed earlier nor an `atexit` handler can be mistaken for the
result.

**Complexity probe** — runs a solution at increasing *n* and fits the growth exponent
against `complexity_target`. Inert without a `complexity_probe` on the item, since fixed
test inputs cannot be grown.

**Adversarial generator** — a `complexity_probe.generator` that builds its input **worst-case
by construction**, never randomly. Measured: a naive backward scan slopes 1.28 on random
input (passes) and 2.03 on ascending (caught). The probe's power is in the generator, not
the curve fit.

**`inconclusive`** — the probe's third verdict, beside `matches` and `slower_than_target`.
Returned whenever the data is too thin to judge or the target has no measured band. Only
`slower_than_target` may count against a candidate (`ProbeResult.penalises`).

## Runtime

**Session** — one mock interview: a mode, a time budget, a plan, a transcript, and the
gradings that come out of it.

**Mode** — which of the four interview surfaces a session runs.

**Turn** — one exchange in the interviewing loop, including any tool calls the agent made.

**Plan** — what the planner chose for a session, returned before the session starts.
Visible by design; opaque adaptation is untrustworthy adaptation.

**Complexity probe** — running a coding submission at increasing *n* and fitting the
growth curve against the item's target. Catches the accepted-but-quadratic solution that
passes small tests.

**Principal** — who a request is, as proved by its session cookie's signature: a user id
and the GitHub id it belongs to, and nothing read from the database. Every `/api/v1` route
takes one; services take the `user_id` out of it rather than resolving "the current user"
themselves. → [API](API.md#auth)

**Session cookie** — `ih_session`: a user id, a GitHub id and an expiry under HMAC-SHA256.
Signed, not encrypted, and carrying nothing secret. Note the collision with **session**
above, which is an interview — the cookie is a login, and it outlives many of them.

**Allowed account** — `GITHUB_ALLOWED_ID`, the one GitHub account id this deployment
serves. Anyone else completes OAuth successfully and is refused `403`: authentication says
who you are, and this is the part that says who that has to be.

**Score anchors** — concrete descriptions of what each score looks like on a rubric
criterion. Without them an LLM grader scores on vibe and drifts between runs.

**Grader version** — stamped on every grading, so evidence stays interpretable after a
rubric or prompt changes.

**Not demonstrated** — a rubric criterion the candidate never addressed, or one whose
citation is not in what they wrote. Scores zero and writes **no evidence**: you cannot be
credited for what you did not do, and silence says nothing about ability. Distinct from
failing a criterion, which is evidence. → [GRADING](GRADING.md#system-design-and-behavioral)

**Abandoned vs failed** — an abandoned session still writes evidence for what was actually
graded; a failed one writes none. A grader crash must never produce a fabricated score.

## Infrastructure

**Container / image / registry** — the packaged filesystem plus run command; the built
artifact; where built artifacts are stored (ECR on AWS).

**Daemon pin** — `.docker-context`, a machine-local gitignored file naming the Docker
daemon this checkout's data lives on. Exported as `DOCKER_CONTEXT` by every make target,
read directly by the backup script, enforced by `scripts/daemon_guard.sh`.
→ [INFRA](INFRA.md#one-daemon-per-machine)

**ECS / Fargate** — AWS's container orchestrator, and the mode of it where AWS runs the
container without you owning a VM. → [INFRA](INFRA.md)

**Task / service** — one running set of containers; the thing that keeps N tasks alive.

**VPC / subnet** — your private network, split into public (reachable from the internet)
and private (not). The main security boundary in the design.

**ALB** — the public front door: terminates HTTPS, health-checks tasks, routes traffic.

**Security group** — a per-resource firewall. The executor's **will have** no outbound
rules, which is how "the sandbox has no network" becomes infrastructure-enforced in
Phase 6. No AWS resource exists yet; today it is enforced by `docker run --network none`
and verified by an escape test.

**IaC / Terraform** — infrastructure as reviewable, diffable, rebuildable files.

## Cost

**Ledger (`llm_calls`)** — one row per model call: tokens in/out/cache, computed dollars,
latency, session, job. Written in its own transaction, so a caller failing afterwards
cannot erase the record of money already spent.

**Model routing** — job-to-model mapping resolved by `ModelRouter`, so call sites never
name a model. It resolves the per-job `effort` too, and omits it for a model family that
would reject the parameter.

**Inference profile** — the `us.`-prefixed Bedrock model id (`us.anthropic.claude-sonnet-4-6`)
that routes a request across a region group. Current models are only callable this way; the
undecorated `anthropic.`-prefixed id answers "does not exist" or demands a profile.
→ [COST](COST.md#what-actually-runs-today)

**Prompt caching** — the frozen prefix (system prompt + item context) sits above the
`cache_control` breakpoint. A silent invalidation shows up only as a bill, so an
`llm`-marked test asserts that a repeated identical prefix reports non-zero cache reads —
run by `make test-llm`, not in CI, which has no credentials.
→ [COST](COST.md#prompt-caching)

**Hard budget** — the per-session and per-day token ceilings in `.env.example`. A breach
**refuses** the request (`429 budget-exceeded`) rather than silently downgrading it, and
refuses before the provider is called. Enforced by `api.llm` since 2026-08-20; every token
counts toward it, cache reads included, and the daily ceiling resets at UTC midnight.
→ [COST](COST.md#hard-budgets)

## Outside terms used narrowly

**Elo** — the chess rating update, applied per concept rather than per player.

**FSRS** — Free Spaced Repetition Scheduler, the spaced-repetition algorithm used for
`stability` and `due_at`.

**SSE** — Server-Sent Events, the one-way streaming channel carrying live session events.
Built 2026-08-20; `api.events.EventBus` assigns the sequence numbers and holds a bounded
per-session buffer, in this process's memory.

**`stream.gap`** — what the stream sends a client that reconnects from before the buffer
starts: what it asked for, what is still available, and the instruction to refetch. A
client that cannot tell it lost events is worse off than one handed an error.

**Vapi** — the voice platform that owns STT, TTS, and turn-taking, calling our
OpenAI-compatible shim as a "custom LLM". → [VOICE](VOICE.md)

**Bedrock** — AWS's model service. Runtime sessions run here so promotional credits absorb
them; research does not, because Bedrock has no server-side web search.
