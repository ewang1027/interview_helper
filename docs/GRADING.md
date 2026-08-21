# Grading

> **Status:** All four graders are **built** — coding and rubric on 2026-08-20, quant on
> 2026-08-21 — so every mode can be created and graded, and `POST /sessions` no longer
> refuses any of them.
> On the coding grader:
> `api.grading.coding` joins an item to its own tests, sends them to the executor's
> `POST /execute`, measures growth through `POST /probe`, folds the two into a score, and
> returns the `concept_evidence` rows that score implies. Verified against real containers
> and the real corpus: the reference solution for `i.code.0002` scores 1.0, a naive
> quadratic submission that **passes every one of that item's tests** is caught by the
> probe alone and scores 0.75, a do-nothing stub scores 0 *with* evidence, and an infinite
> loop is a failed grading with **none**.
> The grader itself stays pure — it returns rows and writes nothing — and the **session
> layer persists them**: a graded submission writes `artifacts`, `gradings` and
> `concept_evidence`, and a failed one writes a `gradings` row with a NULL score and no
> evidence at all.
> On the quant grader: `api.grading.quant` reads the answer out of the candidate's closing
> statement, checks it by sympy equivalence behind a parser wall, and judges the derivation
> against the item's `reasoning_rubric` with the same code system design uses. Verified
> against the real corpus: the three items' exact answers are matched in every spelling the
> corpus lists, a sanity bound after a correct answer does not cost it, and a full quant
> session runs create → submit → grade → evidence.
> **Not built:** the calibration harness, `cpp`, and `peak_rss_kb`.
> Related: [SECURITY](SECURITY.md) (the sandbox code runs in) · [ADAPTIVE](ADAPTIVE.md) (what the evidence feeds) · [API](API.md) (how results reach the client) · [OPERATIONS](OPERATIONS.md) (calibration drift)

Every graded artifact produces one thing: `concept_evidence` rows. Everything else —
the score you see, the report, the next session's plan — is downstream of those.

Implemented in Phase 2 (deterministic) and Phase 3 (rubric and quant).

## The four graders

| Modality | Grader | Determinism |
|---|---|---|
| Coding | Hidden tests in the sandbox + empirical complexity probe | Fully deterministic |
| Quant | Symbolic/numeric answer check + reasoning rubric | Answer deterministic, reasoning LLM |
| System design | Multi-criterion LLM rubric, each criterion cited to a transcript span | LLM, structured |
| Behavioral | STAR-completeness + specificity rubric, same citation requirement | LLM, structured |

**No LLM decides code correctness.** Tests do. A model's opinion of whether code works
is not evidence about `two-pointers`; a passing hidden test is.

## Coding

1. Run the submission against every test in the sandbox.
2. Run the complexity probe. The item supplies a `complexity_probe` — a deterministic
   `make_input(n)` generator plus ascending `sizes` — and the probe times the solution at
   each size and fits the growth exponent against `complexity_target`. This catches the
   accepted-but-quadratic solution that passes small tests, which is exactly what a real
   interviewer would catch. The sweep runs under a ~20s process-time budget, and the
   driver stops growing n — keeping the points it has, which still judge at three — rather
   than start a size the budget cannot afford: the slow submission is the one being
   measured, so timing the probe out on it would hand `inconclusive` to exactly the case
   the probe exists for. Three things govern how much a verdict is allowed to mean:
   - **A `complexity_target` with no `complexity_probe` is inert.** Fixed test inputs
     cannot be grown, so nothing is measured. Nothing enforces the pairing — the verifier
     prints a notice and continues, and a grading says so in its `detail` rather than
     leaving the reader to assume the growth was checked.
   - **Bands are measured, not derived, and `inconclusive` is a real verdict that never
     penalises.** `sorted` predicts a 1.09 slope and measures ~1.5 in this sandbox, so
     textbook thresholds would fail correct code. Only `slower_than_target` — a slope
     clearing the band by a 0.35 margin — may count against a submission; an n-log-n
     solution against an O(n) target is never failed.
   - **The generator is where the power lives.** The same naive scan measures 1.28
     ("matches") on random input and 2.03 on adversarial input. Generators must be
     worst-case by construction; simplifying one to `random.randrange` silently disarms
     the check.
3. Score = `correctness x complexity_retention x hint_retention`, all in [0, 1].

**Correctness is a multiplier, not a term in a sum**, and that is a correction to how
this was originally specified. A weighted sum of correctness and complexity hands a
quarter of the marks to a submission that fails every test and returns instantly —
`return []` is O(1). So complexity and hints can only ever *discount* what correctness
earned, and a submission that earned nothing scores zero however fast it was:

