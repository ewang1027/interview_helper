# The practice log

> **Status:** Schema built, behaviour not. The two tables below and the `concept_evidence`
> extension exist and are migrated (they landed with the Phase 3 slice, 2026-08-16); the
> classification call, the REST surface and the scheduling rule are **not** built. Lands
> in **Phase 9**, still gated on the rest of Phase 3 (API, a live `ModelRouter`) and
> Phase 4 (mastery) existing first.
> Related: [ARCHITECTURE](ARCHITECTURE.md#data-model) ·
> [ADAPTIVE](ADAPTIVE.md) (the evidence/scheduling machinery this reuses) ·
> [CORPUS](CORPUS.md) (why this is manual-entry-only) ·
> [COST](COST.md#model-routing) (the classification job) ·
> [API](API.md) (REST/state-machine conventions followed here) · [GLOSSARY](GLOSSARY.md)

## Why this exists

Real practice happens outside this app — LeetCode, Codeforces, wherever. Without this
feature that practice is invisible to the adaptive engine: you could be strong on a
concept from a hundred outside solves and the planner would still treat you as
untested on it. The practice log closes that loop by letting you tell the system what
you solved, classifying it against the same 159-concept taxonomy the interview corpus
uses, and feeding the result into the same `concept_evidence`/`mastery` machinery
[ADAPTIVE](ADAPTIVE.md) already defines — so outside practice moves the same needle
in-app sessions do, instead of living as a disconnected log.

## Why manual-entry-only, not URL-fetch

[CORPUS](CORPUS.md) enforces, mechanically, that no proprietary problem statement text
from sites like LeetCode or HackerRank is ever stored in this repo — a validator check
rejects corpus items with excessive n-gram containment against source text. Fetching a
LeetCode page to classify it would mean holding that text somewhere, even briefly, and
would put this feature in the position of needing an exception to a rule the rest of
the project treats as absolute.

The practice log avoids the question entirely: it only ever stores a `title`, a `url`
(a pointer back to the original, never dereferenced by the system), and your own
notes. It is structurally outside the originality rule's scope, by construction, not
by exemption. Classification runs on that metadata alone.

## Data model

Two tables — **already created by migration `6e1d353bc543`** — plus an extension to the
existing `concept_evidence` table
([ARCHITECTURE](ARCHITECTURE.md#data-model)).

### `practice_problems`

| Column | Type | Notes |
|---|---|---|
| `id` | ULID | |
| `title` | text | User-entered |
| `url` | text | Pointer only, never fetched |
| `source_site` | enum(`leetcode`,`codeforces`,`other`) | |
| `notes` | text, nullable | User's own notes — never problem text |
| `difficulty_label` | text, nullable | Raw external label ("Medium", CF rating "1700") — a different currency from corpus `Difficulty.elo`; never conflated with it |
| `primary_concept_id` | text, FK → `concepts.id` | Mirrors corpus `Item.primary_concept` |
| `secondary_concept_ids` | text[] | Mirrors corpus `Item.concepts` |
| `classification_confidence` | float | From the classification call |
| `classification_model` | text | e.g. `"haiku-4.5"`, for audit |
| `status` | enum(`pending_classification`,`active`,`graduated`) | See state machine below |
| `solve_count` | int, default 1 | The initial log is solve #1 |
| `stability_days` | float, nullable | Current re-solve interval |
| `due_at` | timestamptz, nullable | Null once graduated |
| `graduated_at` | timestamptz, nullable | Set when `solve_count` reaches 3 |
| `created_at`, `updated_at` | timestamptz | |

### `practice_solves` (append-only)

| Column | Type | Notes |
|---|---|---|
| `id` | ULID | |
| `problem_id` | FK → `practice_problems.id` | |
| `review_number` | int | 0 = initial solve, 1–3 = scheduled re-solves |
| `is_success` | bool | Initial log is always `true` |
| `attempted_at` | timestamptz | |
| `notes` | text, nullable | |
| `concept_evidence_id` | FK, nullable → `concept_evidence.id` | Traceability |
| `created_at` | timestamptz | |

`practice_problems`'s `solve_count` / `stability_days` / `due_at` / `graduated_at` are a
derived projection over `practice_solves`, recomputable from scratch — the same
"immutable log, recomputable projection" shape [ADAPTIVE](ADAPTIVE.md) already uses for
`mastery` over `concept_evidence`. This is that pattern applied one level down, not a
new idea.

### Extending `concept_evidence`

Practice-log solves are not tied to a `sessions` row and are not scored against a
corpus `items` row, so this needs additive, nullable columns rather than a parallel
evidence table — a parallel table would defeat the point of feeding the shared engine:

- `item_id` — made nullable.
- `session_id` — made nullable.
- `practice_problem_id` — new, nullable FK → `practice_problems.id`.
- `source` — new, text holding `session_grading` | `practice_log` (a plain column, not a
  Postgres enum). A CHECK constraint, `concept_evidence_exactly_one_source`, requires
  exactly one of (`item_id`, `practice_problem_id`) to be set. **It does not cross-check
  `source`** — a row claiming `practice_log` with `item_id` set passes, so keeping the
  column consistent with the populated FK is the writer's job, not the database's.
- `grader_version` is reused as-is; for practice-log evidence it records the scheduling
  rule version (e.g. `"practice-log-v1"`) so a future constant change stays
  interpretable.

Corpus `items` are deliberately not reused for external problems: they are a
build-time, versioned, originality-checked artifact ([CORPUS](CORPUS.md)), and an
external LeetCode/Codeforces problem is neither. Extending `concept_evidence` is the
right level of integration — shared evidence and mastery, without blurring what a
corpus item is.

**Score for practice-log evidence:** initial solve or successful re-solve → `score =
1.0`. Failed re-solve attempt → `score = 0.2`, `confidence = 0.5` — weaker than a
graded artifact, because a self-reported miss is softer evidence of decay than a
hidden-test failure, not a confident "you don't know this."

## Classification flow

`POST /practice/problems` synchronously invokes one `ModelRouter` call, using the
"Classification, extraction" job already in [ARCHITECTURE](ARCHITECTURE.md#model-routing)'s
routing table (Haiku 4.5) — no new router entry needed. Logged to `llm_calls` with
`job="practice_log_classify"` for cost-report granularity ([COST](COST.md)).
Synchronous, unlike the async submission endpoint in [API](API.md) (which involves
sandboxed execution) — this is one small structured-output call with nothing to wait on.

Structured output:

```jsonc
{
  "primary_concept_id": "string, must be one of the 159 ids in concepts.json",
  "secondary_concept_ids": ["string", "..."],  // 0-4
  "confidence": 0.0,                            // 0-1
  "reasoning": "string, short paraphrase — never problem text"
}
```

Prompt is cache-shaped per [COST](COST.md)'s convention: the frozen 159-concept
taxonomy sits above the `cache_control` breakpoint (only changes when the corpus
version bumps); the volatile per-problem `title`/`url`/`notes` sit below.

**Confidence gate:**

- `confidence >= 0.75` → `status = "active"`. Evidence for the initial solve is
  written immediately; review scheduling starts.
- `confidence < 0.75` → `status = "pending_classification"`. **No `concept_evidence`
  row is written yet.** The problem is visible in listings with its proposed
  classification, but not in the review queue and not feeding mastery, until you
  confirm or correct it via `PATCH .../classification`.

The gate exists because `concept_evidence` is immutable: writing evidence against a
low-confidence guess, with no way to retract it if you later correct the concept tag,
would force an amendment/tombstone mechanism the rest of the design avoids. Deferring
the write until classification is resolved sidesteps that entirely, at the cost of a
short "pending" state.

## Spaced re-solve scheduling

Framed explicitly as FSRS-*inspired*, not full FSRS. [ADAPTIVE](ADAPTIVE.md)'s FSRS is
built for indefinite concept-level review with a richer memory model; this caps at 3
solves per problem and then graduates, so `stability_days` here is just "the current
interval length," not a memory-strength parameter. Constants below are placeholders,
same as ADAPTIVE's priority-formula weights — tune once real data exists.

```
PRACTICE_LOG_INITIAL_INTERVAL_DAYS = 3
PRACTICE_LOG_GROWTH_FACTOR         = 2.5   # SM-2-style default ease
PRACTICE_LOG_LAPSE_SHRINK          = 0.5
```

1. **Initial solve** (`review_number = 0`, always success) → `stability_days = 3`,
   `due_at = solved_at + 3d`, `solve_count = 1`.
2. **Scheduled review succeeds** → `solve_count += 1`. If `solve_count == 3` →
   `status = "graduated"`, `due_at = NULL`, out of the queue permanently. Otherwise
   `stability_days *= 2.5` (≈7–8 days after the first successful re-solve),
   `due_at = attempted_at + stability_days`.
3. **Scheduled review fails** → `solve_count` unchanged (a failed attempt is not a
   solve), `stability_days = max(1, stability_days * 0.5)`, `due_at` rescheduled
   sooner. `status` stays `"active"`. The attempt is still recorded in
   `practice_solves` and writes weak negative `concept_evidence` (above) — this is
   the concrete mechanism by which a lapse nudges the concept's shared `mastery`, not
   just this one problem's own schedule.

## REST endpoints and state machine

Follows [API](API.md) conventions throughout: base path `/api/v1`, ULIDs, RFC 3339
timestamps, `Idempotency-Key` on creates, cursor pagination on lists, RFC 9457
`problem+json` errors reusing the existing table — no new error codes needed.

```
pending_classification ──(confirm/correct, or auto-accept ≥0.75)──▶ active ──(solve_count reaches 3)──▶ graduated
```

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/practice/problems` | Log a solved problem. Body: `{title, url, source_site, notes?, difficulty_label?, solved_at?}`. Runs classification synchronously. |
| `GET` | `/practice/problems` | List, paginated, filterable by `concept_id`, `status`. |
| `GET` | `/practice/problems/{id}` | Detail + solve history + the `concept_evidence` rows it produced. |
| `PATCH` | `/practice/problems/{id}/classification` | Confirm or correct the classification. Triggers the deferred evidence write; flips `pending_classification → active`. `422` on an unknown concept id. |
| `GET` | `/practice/review-queue` | `status="active"` and `due_at <= now`, most-overdue first. |
| `POST` | `/practice/problems/{id}/reviews` | Record a re-solve attempt: `{is_success, notes?, attempted_at?}`. Applies the interval rule above. `409` if `status` is not `"active"`. |

## What this deliberately does not do

- **No scraping, no URL fetch of problem content** — see above.
- **No full FSRS memory model** (difficulty parameter, retrievability curve) — a
  3-repetition cap doesn't need one.
- **No multi-tenancy** — consistent with the rest of the app.
- **No LLM-invented problems.** This only classifies problems you solved yourself; the
  corpus stays the only thing anything is *generated* into
  ([ARCHITECTURE](ARCHITECTURE.md)'s "why build-time" reasoning applies here too).

## Open questions / risks

- Haiku 4.5's classification accuracy against 159 concepts is uncalibrated. Before
  trusting auto-accept at the 0.75 threshold, build a small hand-labeled gold set —
  same spirit as [GRADING](GRADING.md)'s calibration harness for LLM graders.
- The growth factor (2.5×), initial interval (3 days), and lapse shrink (0.5×) are
  placeholders pending real usage data, not tuned values.
- Whether self-reported practice-log evidence should carry lower `confidence` than an
  LLM-graded rubric read is an open call; this doc proposes `0.5` for a failed
  re-solve as a starting number, not a settled one.
