# The research pipeline

> **Status:** Specification — **not built, and already partly bypassed.** `research/` is
> empty; no stage below has ever run. Phase 1's 36-item thin slice on disk was authored
> directly by Claude Code agents working from `CORPUS.md`'s checklist, skipping
> sweep/extract/cluster/rank entirely and recording no `research_runs` row. This remains
> the design for **bulk** authoring toward the ~400/~150 target, which has not started.
> Related: [CORPUS](CORPUS.md) (what a good item is) · [CONCEPTS](CONCEPTS.md) (the taxonomy it tags against) · [COST](COST.md) (why this runs on the Max plan)

[CORPUS.md](CORPUS.md) defines *what* a corpus item must be. This file defines *how* items
get made — the pipeline that turns "no seed bank" into a validated question corpus.

## Where it runs, and why that matters

The pipeline runs as **Claude Code sessions on your machine**, not as a deployed service
and not through the API. It reads the web, writes JSON into `packages/corpus/data/items/`,
and commits.

Three consequences, all deliberate:

- **It costs nothing.** Research is the token-expensive half of this project, and the Max
  subscription covers Claude Code. Moving it to build time is the single largest cost
  decision in the design (see [COST.md](COST.md)).
- **It needs web search**, which Bedrock does not offer as a server-side tool. Runtime
  runs on Bedrock; research runs where the tools are.
- **Its output is reviewable.** A research run produces a diff you read before merging,
  not a side effect inside a running system.

## The five stages

```
  sweep ──▶ extract ──▶ cluster ──▶ rank ──▶ author
    │          │           │          │         │
  queries   candidate   archetypes  evidence  instances
  per       patterns    (dedup)     density   (original
  domain    + sources               ordering   prose)
                                               │
                                               ▼
                                          validate ──▶ commit
```

### 1. Sweep

Per domain, run a set of query templates against the web. The goal is *breadth of
independent attestation*, not depth on any one page — an archetype is only interesting if
several unrelated sources say it gets asked.

Query families per domain (each instantiated with role, firm type, and year):

| Domain | Families |
|---|---|
| coding | interview experience writeups; "asked in {firm} interview"; pattern taxonomies; new-grad and intern loop reports |
| quant | trading interview question compilations; brainteaser collections with attribution; mental-math and market-making game descriptions; firm-specific loop writeups |
| system_design | design interview breakdowns; scaling case studies; low-latency and exchange-adjacent design discussions |
| behavioral | competency frameworks; firm value statements; interview-loop descriptions naming behavioral rounds |

Record every query and the URLs it returned, whether or not they were used. A run that
found nothing is a useful record — it prevents re-running the same dry sweep next quarter.

### 2. Extract

From each source, pull **candidate patterns**, not problems. A candidate is a short
description of what is being asked, plus a paraphrased note on why this source counts as
evidence.

The extraction step is where the originality discipline starts. Never copy a problem
statement into the pipeline, not even as a working note — see the originality rule below.

### 3. Cluster into archetypes

Group candidates that are the same underlying question wearing different clothes. "Two
sum," "find the pair summing to k," and "does any pair add to the target" are one
archetype. Clustering is the step that converts a pile of scraped questions into a
taxonomy with real coverage.

**Novelty is used here and nowhere else** — purely as a dedup filter. A candidate that
matches an existing archetype merges into it, adding a source rather than creating a new
entry.

### 4. Rank by evidence density

Order archetypes by **how many independent sources attest them**, weighted by recency.

```
density = Σ over distinct registrable domains of (recency_weight × source_quality)
```

- **Distinct registrable domains only.** Five pages on one aggregator is one source.
- **Recency weight** decays over roughly three years; interview patterns shift.
- **Source quality** is a coarse tier — a first-hand loop writeup outranks a listicle.

**The model never scores importance or novelty as a ranking signal.** This follows the
finding that drove `signal-forge`: LLM-judged novelty correlates *negatively* with real
impact, so ranking on it actively selects for worse material. Evidence density is a
count, not an opinion, which is exactly why it is the ranking key.

### 5. Author instances

