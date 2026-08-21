# The adaptive engine

> **Status:** Built (2026-08-20), and verified against both gates at the end of this
> document. `api.mastery` holds Elo `ability` and FSRS `stability`/`due_at`;
> `api.priority` ranks concepts by the formula below; `api.planner` turns that ranking
> into a session, and every plan carries the reasoning behind each item it chose.
> `POST /mastery/recompute` rebuilds the whole projection — item ratings included — from
> `concept_evidence` alone.
> **The weights below are still placeholders**, to be calibrated against real sessions.
> Two limits are structural at 24 items rather than defects: the prerequisite gate usually
> has nowhere to send you (no item measures `stack-simulation`), and with one item per
> concept the informative band cannot influence *which item* is served — only which
> concept.
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
  the estimate quickly and later ones refine it. As built: `K = max(10, 48 / (1 + n/8))`,
  and it never reaches zero — skill decays, and an estimate that stops moving stops being
  a measurement.
- `K_item` is much smaller than `K`. Item ratings should move slowly; with one user,
  they are mostly a prior. As built: `4`.
- **Both updates are scaled by the evidence's `confidence`**, so a hidden-test pass moves
  a rating further than a soft signal about the same concept would.
- **An item's rating moves once per attempt, not once per concept.** One graded
  submission writes one evidence row per concept the item names — four, for the coding
  items on disk — so the item update is tied to the *primary* concept's row. Without that
  tie, an item drifted four times faster for the crime of naming four concepts.
- **And once per attempt means once, even when several rows name that concept**
  (corrected 2026-08-21). Tying the update to the primary concept's row was the same thing
  as tying it to one row per attempt *only while one row per concept was the only evidence
  shape there was*. The quant grader writes a deterministic row for the answer and a rubric
  row per criterion, and a criterion may name the primary concept too — `i.quant.0002`
  produces three rows naming `expected-value-decision`, and all three moved the rating: the
  same drift the rule above fixed, arriving by a different route. The row that moves an item
  is now the attempt's **first**, in the `(ts, id)` order `recompute` replays in, so the
  live path and a rebuild agree by construction rather than by coincidence.
