# The concept taxonomy

> **Status:** The taxonomy is built and verified (**Phase 0**) — **186 concepts**,
> DAG-validated in CI. **Expanded 2026-09-09:** `coding` grew from 52 to 79 concepts, every
> coding concept carries searchable **aliases** (`tags`), and `interval-scheduling` was
> narrowed to make room for two interval concepts beside it — see
> [the expansion](#the-2026-09-09-coding-expansion) below, which also records what happened
> to the evidence already written. The planner and adaptive-engine behaviours described
> below are **Phase 4 design, not built**: nothing reads `prereqs` today except the
> validator, and nothing reads `band` at runtime at all.
> Related: [CORPUS](CORPUS.md) (items tag against these) · [ADAPTIVE](ADAPTIVE.md) (mastery is tracked per concept) · [GLOSSARY](GLOSSARY.md)

`packages/corpus/data/concepts.json` is the machine-readable source; this file explains
the rules it follows. **186 concepts** across four domains.

| Domain | Concepts | What it covers |
|---|---|---|
| `coding` | 79 | Data structures, algorithms, and the interview behaviours around them |
| `quant` | 51 | Probability, expectation, stochastic processes, market-making, mental math |
| `system_design` | 37 | Requirements through scaling, plus low-latency topics for quant-dev loops |
| `behavioral` | 19 | STAR delivery, resume defence, motivation |

Bands: 22 foundational · 93 core · 71 advanced.

## What a concept is

**A concept is a unit of mastery — something you can be separately good or bad at, and
that a graded artifact can produce evidence about.** That test decides what belongs:

- `sliding-window` is a concept: you can be measurably weak at it, and an item can
  measure it.
- "arrays" is not: it is a data type, not a competence.
- `linearity-of-expectation` is a concept even though it is one idea, because it is a
  *distinct failure mode* — people who know it and people who don't produce visibly
  different solutions.

Descriptions are phrased as things you can demonstrate ("Sum expectations of dependent
quantities without touching the joint distribution"), not as topics ("expectation").
The description is what a grader reads when deciding whether evidence applies.

## Prerequisites

`prereqs` means *should be solid before this is drilled*, and forms a DAG — the
validator rejects cycles and dangling references.

It is designed for two uses, **neither built yet** (both Phase 4):
- **Hard gate** in the session planner. It will not serve `dp-knapsack` while `dp-1d`
  is weak; it serves `dp-1d`.
- **Priority weight** in the adaptive engine. A weak concept that unlocks six others
  outranks an isolated leaf.

Today the only consumer of `prereqs` is the validator's cycle and dangling-reference check.

Keep edges to genuine dependencies. `sliding-window` requires `two-pointers` and
`hash-map-counting` because the technique is built from both. It does not require
`comparison-sort` merely because both are "array stuff" — a spurious edge blocks work
for no reason.

## Bands

`foundational` · `core` · `advanced` — a rough tier, advisory only. It seeds cold-start
ordering and nothing else. Difficulty is a property of *items*, not concepts, and the
Elo rating **will supersede** the band once the adaptive engine exists and evidence has
accumulated. Nothing reads `band` at runtime today.

## Stability rules

- **Ids are permanent.** `concept_evidence` rows are keyed on them; renaming one
  silently orphans history. Change `name` and `description` freely; never change `id`.
- **Retire, don't delete.** Set `deprecated_at`. A deprecated concept stops being
  served but keeps its evidence readable.
- **Splitting a concept is a migration**, not an edit. Adding `dp-bitmask` out of
  `bitmask-enumeration` means deciding what happens to existing evidence, and that
  decision belongs in the same commit.
  Done once so far, on 2026-09-09: `interval-scheduling` used to describe merging and
  overlap-counting too, and the two concepts that now own those were added beside it. The
  decision about evidence is below.

## Aliases

Every `coding` concept carries `tags`: the words a person actually has in mind when they
cannot name the concept, which is usually the problem they just solved — `meeting rooms`,
`group anagrams`, `kadane`, `bisect`. The practice log's concept picker searches them
([WEB](WEB.md)), and they are display and search metadata only: nothing classifies on
them, and an alias that names a problem is a pointer to the problem, never its statement.
They exist because a taxonomy phrased as competences (*"Sort by the right endpoint and
sweep"*) is the right thing for a grader to read and the wrong thing to search when what
you know is that you just did *Meeting Rooms II*.

## The 2026-09-09 coding expansion

Asked for directly: *sometimes I can't find the correct tag for a problem — a lot of the
meeting room / interval problems are not under any category.* Checked against the log,
that was true twice over. `interval-scheduling` existed but was named *Interval problems*
and described three different competences at once, so a search for "meeting" found
nothing and *Meeting Rooms*, *Merge Intervals* and *Meeting Rooms II* had been filed under
`prefix-sums` and `two-pointers` by hand. And the 52 coding concepts, written before any
problem was logged, had no home for a good share of what LeetCode and the NeetCode 150
actually ask: Kadane, matrices, number theory, counting sort, palindromes, k-way merge,
sweep line, MST, Bellman–Ford, state-machine DP, minimax, sorted containers.

**27 concepts added**, all `coding`, grouped by what was missing:

| Gap | Added |
|---|---|
| Intervals | `interval-merge` (merge / insert / intersect), `interval-overlap-count` (sweep line, min-heap of end times — meeting rooms II, skyline, car pooling); `interval-scheduling` narrowed to the greedy-by-end-time selection it was always about |
| Arrays | `kadane-running-best`, `constant-space-array-tricks` (cyclic sort, sign-marking, Boyer–Moore), `matrix-manipulation`, `counting-sort-buckets`, `divide-and-conquer` (merge sort, quickselect), `greedy-frontier` (jump game, gas station), `simulation` |
| Strings | `palindromes` (expand around centre), `string-matching` (KMP, Rabin–Karp, Z) |
| Maths | `integer-math` (digits, gcd, modular, fast power, string arithmetic), `coordinate-geometry`, `reservoir-sampling` |
| Trees and heaps | `tree-construction` (build from traversals, serialise), `range-query-structures` (Fenwick, segment tree), `k-way-merge`, `priority-queue-scheduling` (task scheduler, kth-largest stream), `ordered-set-queries` (bisect, sorted containers, calendars) |
| Graphs | `bipartite-coloring`, `state-space-search` (word ladder, multi-source BFS), `minimum-spanning-tree`, `eulerian-path`, `bellman-ford`, `bridges-articulation` |
| DP | `dp-state-machine` (stock with cooldown, hold/not-hold), `minimax-games` |

Each passes the test at the top of this file — a distinct failure mode, phrased as
something you demonstrate — and each has a prerequisite edge only where the technique is
built from the other (`interval-overlap-count` needs `interval-merge` and `heap-top-k`;
`bellman-ford` needs `shortest-path-weighted` and `dp-1d`). The DAG still validates. The
largest domain is now 79, still under the 100-row cap the web app's per-mode ranking
request carries ([WEB](WEB.md)).

**What happened to the evidence.** Every id is unchanged, so nothing was orphaned. But 23
logged problems carried tags chosen against the old taxonomy, eleven of them wrong on
inspection — *Invert Binary Tree* as `graph-bfs`, *Missing Number* as
`binary-search-index`, *Group Anagrams* as plain counting — and each had already written
its immutable `concept_evidence`. The API refuses to re-tag a resolved problem for exactly
that reason. So the correction is a script, `scripts/retag_practice_problems.py`, run once
against a fresh backup with a dry run first: it re-points the evidence rows that carried
the old primary to the new one, leaves their score, confidence and timestamp alone — the
solve happened; only the concept credited was wrong — resolves anything still pending
through the ordinary path, and rebuilds `mastery`. The mapping it was run with is checked
in beside it. [PRACTICE_LOG](PRACTICE_LOG.md#correcting-a-tag-after-its-evidence-is-written)
has the rules for using it again.

## Cross-domain notes

`system_design` carries four low-latency concepts (`network-latency-physics`,
`hot-path-design`, `kernel-bypass-concepts`, `deterministic-replay`) that a general SWE
loop never asks about but a quant-dev loop does. They are in `system_design` rather
than `quant` because they are *system* questions; once the planner exists it will select
by mode, so a SWE-mode session will not reach for them.

`quant` deliberately includes mental arithmetic (`fast-multiplication`,
`fraction-percent-arithmetic`, `log-exp-estimation`). Trading interviews test it under
a clock, it decays without practice, and it is exactly the kind of thing a
spaced-repetition scheduler is good at.