Take the top-ranked archetypes and write concrete, gradeable problems against them, to
the checklist in [CORPUS.md](CORPUS.md#authoring-checklist-phase-1).

**Authoring is the expensive step**, so it is deliberately downstream of ranking: effort
goes to patterns that are demonstrably asked, not to whatever the sweep happened to
surface first.

Per modality, an instance is not done until:

- **coding** — reference solution written *and executed* against every test, including
  the adversarial ones. A reference solution that has not been run is a guess.
- **quant** — the answer derived independently of the source, with the derivation kept as
  the reasoning rubric.
- **design / behavioral** — criteria carry concrete score anchors, not adjectives.

## The originality rule, restated as a process constraint

**Statements are original prose. Sources justify the archetype; they never supply text.**

The validator is only a partial backstop, and it matters to know exactly what it does not
do: it shingles the statement against each source's own `evidence` note — *your
paraphrase* — because it runs offline with no copy of the page. Any shared 12-gram, or
>15% containment of an evidence note's 8-grams, is an error. **A statement copied verbatim
from a live URL passes this check cleanly.**

So the process rule below is not a supplement to mechanical enforcement — it *is* the
enforcement:

> Read sources to learn *that a pattern is asked*, then close them and write the problem
> from the pattern.

Writing while looking at a source produces near-copies that trip the validator at best
and slip through paraphrased at worst. The `evidence` field is a paraphrase of *why this
source attests the pattern* — pasting a problem statement there will fail validation on
the very item it was meant to support, which is the intended behaviour.

## Provenance: `research_runs`

Every run is *to* record a row so the corpus can be audited and re-run. **Not built, and
the shape below is not the shape that shipped:** the `research_runs` table exists with
three JSONB columns — `searched`, `added`, `deprecated` — so the fields below describe
what must be packed into those, not columns you can query. Nothing has ever written a row.

| Field | Contents |
|---|---|
| `run_id`, `started_at`, `ended_at` | When |
| `domains` | Which domains were swept |
| `queries` | Every query issued, with result counts |
| `sources_seen` | All URLs encountered, used or not |
| `archetypes_added`, `archetypes_merged` | What clustering did |
| `instances_authored` | What was written |
| `items_deprecated` | What this run retired, and why |
| `validator_result` | Errors and warnings at commit time |

This is the record that makes "why is this question in the corpus?" answerable months
later.

## Refresh

Append-only. Items retire by setting `deprecated_at`; nothing is deleted, because a
deleted item orphans the `concept_evidence` rows that reference it (see
[ADAPTIVE.md](ADAPTIVE.md#evidence-not-scores)).

Refresh runs quarterly as a scheduled Claude Code job. A refresh may:

- add sources to an existing archetype (raising its density),
- add archetypes that have newly accumulated evidence,
- deprecate archetypes whose evidence has gone stale,
- **never** silently rewrite an existing statement — an edit that changes what an item
  measures is a new item.

## Failure modes to expect

| Symptom | Reading | Response |
|---|---|---|
| Archetype has only one independent source | Might be one blogger's pet question | Hold it out of the corpus; the validator will reject it anyway |
| Many sources, all quoting one original | Aggregator echo, not independent attestation | Registrable-domain dedup catches most; spot-check the top-ranked |
| Validator flags originality on a careful write-up | Likely wrote while looking at the source | Rewrite from the pattern, not from the page |
| Sweep returns mostly listicles | Query family is too generic | Add firm and role qualifiers; prefer first-hand loop reports |
| A domain yields far fewer archetypes than the others | Real signal about that domain, or bad queries | Record it in `research_runs` and revisit next refresh — do not pad the corpus to hit a number |

That last row is the important one. **The corpus is allowed to be uneven.** Inventing
items to balance a table produces questions nobody is asked, which is worse than a thin
domain honestly labelled.

## Phase 1 gate

- Validator passes with zero errors.
- Every archetype cites ≥2 independent sources with retrieval dates.
- Every coding instance's reference solution passes its own hidden tests **in CI**, not
  on an author's claim.
- Originality check clean.
- Human spot-check: read 10 random instances and confirm they read like real interview
  questions rather than textbook exercises.