- **An item whose rubric never names its primary concept never moves at all** — the mirror
  image of the same assumption, and a corpus-shape question rather than a projection bug. So
  **the validator warns** about it ([CORPUS.md](CORPUS.md#validator-checks)) instead of the
  projection guessing at a concept the author did not choose. `i.design.0003` was the one
  instance and is fixed; the corpus validates clean. Quant items are exempt: their answer
  writes that row whatever the reasoning rubric names.

A concept with fewer than five observations is flagged `calibrating`, and the API says so
rather than presenting an estimate built on one data point as if it were settled.

**Selection target:** pick items where expected score is around 0.6–0.75. Below that
you learn little because you fail for uninformative reasons; above it the item confirms
what is already known.

**A new concept starts at 1550, not at 1200.** That is the median instance rating in the
corpus, and starting at chess's 1200 was measured doing real damage: every item sat 300–600
points above a new candidate, the expected score against a median item was 0.12, nothing
was ever inside the band above — and a candidate who scored 0.2 had *beaten* a 0.09
expectation, so **failing an item repeatedly raised their rating on it**. A simulated
candidate who failed `monotonic-stack` five times finished rated higher on it than on the
concepts they never got wrong. It is a fixed constant rather than a median computed at
import, because a starting rating that moved with the corpus would change what a replay of
old evidence produces.

### `stability` / `due_at` — FSRS

Answers **when should I see this again**. FSRS over the concept, driven by the same
graded outcome. Fluency decays; a concept you nailed three months ago is not a concept you
can perform under pressure today.

Built on the `fsrs` package (FSRS-6) rather than hand-rolled arithmetic — spaced
repetition parameters are fitted, not derived, and inventing constants that *look* like
FSRS would be a claim nothing could check. Two settings are load-bearing:

- **Fuzzing off.** The library jitters each interval by default so schedules feel less
  mechanical. Measured here: six identical reviews of an identical card produced six
  different due dates. Under a design whose central claim is "the projection rebuilds from
  the evidence", that is the difference between a replay test that means something and one
  that cannot pass.
- **No learning steps.** FSRS ships flashcard defaults that re-show a card after one
  minute and ten minutes. A concept in a mock interview is not re-drilled sixty seconds
  later; that interval would leave every concept permanently overdue.

A score is continuous and FSRS takes one of four grades, so the mapping is stated rather
than buried: `< 0.5` Again, `< 0.75` Hard, `< 0.95` Good, else Easy. Confidence does
**not** scale the schedule — FSRS takes a grade, and a fractional review is arithmetic
nobody could check.

## Evidence, not scores

Nothing writes directly to `mastery`. Every graded artifact appends:

```
concept_evidence(id, concept_id, source, item_id, session_id,
                 practice_problem_id, score, confidence, ts, grader_version)
```

`confidence` matters because the sources differ in reliability: a hidden-test pass is
near-certain evidence about `two-pointers`; an LLM rubric's read on
`influence-without-authority` is softer. Confidence weights the Elo update.

`mastery` is a projection, rebuildable by replaying evidence in timestamp order. That
gives three things: the engine can explain itself, the rating math can be swapped
without data loss, and a grader bug can be corrected by re-running rather than by
hand-patching state.

**Applying evidence is serialised by a Postgres advisory lock**, taken before the evidence
rows are written so their timestamps are stamped inside the critical section. Two gradings
really do overlap — `grade_artifact` runs in a threadpool, one per submission — and
without the lock two transactions read the same rating, each add their delta, and one is
lost: the evidence row survives, its effect does not, and the replay above stops agreeing
with the live table. Measured before the lock existed, two concurrent gradings that shared
a concept raised `UniqueViolation` on `mastery`'s primary key.

**Item ratings are part of that projection.** `items.difficulty_elo` holds the author's
prior and `items.elo` is what real outcomes made of it, so `recompute` resets the second
to the first and replays. A rebuild that reset only half the state would produce a table
no replay could reproduce.

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
   **As far as the corpus allows:** substituting toward a concept no item measures would
   plan a session with nothing in it, so an unserveable prerequisite is reported in the
   plan and the original concept is kept. At 24 items that is the common case.
4. Keeps a minority of due-for-review items that you are *good* at, so fluency on
   solved material does not rot. At most one per session — a session is about what you
   are bad at, and review is the seasoning. **The slot is reserved before the weakness
   pass fills the budget**, because a greedy fill always leaves less than one item's worth
   behind: considered afterwards, the review slot was unreachable rather than merely rare.
   It was unreachable twice over — its "good at it" floor was expressed on the normalised
   scale rather than in Elo, which put it 260 points above where a concept starts and made
   it first reachable on a candidate's 55th consecutive success.

Ties in priority are broken by **distance from the informative band**, which is what makes
a cold start sensible: with nothing measured, every concept scores identically, and
without that tie-break the first session is decided by whichever concept id sorts first
alphabetically. Measured: it served an item the candidate was expected to score 0.43 on
while an item sitting on the band's edge went unserved.

## Cold start

With no history there is no weakness signal. The first few sessions run a **calibration
plan**: spread across domains, starting near the band midpoint, with larger `K` so
estimates move fast. Calibration ends per concept once evidence count crosses a
threshold, not on a fixed session count.

## How this gets verified

The Phase 4 gate is a simulated candidate with an injected weakness: a synthetic user
who scores poorly on a chosen concept cluster and well elsewhere. Within five sessions,
a majority of served items must target that cluster. **Built, and it needed strengthening
before it meant anything.** The first version passed while proving nothing: for want of a
tie-break the planner served that item in session one, before any evidence existed, so the
majority was satisfied by a default rather than by adaptation. It now also requires that
the *first* session not be the weak item, and that the engine end up rating that concept
lowest of everything it measured — behaviour a default cannot fake.

Plus a replay test — recomputing `mastery` from `concept_evidence` alone must reproduce
the live table exactly. **Built, and it earned its keep on its first run:** the
incremental path and the replay disagreed, because a timestamp written as
`timezone.utc` returns from Postgres as `ZoneInfo("Etc/UTC")` — the same instant, a
different object — and FSRS compares `tzinfo` by equality. Only the replay path read
timestamps back from the database, so only the replay path raised.

It then earned it twice more. The comparison originally covered four derived columns and
skipped `fsrs_card`, which hid a real divergence: `fsrs.Card()` stamps its id from the wall
clock, so a rebuilt row differed from the row it was meant to reproduce while every number
computed from it matched. A first card is now built from the evidence, and the gate
compares every column the projection owns — a gate that skips a column is a gate with a
hole in it.
