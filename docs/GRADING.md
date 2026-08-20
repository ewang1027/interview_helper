# Grading

> **Status:** Partially built. **Working:** `POST /execute` runs a submission against a
> *caller-supplied* list of test cases in the sandbox and returns a count of passes plus a
> record of every *failure* with its kind — passes are counted, not enumerated. It holds
> no corpus and no database, so nothing yet joins an item to its own tests at runtime. The
> **complexity probe** (`executor.complexity`) measures growth against
> `complexity_target`, reachable today only from
> `scripts/verify_reference_solutions.py --complexity`, never from `/execute`. Both run
> over every reference solution in CI, so they are verified rather than trusted.
> **Not built:** scoring (the weighted mix below), hint penalties, the quant answer check,
> every rubric grader, the calibration harness, and the write to `concept_evidence` — so
> no grading has ever produced a score or a row of evidence. Rubric graders land in
> **Phase 3**.
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
2. Run the complexity probe. The item supplies a `complexity_probe` — a deterministic
   `make_input(n)` generator plus ascending `sizes` — and the probe times the solution at
   each size and fits the growth exponent against `complexity_target`. This catches the
   accepted-but-quadratic solution that passes small tests, which is exactly what a real
   interviewer would catch. Three things govern how much a verdict is allowed to mean:
   - **A `complexity_target` with no `complexity_probe` is inert.** Fixed test inputs
     cannot be grown, so nothing is measured. Nothing enforces the pairing — the verifier
     prints a notice and continues.
   - **Bands are measured, not derived, and `inconclusive` is a real verdict that never
     penalises.** `sorted` predicts a 1.09 slope and measures ~1.5 in this sandbox, so
     textbook thresholds would fail correct code. Only `slower_than_target` — a slope
     clearing the band by a 0.35 margin — may count against a submission; an n-log-n
     solution against an O(n) target is never failed.
   - **The generator is where the power lives.** The same naive scan measures 1.28
     ("matches") on random input and 2.03 on adversarial input. Generators must be
     worst-case by construction; simplifying one to `random.randrange` silently disarms
     the check.
3. Score = weighted mix of correctness (dominant), complexity match, and hint penalty.

Test kinds are tagged `example` / `edge` / `stress` / `adversarial`. Failing an
adversarial test is weaker evidence of weakness than failing an example one, and the
confidence on the resulting evidence row reflects that.

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

The answer check is deterministic — sympy equivalence, so `1/3`, `0.333...`, and `2/6`
all pass — with a numeric tolerance fallback and an `accept_forms` list for answers
sympy cannot normalize.

Note before starting that work: **`sympy` is not a dependency of any package in this
workspace** and is not importable in the project venv. The three `exact` strings on disk
(`39`, `149/20`, `16/3`) are trivially parseable, so no content is at risk, but the
grader's first commit has to add the dependency.

But **a correct number with wrong reasoning is not a pass in a quant interview**, so
the derivation is graded against a `reasoning_rubric` too. The two produce separate
evidence: the answer writes evidence against the primary concept, the reasoning
criteria write against whichever concepts they name.

## System design and behavioral

Rubric grading with structured outputs (`output_config.format`), so the result is a
validated object rather than prose to be parsed.

Two requirements on every criterion:

- **Score anchors.** Each criterion should carry `levels` describing what each score looks
  like concretely. Without anchors the grader scores on vibe and drifts between runs.
  **The validator warns rather than errors on a missing `levels`, and the schema does not
  require it** — all nine rubric items on disk carry anchors by author discipline, not by
  enforcement.
- **Citation.** Each judgement must quote the transcript span it is based on. A
  criterion the grader cannot cite is scored as not-demonstrated, not as failed —
  those are different, and only one of them is evidence. **Nothing enforces this yet: no
  rubric grader exists.** It is a requirement on the grader that lands in Phase 3, not a
  property of anything running today.

Weights sum to 1.0; the validator enforces it.

## Hints cost score

Hints are graduated, least to most revealing. Every one the interviewer reveals **is to be
recorded on the turn** — no column for it exists yet; `turns` carries `role`, `content`
and `tool_calls` and nothing hint-shaped — and the score discounted accordingly. A problem solved after
three hints is real evidence — just weaker, and about a lower ability level, than the
same problem solved cold.

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
