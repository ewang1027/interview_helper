# API and session runtime

> **Status:** Specification — of the surface below, only `/health` and `/corpus/status`
> exist today, and there is **no auth on any of it**. The rest lands in **Phase 3**; the
> Vapi shim in **Phase 7**. (The executor's `POST /execute` and `POST /probe` *are* built,
> but that is a separate service on a separate contract — see [SECURITY](SECURITY.md).
> `api.executor_client` now speaks to it, and the coding grader uses it; what does not
> exist is the `run_code` **tool** below — there is no agent to invoke it.)
> Related: [ARCHITECTURE](ARCHITECTURE.md) · [GRADING](GRADING.md) (what the graders do with submissions) · [ADAPTIVE](ADAPTIVE.md) (where the planner gets its input) · [VOICE](VOICE.md) (the second transport) · [WEB](WEB.md) (the first consumer)

This is the contract two separate consumers build against — the web app and the Vapi
voice adapter. Leaving it implicit would mean building Phase 5 and Phase 7 against
guesswork, so it is specified before either exists.

## Shape of the thing

The interviewer is a function over `(session state, corpus item, tools) → turn`. HTTP+SSE
is one adapter over that function; Vapi's OpenAI-compatible endpoint is another. Nothing
in the agent core knows which transport it is serving — that is what makes voice a Phase 7
adapter rather than a rewrite.

## Session state machine

```
                    ┌──────────┐
                    │ planning │  planner picks items from mastery
                    └────┬─────┘
                         ▼
                    ┌──────────┐
                    │ briefing │  interviewer states the format and the first problem
                    └────┬─────┘
                         ▼
              ┌──────────────────┐
     ┌───────▶│   interviewing   │◀──────┐  turn loop: candidate ⇄ agent ⇄ tools
     │        └────┬─────────┬───┘       │
     │             │         │           │
     │      next item        │      tool result
     └─────────────┘         ▼           │
                    ┌──────────┐         │
                    │ wrapping │─────────┘  time or items exhausted
                    └────┬─────┘
                         ▼
                    ┌──────────┐
                    │ grading  │  deterministic + rubric graders run
                    └────┬─────┘
                         ▼
                    ┌──────────┐
                    │ complete │  report available, evidence written
                    └──────────┘

  any state ──▶ abandoned  (client ended it early; partial evidence still written)
  any state ──▶ failed     (unrecoverable error; no evidence written)
```

Two rules that matter:

- **`abandoned` still writes evidence** for whatever was actually graded. A session you
  quit halfway through is real data about the part you did.
