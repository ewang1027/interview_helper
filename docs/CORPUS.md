# The corpus and how it gets built

> **Status:** Contract built and enforced (**Phase 0**) — schema and validator ship with
> tests. A **thin Phase 1 slice is authored and verified**: 3 archetypes and 6 instances in
> every one of the four domains (widened 2026-08-21). Every coding reference solution passes
> its own tests in a real sandbox and measures inside its declared complexity band; every
> quant answer was checked twice, by exact reasoning and by simulation. **Design and
> behavioral items carry no comparable check** — nothing executes a rubric, so the validator
> and a careful reading are the whole of it, and each has been graded once against a
> scripted model only to prove that it grades at all. Bulk authoring toward the ~400/~150
> target has not started.
> Related: [RESEARCH](RESEARCH.md) (how items get made) · [CONCEPTS](CONCEPTS.md) (what they tag against) · [GRADING](GRADING.md) (what the grading contracts mean) · [GLOSSARY](GLOSSARY.md) · [PRACTICE_LOG](PRACTICE_LOG.md) (why its ingestion is manual-entry-only, not URL-fetch)

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
published books) stay out of this repo.

| Check | Threshold | Level |
|---|---|---|
| Shared word run with a source's `evidence` | any 12-gram | error |
| Containment of a source's `evidence` 8-grams in the statement | > 15% | error |

**Be precise about what this actually enforces.** The validator runs offline and has no
copy of the source page, so it compares the statement against the item's own
`sources[].evidence` field — *the author's paraphrase*, not the source text. That catches
an author who pastes problem text into their evidence note, and nothing else. **A
statement copied verbatim from a live URL passes this check cleanly.**

So the originality rule is enforced by *process*, not by the validator: read sources to
learn that a pattern is asked, close them, and write the problem from the pattern. The
shingle check is a backstop against one specific slip, not a guarantee. Treating it as
proof of originality would be exactly the false confidence this project keeps trying to
avoid. (The check's error message used to read "overlaps N% of source `<url>` text", which
described a comparison that never happened; it now names the evidence note.)

Closing the gap properly means storing a snapshot of each source's text at research time
and shingling against that. That is real work — fetching, storing, and licensing
third-party text the repo is otherwise careful not to hold — and it is deferred, not
solved.

A `sources[].evidence` field is a *paraphrase* of why the source attests the pattern.
Pasting a problem statement in there will trip the originality check on the very item
it was meant to support, which is the intended behaviour.

[PRACTICE_LOG](PRACTICE_LOG.md) (Phase 9) stays clear of this rule by construction
rather than by exemption: it only ever stores a problem's `title`, its `url` (a
pointer, never dereferenced), and your own notes — never the problem statement text
itself, so there is nothing for the originality check to apply to.

## Validator checks

Run `make corpus-validate`. All eight must pass:

1. JSON Schema conformance for concepts and items.
2. Concept graph is a DAG with no dangling prerequisites.
3. Item concept references resolve; `primary_concept` is among `concepts`.
4. Every instance points at an archetype that exists.
5. At least two independent sources per item.
6. Originality — the two shingle thresholds above.
7. Grading contract matches modality; coding items ship a reference solution for every
   language they declare; criterion weights sum to 1.0, criterion ids are unique, and any
   `concept` a criterion names resolves. This applies to **both** `rubric.criteria` and a
   quant item's `reasoning_rubric` — the weight check originally lived in the rubric
   branch alone, so a reasoning rubric summing to 0.8 validated cleanly and silently
   scaled every score derived from it.
8. Domain and modality agree. They are 1:1 (`coding`→`coding`, `system_design`→`design`,
   …), and a mismatch would route an item to a grader that cannot grade it. Added during
   the Phase 0 self-review and never added to this list until an audit caught it.

Several further error-level checks are enforced but not itemised above, because they are
structural rather than editorial: duplicate item id, duplicate concept id, an archetype
setting `archetype_id`, an instance with no grading contract, and `answer` grading with
neither `exact` nor `numeric`.

Two checks are **warnings** rather than errors, because each is occasionally the right
editorial choice and neither corrupts anything on its own:

