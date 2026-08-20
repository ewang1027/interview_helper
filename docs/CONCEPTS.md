# The concept taxonomy

> **Status:** The taxonomy is built and verified (**Phase 0**) — 159 concepts,
> DAG-validated in CI. The planner and adaptive-engine behaviours described below are
> **Phase 4 design, not built**: nothing reads `prereqs` today except the validator, and
> nothing reads `band` at runtime at all.
> Related: [CORPUS](CORPUS.md) (items tag against these) · [ADAPTIVE](ADAPTIVE.md) (mastery is tracked per concept) · [GLOSSARY](GLOSSARY.md)

`packages/corpus/data/concepts.json` is the machine-readable source; this file explains
the rules it follows. **159 concepts** across four domains.

| Domain | Concepts | What it covers |
|---|---|---|
| `coding` | 52 | Data structures, algorithms, and the interview behaviours around them |
| `quant` | 51 | Probability, expectation, stochastic processes, market-making, mental math |
| `system_design` | 37 | Requirements through scaling, plus low-latency topics for quant-dev loops |
| `behavioral` | 19 | STAR delivery, resume defence, motivation |

Bands: 22 foundational · 81 core · 56 advanced.

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
