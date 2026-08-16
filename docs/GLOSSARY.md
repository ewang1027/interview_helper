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
never supply text. Enforced mechanically: any shared 12-gram, or >15% containment of a
source's 8-grams, is a validation error.

**Modality** — which runtime and grader serve an item: `coding`, `quant`, `design`,
`behavioral`. One-to-one with **domain**, which names the body of knowledge
(`coding`, `quant`, `system_design`, `behavioral`).

## Adaptation

**Concept evidence** — an immutable row written by every graded artifact: concept, item,
session, score, confidence, timestamp, grader version. **The source of truth.** Never
updated, never deleted. → [ADAPTIVE](ADAPTIVE.md#evidence-not-scores)

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

**Score anchors** — concrete descriptions of what each score looks like on a rubric
criterion. Without them an LLM grader scores on vibe and drifts between runs.

**Grader version** — stamped on every grading, so evidence stays interpretable after a
rubric or prompt changes.

**Abandoned vs failed** — an abandoned session still writes evidence for what was actually
graded; a failed one writes none. A grader crash must never produce a fabricated score.

## Infrastructure

**Container / image / registry** — the packaged filesystem plus run command; the built
artifact; where built artifacts are stored (ECR on AWS).

**ECS / Fargate** — AWS's container orchestrator, and the mode of it where AWS runs the
container without you owning a VM. → [INFRA](INFRA.md)

**Task / service** — one running set of containers; the thing that keeps N tasks alive.

**VPC / subnet** — your private network, split into public (reachable from the internet)
and private (not). The main security boundary in the design.

**ALB** — the public front door: terminates HTTPS, health-checks tasks, routes traffic.

**Security group** — a per-resource firewall. The executor's has **no outbound rules**,
which is how "the sandbox has no network" is actually enforced.

**IaC / Terraform** — infrastructure as reviewable, diffable, rebuildable files.

## Cost

**Ledger (`llm_calls`)** — one row per model call: tokens in/out/cache, computed dollars,
latency, session, job.

**Model routing** — job-to-model mapping resolved by `ModelRouter`, so call sites never
name a model.

**Prompt caching** — the frozen prefix (system prompt + item context) sits above the
`cache_control` breakpoint. A silent invalidation shows up only as a bill, so CI asserts
non-zero cache reads. → [COST](COST.md#prompt-caching)

**Hard budget** — per-session and per-day token ceilings enforced before the call is made.
On breach the request is **refused**, never silently downgraded.

## Outside terms used narrowly

**Elo** — the chess rating update, applied per concept rather than per player.

**FSRS** — Free Spaced Repetition Scheduler, the spaced-repetition algorithm used for
`stability` and `due_at`.

**SSE** — Server-Sent Events, the one-way streaming channel carrying live session events.

**Vapi** — the voice platform that owns STT, TTS, and turn-taking, calling our
OpenAI-compatible shim as a "custom LLM". → [VOICE](VOICE.md)

**Bedrock** — AWS's model service. Runtime sessions run here so promotional credits absorb
them; research does not, because Bedrock has no server-side web search.