- **A criterion with no `levels`.** An LLM grader without anchors scores on vibe and drifts
  between runs; the grader copes by saying so ([GRADING.md](GRADING.md#system-design-and-behavioral)).
- **A rubric that names its item's `primary_concept` nowhere** (added 2026-08-21). An item's
  rating moves on the attempt's first evidence row naming that concept
  ([ADAPTIVE.md](ADAPTIVE.md#two-numbers-per-you-concept)), so a rubric that never names it
  writes no such row and the rating stays at the author's prior however many times the item
  is attempted — and a rating that never moves looks exactly like a well-calibrated one.
  Quant items are exempt: their answer writes that row whatever the reasoning rubric names.

  **The corpus validates clean.** `i.design.0003` was the one instance — its four criteria
  named every concept the item lists *except* `rate-limiting`, the one it is chiefly a
  measurement of — and it was fixed by authoring rather than by retagging, because the
  criterion nearest to `rate-limiting` was already tagged correctly. See the buildlog wave;
  the short version is that the gap in the rubric and the gap in the tagging turned out to
  be the same gap.

Checks 2–8 each have a test in `packages/corpus/tests/test_validate.py` proving the check
*catches* its failure, not merely that it passes. **Check 1 is the exception: JSON Schema
conformance is covered only by `test_schema_accepts_the_real_concepts`, a pass-only test.**
No test feeds a schema-violating record and asserts an error comes back. A validator that
only ever passes is indistinguishable from no validator, so a negative schema test is owed
— and the gap sitting one line under that sentence is exactly how these things survive.

Alongside the errors above the validator raises **warnings**, which print and exit 0: an
item tagging a `deprecated_at` concept, a concept tagged outside the item's own domain, a
reference solution for an undeclared language, and a criterion with no `levels` anchors.
They are a review prompt, not a gate.

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

Refresh is *designed* to run as a scheduled Claude Code job so it stays on the Max plan,
recording a `research_runs` row per run for provenance: what was searched, what was added,
what was deprecated. **Neither exists yet** — there is no scheduled job, the table is
migrated but empty, and the 27 items on disk were authored by hand-launched agents and by
hand, with no provenance row written for any wave.

## Authoring checklist (Phase 1)

For each archetype:
- [ ] ≥2 independent sources, each with a retrieval date and a paraphrased evidence note
- [ ] Tagged to concepts that exist in the taxonomy
- [ ] A primary concept that is genuinely what the item measures

For each instance:
- [ ] Statement written from scratch, not adapted from a source
- [ ] Coding: ≥3 tests including edge and adversarial cases; reference solution passes
      all of them in CI; complexity target stated **together with a `complexity_probe`
      whose generator is worst-case by construction** — a target with no probe is inert,
      since fixed test inputs cannot be grown, and a random generator lets the very defect
      the probe exists for walk straight through (measured: a naive scan reads 1.28 on
      random input and 2.03 on adversarial). Probe `sizes` are bounded on both ends: the
      largest run must clear ~0.2ms of real work (below that, interpreter noise judges
      instead of the algorithm), and an impostor one class slower than the target must
      still land **three sizes** inside the probe's ~20s budget on a machine several
      times slower than yours — CI's runners measured ~2–3M simple loop iterations/s, and
      oversized sweeps come back `inconclusive` there (measured: [4000…32000] escaped the
      quadratic impostor on CI that [1000…8000] catches)
- [ ] Coding: **the `complexity_target` string decides how much protection the probe gives
      you.** `O(n log n)` lands in the linearithmic band, whose ceiling plus margin is 2.10
      — wide on purpose, so a genuine n-log-n solution is never failed, and wide enough
      that a quadratic impostor measuring 2.00 comes back `inconclusive` rather than
      caught (measured on `i.code.0006`). When the log factor is over a *value* range and
      not over n — a binary search on the answer, most often — say so: `O(n log M)` reads
      as linear in n, which is what the probe actually varies, and the same impostor is
      then called at 2.01 against a 1.65 threshold. Check the target you wrote by running
      an impostor through `make verify-solutions`, not by reading the band table
- [ ] Quant: exact and/or numeric answer, tolerance, plus a reasoning rubric — a right
      number with wrong reasoning is not a pass in a real quant interview
- [ ] Design/behavioral: ≥3 criteria with score anchors, weights summing to 1.0
- [ ] Graduated hints, least to most revealing
- [ ] Follow-ups for when the main problem lands early
