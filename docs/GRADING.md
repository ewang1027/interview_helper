# Grading

> **Status:** Partially built. Working: `POST /execute` runs a submission against an
> item's tests in the sandbox and reports pass/fail per case with its kind; the
> **complexity probe** measures growth against `complexity_target`; and reference
> solutions are verified in CI against both, rather than trusted. **Not built:** scoring
> (the weighted mix below), hint penalties, the quant answer check, every rubric grader,
> and the write to `concept_evidence` — so no grading has ever produced a score or a row
> of evidence. Rubric graders land in **Phase 3**.
> Related: [SECURITY](SECURITY.md) (the sandbox code runs in) · [ADAPTIVE](ADAPTIVE.md) (what the evidence feeds) · [API](API.md) (how results reach the client) · [OPERATIONS](OPERATIONS.md) (calibration drift)

Every graded artifact produces one thing: `concept_evidence` rows. Everything else —
the score you see, the report, the next session's plan — is downstream of those.

Implemented in Phase 2 (deterministic) and Phase 3 (rubric).

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
2. Run the complexity probe: execute at increasing *n* and fit the growth curve against
   `complexity_target`. This catches the accepted-but-quadratic solution that passes
   small tests — which is exactly what a real interviewer would catch.
3. Score = weighted mix of correctness (dominant), complexity match, and hint penalty.

Test kinds are tagged `example` / `edge` / `stress` / `adversarial`. Failing an
adversarial test is weaker evidence of weakness than failing an example one, and the
confidence on the resulting evidence row reflects that.

**Reference solutions are verified in CI**, not trusted. Every declared language's
reference solution must pass every test for that item. Borrowed from `learning_files`,
where several graders would have shipped broken on the strength of a confident report:
re-run the graders, don't believe the claim.

## Quant

The answer check is deterministic — sympy equivalence, so `1/3`, `0.333...`, and `2/6`
all pass — with a numeric tolerance fallback and an `accept_forms` list for answers
sympy cannot normalize.

But **a correct number with wrong reasoning is not a pass in a quant interview**, so
the derivation is graded against a `reasoning_rubric` too. The two produce separate
evidence: the answer writes evidence against the primary concept, the reasoning
criteria write against whichever concepts they name.

## System design and behavioral

Rubric grading with structured outputs (`output_config.format`), so the result is a
validated object rather than prose to be parsed.

Two requirements on every criterion:

- **Score anchors.** Each criterion carries `levels` describing what each score looks
  like concretely. Without anchors the grader scores on vibe and drifts between runs.
- **Citation.** Each judgement must quote the transcript span it is based on. A
  criterion the grader cannot cite is scored as not-demonstrated, not as failed —
  those are different, and only one of them is evidence.

Weights sum to 1.0; the validator enforces it.

## Hints cost score

Hints are graduated, least to most revealing. Every one the interviewer reveals is
recorded on the turn, and the score is discounted accordingly. A problem solved after
three hints is real evidence — just weaker, and about a lower ability level, than the
same problem solved cold.

## Grader versioning and calibration

Every `gradings` row records `grader_version`. When a rubric or prompt changes, the
version bumps, and old evidence stays interpretable.

LLM graders get a calibration harness: a held-out set of hand-scored transcripts,
re-run on every prompt change, reporting drift per criterion. This is the check on the
one part of the system that can silently get worse without anything failing.

## Failure is a failure

A grader that crashes, times out, or returns unparseable output is a **failed grading**
whose message is the stderr tail — never a silent pass and never a default score. A
missing grade is visible; a fabricated one corrupts mastery permanently.
