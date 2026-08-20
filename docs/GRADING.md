# Grading

> **Status:** The **coding grader is built and verified end to end** (2026-08-20).
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
> **Not built:** the quant answer check, both rubric graders, the calibration harness,
> `cpp`, and `peak_rss_kb`. Hint penalties are implemented but nothing *records* hints yet
> (`turns` has no hint column), so the count is an argument the caller supplies.
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

Hints are graduated, least to most revealing, and cost `0.05, 0.10, 0.15, 0.20` of the
remaining score in order — the schedule `api.grading.coding.hint_penalty` exposes, so
[API.md](API.md#sse-event-stream)'s `hint.revealed` can report the price at the moment it
is paid rather than in the report afterwards. Items with more hints keep paying the last,
steepest rate. Taking all four leaves 58% of what was earned.

The grader applies the schedule; **nothing records the hints yet**. `turns` carries
`role`, `content` and `tool_calls` and nothing hint-shaped, so the count arrives as an
argument from the caller and the column is owed with the session layer. A problem solved
after three hints is real evidence — just weaker, and about a lower ability level, than
the same problem solved cold.

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
