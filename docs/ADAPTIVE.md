# The adaptive engine

> **Status:** Specification — not built. Lands in **Phase 4**. The weights in the
> priority formula are placeholders to be calibrated against real sessions, not tuned
> values.
> Related: [CONCEPTS](CONCEPTS.md) (the DAG it plans over) · [GRADING](GRADING.md) (where evidence comes from) · [API](API.md#mastery-and-planning) (how it is exposed) · [GLOSSARY](GLOSSARY.md) · [PRACTICE_LOG](PRACTICE_LOG.md) (a second evidence source, and a lighter FSRS-inspired scheduler at problem granularity)

How the system decides what to make you do next.

## The problem with the obvious approach

"Track a percentage per topic and drill the low ones" fails in three ways: it conflates
*never attempted* with *attempted and failed*, it ignores that skill decays, and it has
no notion of an item being too easy to be informative. The design below separates those
into two numbers with different jobs.

## Two numbers per (you × concept)

### `ability` — an Elo rating

Answers **how hard should the next item be**. Both you and each item carry a rating;
a graded outcome updates both, so item difficulty self-calibrates from real results
rather than staying at whatever the corpus author guessed.

```
expected  = 1 / (1 + 10 ** ((item_elo - ability) / 400))
ability  += K * (score - expected)
item_elo -= K_item * (score - expected)
```

- `score` is in [0, 1] — a partial credit outcome, not a binary. A correct answer
  reached with two hints is not the same evidence as one reached with none.
- `K` decays with the number of observations for that concept, so early sessions move
  the estimate quickly and later ones refine it.
- `K_item` is much smaller than `K`. Item ratings should move slowly; with one user,
  they are mostly a prior.

**Selection target:** pick items where expected score is around 0.6–0.75. Below that
you learn little because you fail for uninformative reasons; above it the item confirms
what is already known.

### `stability` / `due_at` — FSRS

Answers **when should I see this again**. Standard FSRS over the concept, driven by the
same graded outcome. Fluency decays; a concept you nailed three months ago is not a
concept you can perform under pressure today.

## Evidence, not scores

Nothing writes directly to `mastery`. Every graded artifact appends:

```
concept_evidence(concept_id, item_id, session_id, score, confidence, ts, grader_version)
```

`confidence` matters because the sources differ in reliability: a hidden-test pass is
near-certain evidence about `two-pointers`; an LLM rubric's read on
`influence-without-authority` is softer. Confidence weights the Elo update.

`mastery` is a projection, rebuildable by replaying evidence in timestamp order. That
gives three things: the engine can explain itself, the rating math can be swapped
without data loss, and a grader bug can be corrected by re-running rather than by
hand-patching state.

From Phase 9, [PRACTICE_LOG](PRACTICE_LOG.md) is a second producer of `concept_evidence`,
for problems solved outside the app. Its own `practice_problems.due_at`/`stability_days`
track a *problem's* re-solve schedule (capped at 3 solves, then graduated) and are
distinct from this concept-level `mastery.due_at`/`stability` despite the shared
vocabulary — the practice log feeds evidence into this engine, it does not replace it.

## Weakness priority

The session planner ranks concepts by

```
priority = w1 * (1 - normalized_ability)      # how weak
         + w2 * recent_error_rate             # how weak *lately*
         + w3 * overdue_ratio                 # how stale
         + w4 * unlocks_count                 # how much it blocks downstream
         - w5 * recent_exposure               # anti-repetition
```

`unlocks_count` uses the concept DAG: a weak prerequisite that gates six other concepts
is worth more than an isolated leaf. `recent_exposure` prevents the planner from
serving the same sore spot five sessions running, which is demoralizing and produces
overfitting to a handful of items.

## Session planning

A session is a **budget** (minutes) and a **mode**. The planner:

1. Takes the top-priority concepts for the requested mode.
2. Selects items whose expected score lands in the informative band.
3. Respects prerequisites — it will not serve `dp-knapsack` while `dp-1d` is weak; it
   serves `dp-1d`. This is the one place the DAG is a hard gate rather than a hint.
4. Keeps a minority of due-for-review items that you are *good* at, so fluency on
   solved material does not rot.

## Cold start

With no history there is no weakness signal. The first few sessions run a **calibration
plan**: spread across domains, starting near the band midpoint, with larger `K` so
estimates move fast. Calibration ends per concept once evidence count crosses a
threshold, not on a fixed session count.

## How this gets verified

The Phase 4 gate is a simulated candidate with an injected weakness: a synthetic user
who scores poorly on a chosen concept cluster and well elsewhere. Within five sessions,
a majority of served items must target that cluster. Plus a replay test — recomputing
`mastery` from `concept_evidence` alone must reproduce the live table exactly.