| Factor | Value | Why |
|---|---|---|
| `correctness` | passed / total | The only term that puts points on the board |
| `complexity_retention` | `0.75` on `slower_than_target`, else `1.0` | Solved, at the wrong cost. Larger than any single hint: shipping the wrong algorithm is worse than needing a nudge |
| `hint_retention` | product of `1 - penalty` over hints taken, penalties `0.05, 0.10, 0.15, 0.20` | Fractions of what is still on the table, so no number of hints can drive a score negative |

The probe is **skipped entirely when nothing passed** — against a zero it can only
confirm the zero, at the cost of a 60-second sandbox run.

Evidence rows carry the same score for every concept the item names, with the primary
concept at full confidence (`0.9` — a hidden test passing is a fact) and the others at
`0.6` of it, since an item is *chiefly* a measurement of one concept.

Test kinds are tagged `example` / `edge` / `stress` / `adversarial`. Failing an
adversarial test is weaker evidence of weakness than failing an example one, and the
confidence on the resulting evidence row reflects that: confidence is `0.9` scaled by the
mean softness of the cases that *failed* (`example` 1.0 → `adversarial` 0.6). The kinds
move confidence, never the score — two submissions that each got one case wrong score the
same, and differ only in how hard that reading is allowed to move mastery.

The asymmetry is deliberate and worth stating: a **full pass** is `0.9` whatever the suite
looked like. Passing a trivial all-example suite should arguably claim less, but every
item on disk carries ten or more cases across every kind, so it is not a live risk — and
guessing at a correction nothing can measure yet would be the same mistake the complexity
bands avoided.

**Reference solutions are verified in CI**, not trusted — every item's *Python* reference
solution runs against every one of its tests, through the same `executor.harness` driver a
candidate's submission gets, plus `--strict-stub-check` (a do-nothing stub must fail) and
`--complexity`. The validator separately enforces that a reference solution *exists* for
every declared language, but **only Python is executed**: the verifier skips other
languages with a notice rather than failing, so a `cpp` solution that did not compile
would pass CI today. The corpus declares Python only, so nothing is currently unverified.
Borrowed from `learning_files`,
where several graders would have shipped broken on the strength of a confident report:
re-run the graders, don't believe the claim.

## Quant

*Built 2026-08-21.* `api.grading.quant`. The answer check is deterministic — sympy
equivalence, so `1/3`, `0.333...` and `2/6` all pass — and **a correct number with wrong
reasoning is not a pass in a quant interview**, so the derivation is graded against the
item's `reasoning_rubric` by the same code system design uses. The two produce separate
evidence: the answer writes against the primary concept, the reasoning criteria write
against whichever concepts they name. A concept named by both is measured twice, by two
instruments, and both readings are real.

**The answer is read from the closing statement, not from the page.** Every real derivation
mentions numbers that are not the answer — an intermediate value, a sanity bound, the naive
figure the problem exists to refute. `i.quant.0001` is exactly this: the answer is 39 and
the derivation says 27 out loud. So the grader takes the line the candidate *declared* their
answer on (`Answer:`, `Final answer:`), or failing that the last line containing arithmetic
at all, and matches any expression on it. Both halves of that matter: scanning the whole
page would accept the decoy, and taking only the last expression would fail "39 presses,
which must exceed 27" — a correct answer punished for being checked.

**A stated answer and no answer are different.** A candidate who never committed to a number
has not got it wrong; they have not answered. That scores zero on the answer half and writes
**no evidence**, on the same reasoning that keeps a not-demonstrated rubric criterion silent.

| Factor | Value | Why |
|---|---|---|
| `answer` | `1.0` or `0.0` | Symbolically equal to the item's answer, or not |
| `reasoning` | the weighted `reasoning_rubric` | The same judgement, citation check included, that grades a design answer |
| weighting | `0.4 × answer + 0.6 × reasoning` | Below half on purpose: this is the arithmetic that makes a bare correct number *not a pass*. The reverse is deliberate too — a sound derivation with a slipped digit keeps most of what the reasoning earned, which is how an interviewer scores it, and the rubric's own arithmetic criterion already docks the wrong value |
| `hint_retention` | the same schedule as every other grader | |

An item with no `reasoning_rubric` — the schema makes it optional — is graded on the number
alone. Dividing by a half that does not exist would cap every such item at 0.4.

**Confidence has two tiers.** A declared answer carries `0.9`, the same as a hidden test
passing, because a symbolic equivalence is a fact. An answer *read out of* a closing
sentence carries `0.75`: the check is equally deterministic, but which expression it was
pointed at was inferred, and a mis-read is a wrong verdict about a right answer.

**A decimal is accepted at the precision it was written to** — `5.33` for `16/3`, provided
it carries at least three significant figures, so `5` is not a correct rounding of
everything. This is how a person reads it, and refusing it would write evidence of a
weakness the candidate does not have, which is the failure this grader is most able to
cause. `tolerance` still applies as an absolute band, and `accept_forms` covers what sympy
cannot normalise — a mixed number, a currency figure — matched as bounded text and tried
*last*, because an equivalence sympy proved is a stronger thing to be right about than a
substring of a sentence.