- **`failed` writes none.** A grader crash must not produce a fabricated score — see
  [GRADING.md](GRADING.md#failure-is-a-failure). A missing grade is visible; a wrong one
  corrupts mastery permanently.

Transitions are server-driven. Clients observe them via SSE; they never set state
directly.

## REST endpoints

Base path `/api/v1`, **for everything that does not exist yet**. The two routes that are
live today are mounted at the **root** with no prefix — `/health` and `/corpus/status` —
because no `APIRouter` exists. Moving them under `/api/v1` is owed when the router lands;
until then, following the paths below will 404. All responses `application/json` unless
noted.

### Sessions

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/sessions` | Create and start planning |
| `GET` | `/sessions/{id}` | Current state, plan, elapsed time, budget consumed |
| `GET` | `/sessions/{id}/events` | **SSE stream** — the live channel (below) |
| `POST` | `/sessions/{id}/turns` | Candidate says something |
| `POST` | `/sessions/{id}/submissions` | Candidate submits code or an answer |
| `POST` | `/sessions/{id}/end` | End early → `abandoned` |
| `GET` | `/sessions/{id}/report` | Full report; 409 until `complete` or `abandoned` |
| `GET` | `/sessions` | History, paginated |

**`POST /sessions`**

```jsonc
{
  "mode": "coding",              // coding | quant | design | behavioral
  "budget_minutes": 45,
  "focus_concepts": [],          // optional override; empty = let the planner decide
  "difficulty_bias": 0           // -1 easier … +1 harder, advisory
}
```

→ `201` with `{ "id": "...", "state": "planning", "plan": { ... } }`

The `plan` is returned up front deliberately — you should be able to see what it decided
to drill you on, and why, before the session starts. Opaque adaptation is untrustworthy
adaptation.

**`POST /sessions/{id}/submissions`**

```jsonc
{
  "item_id": "i.code.0117",
  "kind": "code",                // code | answer | design | narrative
  "language": "python",          // code only
  "content": "def solve(...): ...",
  "elapsed_seconds": 412
}
```

→ `202 Accepted`. Grading is asynchronous; results arrive on the SSE stream. The endpoint
returns immediately because a coding submission with a complexity probe can take tens of
seconds, and a blocked HTTP request is a bad way to wait for that.

### Mastery and planning

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/mastery` | Every concept: ability, stability, due_at, evidence count |
| `GET` | `/mastery/{concept_id}` | One concept, with the evidence rows behind it |
| `GET` | `/mastery/weaknesses` | Ranked weakness list with the priority breakdown |
| `GET` | `/plan/next` | What the planner would choose right now, without starting a session |
| `POST` | `/mastery/recompute` | Rebuild the projection from `concept_evidence` |

`GET /mastery/{concept_id}` returning the underlying evidence is the feature that makes
the adaptive engine auditable: every number traces to graded artifacts you can re-read.

`POST /mastery/recompute` exists because `mastery` is a projection
([ADAPTIVE.md](ADAPTIVE.md#evidence-not-scores)). If a grader bug is found and fixed,
correct the evidence and replay — never hand-patch the projection.

### Corpus and cost

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/corpus/status` | Counts by domain and kind — **exists today, at `/corpus/status`, not under `/api/v1`** |
| `GET` | `/corpus/items/{id}` | One item, statement redacted if unseen |
| `GET` | `/costs` | Ledger rollups: per session, per day, per model |
| `GET` | `/costs/budget` | Remaining session and daily token budget |

`GET /corpus/items/{id}` redacts the statement of an item you have not been served yet.
Reading ahead defeats the measurement.

## SSE event stream

`GET /sessions/{id}/events` — `text/event-stream`. Every event is JSON with a `type` and a
monotonic `seq`.

| `type` | Payload | Meaning |
|---|---|---|
| `session.state` | `{ state, reason? }` | State machine transition |
| `item.presented` | `{ item_id, title, statement_md, expected_minutes }` | A problem is now in play |
| `agent.message.delta` | `{ text }` | Streaming interviewer text |
| `agent.message.done` | `{ message_id, text }` | Complete turn; authoritative over deltas |
| `agent.tool_use` | `{ tool, input, tool_use_id }` | Interviewer invoked a tool |
| `tool.result` | `{ tool_use_id, output, is_error }` | What came back |
| `hint.revealed` | `{ item_id, level, text, score_penalty }` | A hint was given — **and what it cost**. `score_penalty` is the schedule in [GRADING.md](GRADING.md#hints-cost-score) — a fraction of the score still on the table, not absolute points |
| `observation.recorded` | `{ concept_id, signal }` | Mid-session evidence captured |
| `grading.started` | `{ item_id }` | Grading began |
| `grading.result` | `{ item_id, score, criteria[], evidence_written[] }` | Grading finished |
| `budget.warning` | `{ consumed, limit, scope }` | Approaching a token budget |
| `session.error` | `{ code, message, recoverable }` | Something failed |

Three deliberate choices:

- **`agent.message.done` is authoritative.** Deltas are a rendering convenience; a client
  that drops one must not end up with corrupted text. Reconcile on `done`.
- **`hint.revealed` carries `score_penalty` explicitly.** You should see the cost of a
  hint at the moment you take it, not discover it in the report.
- **`seq` is monotonic and gap-free**, so a reconnecting client can detect loss.
  Reconnect with `Last-Event-ID`; the server replays from the last acknowledged `seq`.

## Interviewer agent tools

The agent's entire capability surface. Deliberately small — see
[SECURITY.md](SECURITY.md#prompt-injection): the defence against injection is that
succeeding buys you very little.

| Tool | Input | Returns | Notes |
|---|---|---|---|
| `run_code` | `{ language, source, entrypoint, tests[], test_selection?, wall_ms?, memory_mb? }` | `{ outcome, passed, total, failures[], wall_ms, peak_rss_kb, detail }` | Proxied to the executor's `POST /execute` via `api.executor_client`. The **only** way code runs. `outcome` is load-bearing — only `ok` yields scorable counts. Passes are a count; only *failures* are enumerated. `peak_rss_kb` is always 0, nothing measures it yet. The executor's other endpoint, `POST /probe`, is deliberately **not** exposed as a tool: it is a grading step, and the agent does not grade |
| `check_answer` | `{ item_id, submitted }` | `{ correct, normalized, method }` | sympy equivalence, then numeric tolerance, then `accept_forms` |
| `reveal_hint` | `{ item_id, level }` | `{ text, score_penalty }` | Monotonic — level N implies N−1 was given |
| `record_observation` | `{ concept_id, signal, confidence, span }` | `{ ok }` | Mid-session evidence. `span` cites the transcript |
| `end_round` | `{ reason }` | `{ ok }` | Moves to the next item or to `wrapping` |

There is deliberately **no** tool that writes the corpus, sends anything outbound, reads
secrets, or edits mastery. Grading is not a tool — it runs after the turn loop, so the
interviewer cannot score itself.

`record_observation` requires a `span` citing the transcript for the same reason rubric
criteria do ([GRADING.md](GRADING.md#system-design-and-behavioral)): an observation the
agent cannot point at is not evidence.

## Auth

**None of this is implemented. Every route is open**, and the `users` table exists with a
`github_id` column that nothing reads. The design, for when it lands:

Single user. GitHub OAuth → signed session cookie, `HttpOnly`, `Secure`, `SameSite=Lax`.
One allowed GitHub account id, in config. Everything under `/api/v1` will require it
except `/health`.

The Vapi shim authenticates differently — a shared secret header, since Vapi is a server
calling us, not a browser. See [VOICE.md](VOICE.md#authentication).

## Errors

RFC 9457 `application/problem+json`:

```jsonc
{
  "type": "https://interview-helper.local/errors/budget-exceeded",
  "title": "Session token budget exceeded",
  "status": 429,
  "detail": "Session consumed 400k of 400k tokens.",
  "instance": "/api/v1/sessions/01J.../turns"
}
```

| Code | When |
|---|---|
| `400` | Malformed request |
| `401` | No or invalid session cookie |
| `404` | Unknown session or item |
| `409` | Wrong state — e.g. report requested before `complete` |
| `422` | Well-formed but invalid, e.g. submission for an item not in the plan |
| `429` | **Token budget exceeded** — refused, never silently downgraded ([COST.md](COST.md#hard-budgets)) |
| `503` | Executor or model provider unavailable |

`429` on budget is a refusal by design. A session that stops and says why is recoverable;
one that quietly switches to a cheaper model produces bad evidence, and bad evidence
corrupts mastery.

## Conventions

- **IDs** are ULIDs — sortable by creation time, which makes transcript ordering free.
- **Timestamps** are RFC 3339 UTC with `Z`.
- **Idempotency:** `POST /sessions` and `/submissions` accept `Idempotency-Key`. Retrying
  a submission after a network blip must not double-grade and double-write evidence.
- **Pagination** is cursor-based (`?cursor=&limit=`). Offsets drift when rows are inserted
  under you.
- **Versioning:** the path carries `v1`. Additive changes ship in place; breaking ones get
  `v2`.
