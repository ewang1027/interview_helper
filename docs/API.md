# API and session runtime

> **Status:** Partly built (2026-08-20). **Live:** the `/api/v1` router, `POST /sessions`,
> `GET /sessions`, `GET /sessions/{id}`, `POST /sessions/{id}/submissions`,
> `POST /sessions/{id}/end`, `GET /sessions/{id}/report`, `GET /api/v1/corpus/status`, and
> RFC 9457 errors on all of it. `/health` stays at the root deliberately — see below.
> **Not built:** the SSE stream and every agent tool (there is no interviewer agent, so no
> model call has ever been made), the mastery and cost routes, `GET /corpus/items/{id}`,
> `Idempotency-Key`, and **auth — every route is still open**, which was acceptable while
> nothing wrote user data and is now overdue rather than merely absent. Vapi in **Phase 7**.
> (The executor's `POST /execute` and `POST /probe` are built on their own contract — see
> [SECURITY](SECURITY.md) — and `api.executor_client` is what speaks to them.)
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

Base path `/api/v1`. The router exists, and `/corpus/status` moved under it as this
document said was owed. **`/health` deliberately did not**: it is what a load balancer and
an ECS task health check poll ([INFRA](INFRA.md)), and it is the one route the auth below
exempts — keeping it outside the prefix makes that exemption structural instead of a
special case inside an auth dependency. All responses `application/json` unless noted;
errors are `application/problem+json`.

### Sessions

| Method | Path | Purpose | State |
|---|---|---|---|
| `POST` | `/sessions` | Create and plan | ✅ built |
| `GET` | `/sessions/{id}` | Current state, plan, per-item grading status, elapsed time | ✅ built |
| `GET` | `/sessions/{id}/events` | **SSE stream** — the live channel (below) | ✗ needs the agent loop |
| `POST` | `/sessions/{id}/turns` | Candidate says something | ✗ needs the agent loop |
| `POST` | `/sessions/{id}/submissions` | Candidate submits code or an answer | ✅ built |
| `POST` | `/sessions/{id}/end` | End early → `abandoned` | ✅ built |
| `GET` | `/sessions/{id}/report` | Full report; 409 until `complete` or `abandoned` | ✅ built |
| `GET` | `/sessions` | History, paginated | ✅ built |

Only `coding` sessions can be created: creating a session in a mode nothing can grade
would produce an interview that can never complete, so it is refused with `422` naming the
missing grader rather than allowed and dead-ended at the first submission.

**Planning is not adaptive yet.** Every plan carries `"adaptive": false` and the strategy
that produced it (`corpus-order-placeholder@1`): eligible items ordered by distance from a
fixed difficulty target, filled to the time budget. [ADAPTIVE](ADAPTIVE.md)'s engine
replaces it in Phase 4, and until it does, a plan that claimed to be adapted to you would
be a lie the response format itself tells.

**`POST /sessions`**

```jsonc
{
  "mode": "coding",              // coding | quant | design | behavioral
  "budget_minutes": 45,
  "focus_concepts": [],          // optional override; empty = let the planner decide
  "difficulty_bias": 0           // -1 easier … +1 harder, advisory
}
```

→ `201` with `{ "id": "...", "state": "...", "plan": { ... } }`

The `plan` is returned up front deliberately — you should be able to see what it decided
to drill you on, and why, before the session starts. Opaque adaptation is untrustworthy
adaptation.

The state in that response is `briefing`, not `planning`: planning is expected to take a
model call, and the placeholder planner is synchronous, so it is already finished by the
time the response is written.

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

→ `202 Accepted` with `{ artifact_id, item_id, state: "grading", poll }`. Grading is
asynchronous because a coding submission with a complexity probe takes tens of seconds,
and a blocked HTTP request is a bad way to wait for that.

Results are specified to arrive on the SSE stream, which lands with the agent loop. Until
then a client polls `GET /sessions/{id}`, where `items[].status` moves `grading` →
`graded` | `failed` and carries the score and the grader's detail.

**One submission per item per session**, enforced with `409`. That is not
`Idempotency-Key` support — a client cannot tell a retry from a genuine second attempt —
but it refuses the harmful half of it: one item cannot write two sets of evidence into one
session. Iterating on a submission is the interviewer loop's job, and that does not exist.

### Mastery and planning

**None of this is built** — it is Phase 4, and there is no `mastery` projection to serve.
The evidence it will read from is real now: a graded session writes `concept_evidence`.

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
| `GET` | `/corpus/status` | Counts by domain and kind — **built**, now under `/api/v1` |
| `GET` | `/corpus/items/{id}` | One item, statement redacted if unseen |
| `GET` | `/costs` | Ledger rollups: per session, per day, per model |
| `GET` | `/costs/budget` | Remaining session and daily token budget |

`GET /corpus/items/{id}` redacts the statement of an item you have not been served yet.
Reading ahead defeats the measurement.

## SSE event stream

**Not built.** There is no agent to narrate and no stream to reconnect to; a client learns
what happened by polling `GET /sessions/{id}`. Specified here because Phase 5 and Phase 7
both build against it.

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

**None of this is implemented. Every route is open** — and as of the session layer, open
routes now read and write user data, which is the line docs/BUILDLOG.md called a hard gate.
It is crossed, deliberately and on a single-user dev machine, and it is the next thing
owed. `api.users.current_user` is the seam it lands on: one function resolves the single
local user today, and nothing downstream has to learn that a user can be someone else.

The design, for when it lands:

Single user. GitHub OAuth → signed session cookie, `HttpOnly`, `Secure`, `SameSite=Lax`.
One allowed GitHub account id, in config. Everything under `/api/v1` will require it
except `/health`.

The Vapi shim authenticates differently — a shared secret header, since Vapi is a server
calling us, not a browser. See [VOICE.md](VOICE.md#authentication).

## Errors

RFC 9457 `application/problem+json`, built and used by every route. `type` is a stable
slug a client can branch on; matching on prose is how error handling rots:

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
| `429` | **Token budget exceeded** — refused, never silently downgraded ([COST.md](COST.md#hard-budgets)). Not reachable: nothing meters tokens, because nothing calls a model |
| `503` | Executor or model provider unavailable |

`429` on budget is a refusal by design. A session that stops and says why is recoverable;
one that quietly switches to a cheaper model produces bad evidence, and bad evidence
corrupts mastery.

## Conventions

- **IDs** are ULIDs — sortable by creation time, which makes transcript ordering free.
- **Timestamps** are RFC 3339 UTC with `Z`.
- **Idempotency:** `POST /sessions` and `/submissions` are specified to accept
  `Idempotency-Key`; **neither does yet**. `/submissions` is protected by the
  one-per-item rule above rather than by a key, and `POST /sessions` retried twice creates
  two sessions. Owed before the web app, which will retry on flaky networks.
- **Pagination** is cursor-based (`?cursor=&limit=`). Offsets drift when rows are inserted
  under you.
- **Versioning:** the path carries `v1`. Additive changes ship in place; breaking ones get
  `v2`.