**sympy parses untrusted text, so it is walled first** ([SECURITY.md](SECURITY.md#the-answer-parser)).

Known and accepted: with no declaration and no other arithmetic below it, a trailing sanity
bound is read as the answer. There is nothing in the text that distinguishes a check from a
claim, and a test pins the behaviour rather than leaving it to be discovered.

## System design and behavioral

*Built 2026-08-20.* `api.grading.rubric` grades an artifact against its item's rubric with
structured outputs (`output_config.format`), so the result is a validated object rather
than prose to be parsed — the response schema even enumerates the item's own criterion ids,
so a judgement of something not on the rubric cannot be expressed.

Two requirements on every criterion, both now enforced rather than hoped for:

- **Score anchors.** Each criterion should carry `levels` describing what each score looks
  like concretely. Without anchors the grader scores on vibe and drifts between runs. The
  anchors are sent **verbatim** in the request rather than summarised into it, and a test
  asserts that. **The validator still warns rather than errors on a missing `levels`**, so
  the grader copes: an unanchored criterion is sent with an instruction to judge
  conservatively, and it says so rather than pretending anchors were there.
- **The scale is the criterion's, not the grader's** (corrected 2026-08-21). The corpus
  does not fix one anchor scale: `system_design` and `behavioral` anchor on 0/2/4, and every
  quant reasoning rubric anchors on 0/1/2/3. The grader read a hardcoded maximum of 4, which
  would have scored a *perfect* three-point derivation at 0.75 and written evidence of a
  weakness that was an artefact of the grader — silently, since nothing about the number
  looks wrong. Full marks is now the criterion's own top anchor; the response schema
  reports that maximum so the model is never invited to a level no anchor describes; and a
  level above the scale is clamped, because `maximum` is an instruction to the provider and
  not a guarantee from it. A criterion with no anchors at all falls back to the widest
  scale, so a conservative judgement lands low on a wide scale rather than high on a narrow
  one the grader invented.
- **Citation.** Each judgement must quote the span it is based on — **and the quote is
  checked against the artifact.** Whitespace and case are forgiven, because a model that
  reflows a quotation has still quoted it; anything else is not. A citation that is not in
  what the candidate wrote is a fabrication, and the criterion is demoted. This is the one
  control separating "the model read the answer" from "the model wrote a plausible review
  of an answer".

**Not-demonstrated is not failure.** A criterion nobody addressed scores zero — you cannot
be credited for what you did not do — and writes **no evidence at all**, because silence
says nothing about ability. Recording it as failure would tell the adaptive engine you are
weak at something it never observed, and that is a lie that compounds.

Rubric evidence carries a confidence of **0.5** against a deterministic result's 1.0. A
model's read of prose is real evidence and a weaker claim than a hidden test passing, and
docs/ADAPTIVE.md's Elo update is weighted by exactly that number.

Weights sum to 1.0; the validator enforces it.

## Hints cost score

Hints are graduated, least to most revealing, and cost `0.05, 0.10, 0.15, 0.20` of the
remaining score in order — the schedule `api.grading.coding.hint_penalty` exposes, so
[API.md](API.md#sse-event-stream)'s `hint.revealed` can report the price at the moment it
is paid rather than in the report afterwards. Items with more hints keep paying the last,
steepest rate. Taking all four leaves 58% of what was earned.

The grader applies the schedule, and **the hints are now recorded** (2026-08-20). This
document called a column owed; there is none. `reveal_hint` writes a `turns` row carrying
the tool, the item and the level, and grading counts the highest level that session took on
that item. The turns are already the authoritative account of what happened in a session,
and a second place to record it is a second place to disagree with the first.

A problem solved after three hints is real evidence — just weaker, and about a lower
ability level, than the same problem solved cold.

## Grader versioning and calibration

Every `gradings` row records `grader_version`. When a rubric or prompt changes, the
version bumps, and old evidence stays interpretable.

LLM graders **will get** a calibration harness (not built, and blocked on transcripts
existing): a held-out set of hand-scored transcripts, re-run on every prompt change,
reporting drift per criterion. This is the check on the
one part of the system that can silently get worse without anything failing.

## Failure is a failure

A grader that crashes, times out, or returns unparseable output is a **failed grading**
whose message is the stderr tail — never a silent pass and never a default score. A
missing grade is visible; a fabricated one corrupts mastery permanently.

**That rule reaches past the grader itself**, and the code had to be corrected to match it.
Anything raised *after* a grade is computed — the evidence insert, the projection update —
used to roll the `gradings` row back along with it. The result was worse than a wrong
score: the item reported `"grading"` forever, the session could never complete, and a
retry was refused with `409` because the submission already existed. The client had its
`202` and never learned. Every path through `grade_artifact` now ends in a row, written
through a fresh transaction because the original one may already be poisoned.
