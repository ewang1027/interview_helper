# The corpus and how it gets built

> **Status:** Contract built and enforced (**Phase 0**) — schema and validator ship with
> tests. **Zero items authored so far**; that is **Phase 1**.
> Related: [RESEARCH](RESEARCH.md) (how items get made) · [CONCEPTS](CONCEPTS.md) (what they tag against) · [GRADING](GRADING.md) (what the grading contracts mean) · [GLOSSARY](GLOSSARY.md)

The corpus is the question bank. It is **researched and authored at build time** by
Claude Code running on your machine, and committed as versioned JSON under
`packages/corpus/data/`. Nothing at runtime generates an item.

## Why build-time

| | Build-time corpus | Runtime generation |
|---|---|---|
| Reproducibility | Same item every time; diffs are reviewable | Different every session |
| Grading | Tests and rubrics authored once, verified in CI | Grader invented alongside the question, unverified |
| Cost | Paid once, on the Max plan | Paid per session, on the API bill |
| Failure mode | A bad item is a bug you can fix and re-run | A bad item is a bad session you cannot reproduce |

## Two tiers

**Archetype** — a recurring interview pattern, attested by at least two independent
sources. "Expected value of a stopping-rule game." "Design a rate limiter." An
archetype has no tests; it is a claim that this pattern is really asked, plus the
evidence for that claim.

**Instance** — a concrete, gradeable problem realizing an archetype. Original
statement, hidden tests or an answer key or a rubric, a reference solution, concept
tags, seed difficulty. Every instance must point at an archetype; the validator
enforces it. Without that rule the corpus drifts into a pile of one-off problems with
no attested pattern behind them.

## Ranking: evidence density, not model opinion

Archetypes are ranked by **how many independent recent sources attest them**, not by
asking a model to rate novelty or importance. This follows the finding that drove
`signal-forge`: LLM-judged novelty correlates *negatively* with real-world impact, so
ranking on it actively selects for worse material. Novelty is demoted to a dedup
filter.

"Independent" means distinct registrable domain. Two pages on the same site are one
source.

## The originality rule

**Statements are original prose. Sources justify the archetype, never supply the text.**

This is not a soft preference — proprietary problem statements (LeetCode, HackerRank,
published books) stay out of this repo. The validator enforces it mechanically:

| Check | Threshold | Level |
|---|---|---|
| Shared word run with a source | any 12-gram | error |
| Containment of a source's 8-grams in the statement | > 15% | error |

A `sources[].evidence` field is a *paraphrase* of why the source attests the pattern.
Pasting a problem statement in there will trip the originality check on the very item
it was meant to support, which is the intended behaviour.

## Validator checks

Run `make corpus-validate`. All seven must pass:

1. JSON Schema conformance for concepts and items.
2. Concept graph is a DAG with no dangling prerequisites.
3. Item concept references resolve; `primary_concept` is among `concepts`.
4. Every instance points at an archetype that exists.
5. At least two independent sources per item.
6. Originality — the two shingle thresholds above.
7. Grading contract matches modality; coding items ship a reference solution for every
   language they declare; rubric weights sum to 1.0.

Each check has a test in `packages/corpus/tests/test_validate.py` that proves it
*catches* the corresponding failure. A validator that only ever passes is
indistinguishable from no validator.

## Layout

```
packages/corpus/
├── schema/
│   ├── concept.schema.json
│   └── item.schema.json
└── data/
    ├── concepts.json          # the taxonomy — one file, it is a single graph
    └── items/
        ├── coding.json        # sharded per domain so research runs don't collide
        ├── quant.json
        ├── system_design.json
        └── behavioral.json
```

## Refresh

Append-only. Items are retired by setting `deprecated_at`, never deleted — deleting one
would orphan the `concept_evidence` rows that reference it.

Refresh runs as a scheduled Claude Code job, so it stays on the Max plan. Each run
records a `research_runs` row for provenance: what was searched, what was added, what
was deprecated.

## Authoring checklist (Phase 1)

For each archetype:
- [ ] ≥2 independent sources, each with a retrieval date and a paraphrased evidence note
- [ ] Tagged to concepts that exist in the taxonomy
- [ ] A primary concept that is genuinely what the item measures

For each instance:
- [ ] Statement written from scratch, not adapted from a source
- [ ] Coding: ≥3 tests including edge and adversarial cases; reference solution passes
      all of them in CI; complexity target stated
- [ ] Quant: exact and/or numeric answer, tolerance, plus a reasoning rubric — a right
      number with wrong reasoning is not a pass in a real quant interview
- [ ] Design/behavioral: ≥3 criteria with score anchors, weights summing to 1.0
- [ ] Graduated hints, least to most revealing
- [ ] Follow-ups for when the main problem lands early
