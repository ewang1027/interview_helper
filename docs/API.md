# API and session runtime

> **Status:** Partly built (2026-08-20). **Live:** the `/api/v1` router, `POST /sessions`,
> `GET /sessions`, `GET /sessions/{id}`, `POST /sessions/{id}/submissions`,
> `POST /sessions/{id}/end`, `GET /sessions/{id}/report`, `GET /api/v1/corpus/status`,
> `GET /mastery`, `GET /mastery/{concept_id}`, `POST /mastery/recompute`, **auth**
> (`/auth/login`, `/auth/callback`, `/auth/me`, `/auth/logout`, and a session cookie
> required by every `/api/v1` route), and RFC 9457 errors on all of it. `/health` stays at
> the root deliberately — see below.
> **Not built:** the SSE stream and every agent tool (there is no interviewer agent, so no
> model call has ever been made), the cost routes, `GET /corpus/items/{id}`,
> `Idempotency-Key`, and rate limiting. The cost routes and the model-call path are built
> (2026-08-20), and so are **the interviewer** (`POST /sessions/{id}/turns`, three of the
> five tools) and **the SSE stream** — every event below except `agent.message.delta`, which
> needs a streamed model call. Vapi in **Phase 7**.
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

Built today: `planning` → `briefing` on creation, `briefing` → `interviewing` on the first
**turn** (the interview has started when someone speaks, not when they submit),
`→ wrapping` when the interviewer calls `end_round` on the last planned item, and
`→ complete` when every planned item has a terminal grading. `grading` is still not a state
anything can observe, and `POST /end` still gives `abandoned` from anywhere.

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
| `GET` | `/sessions/{id}/events` | **SSE stream** — the live channel (below) | ✅ built |
| `POST` | `/sessions/{id}/turns` | Candidate says something | ✅ built |
| `POST` | `/sessions/{id}/submissions` | Candidate submits code or an answer | ✅ built |
| `POST` | `/sessions/{id}/end` | End early → `abandoned` | ✅ built |
| `GET` | `/sessions/{id}/report` | Full report; 409 until `complete` or `abandoned` | ✅ built |
| `GET` | `/sessions` | History, paginated | ✅ built |

Only `coding` sessions can be created: creating a session in a mode nothing can grade
would produce an interview that can never complete, so it is refused with `422` naming the
missing grader rather than allowed and dead-ended at the first submission.

**Planning is adaptive** ([ADAPTIVE](ADAPTIVE.md)): concepts ranked by weakness priority,
then the item whose expected score lands closest to the informative band. Each plan carries
its own reasoning — which concept an item was chosen for, what you were expected to score,
the priority terms behind that concept's rank, and the concepts it weighed but did not
serve. A plan with no evidence behind it says `"calibration": true` rather than implying it
adapted to something.

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

**`POST /sessions/{id}/turns`**

```jsonc
{ "content": "I'd use a sliding window here — is that the right shape?" }
```

→ `200` with `{ item_id, state, message, tool_calls[], hints_revealed, round_ended,
end_reason, truncated }`.

Synchronous, unlike a submission: a turn is a conversation and the candidate is waiting for
the reply. The tools the interviewer used are reported rather than hidden, for the same
reason the plan is — you should be able to see that it ran your code before telling you
something about it. `truncated` says the interviewer hit the per-turn tool-round cap, which
is a cost control and is reported rather than silently swallowed.

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

Results arrive on the SSE stream as `grading.started` and then `grading.result` — including
for a *failed* grading, which is the outcome somebody most needs telling about. Polling
`GET /sessions/{id}` still works and reports the same thing.

**One submission per item per session**, enforced with `409`. That is not
`Idempotency-Key` support — a client cannot tell a retry from a genuine second attempt —
but it refuses the harmful half of it: one item cannot write two sets of evidence into one
session. Iterating on a submission is the interviewer loop's job, and that does not exist.

### Mastery and planning

| Method | Path | Purpose | State |
|---|---|---|---|
| `GET` | `/mastery` | Every measured concept: ability, stability, due_at, observations | ✅ built |
| `GET` | `/mastery/{concept_id}` | One concept, with the evidence rows behind it | ✅ built |
| `GET` | `/mastery/weaknesses` | Ranked weakness list with the priority breakdown | ✅ built |
| `GET` | `/plan/next` | What the planner would choose right now, without starting a session | ✅ built |
| `POST` | `/mastery/recompute` | Rebuild the projection from `concept_evidence` | ✅ built |

`GET /mastery` reports `measured` and `calibrating` alongside the rows, because "four
concepts, weakest first" reads very differently once you know the taxonomy has 159 and the
rest have never been measured at all.

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
| `GET` | `/costs` | Ledger rollups: totals, by job, by model over the last `days` — **built** |
| `GET` | `/costs/budget` | Remaining session and daily token budget — **built** |

`GET /corpus/items/{id}` redacts the statement of an item you have not been served yet.
Reading ahead defeats the measurement.

`GET /costs/budget` is the more useful of the two cost routes while the agent is being
built: it answers "will the next call be refused, and why" without making one. Both are
scoped by the session cookie like everything else under `/api/v1`.

## SSE event stream

**Built (2026-08-20), except `agent.message.delta`.** `GET /sessions/{id}/events` —
`text/event-stream`. Every event is JSON with a `type` and a monotonic `seq`.

| `type` | Payload | Meaning |
|---|---|---|
| `session.state` | `{ state, reason? }` | State machine transition |
| `item.presented` | `{ item_id, title, statement_md, expected_minutes }` | A problem is now in play |
| `agent.message.delta` | `{ text }` | Streaming interviewer text — **not built**: the model call is not streamed yet, so a turn's text arrives once, on `done` |
| `agent.message.done` | `{ message_id, text }` | Complete turn; authoritative over deltas |
| `agent.tool_use` | `{ tool, input, tool_use_id }` | Interviewer invoked a tool |
| `tool.result` | `{ tool_use_id, output, is_error }` | What came back |
| `hint.revealed` | `{ item_id, level, text, score_penalty }` | A hint was given — **and what it cost**. `score_penalty` is the schedule in [GRADING.md](GRADING.md#hints-cost-score) — a fraction of the score still on the table, not absolute points |
| `observation.recorded` | `{ concept_id, signal }` | Mid-session evidence captured — **not built**, with `record_observation` |
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
  Reconnect with `Last-Event-ID` (or `?after=`); the server replays from the last
  acknowledged `seq`. History is a bounded buffer, so a client resuming from before it
  gets a **`stream.gap`** event naming what it asked for and what is still available —
  being told beats a plausible stream with a hole in it.

Two properties of the implementation that a client should know about:

- **The stream ends when the session does.** On `complete` or `abandoned` no further event
  can arrive, so the connection closes rather than being held open. A `ping` comment frame
  every 15s keeps it alive while a turn is thinking.
- **The bus is in-process.** One uvicorn process is what this runs on; under Fargate with
  two tasks a client could hold a stream against a task that is not running its turn.
  `api.events.EventBus` is the seam where a shared broker goes in Phase 6, and this is
  written down rather than left to be discovered.

## Interviewer agent tools

The agent's entire capability surface. Deliberately small — see
[SECURITY.md](SECURITY.md#prompt-injection): the defence against injection is that
succeeding buys you very little.

| Tool | Input | Returns | State |
|---|---|---|---|
| `run_code` | `{ language, source }` | `{ outcome, passed, total, failures[], detail, gradeable }` | ✅ built |
| `reveal_hint` | `{ level }` | `{ level, text, score_penalty, hints_remaining }` | ✅ built |
| `end_round` | `{ reason }` | `{ ok, reason }` | ✅ built |
| `check_answer` | `{ item_id, submitted }` | `{ correct, normalized, method }` | ✗ quant only, and no quant session can be created |
| `record_observation` | `{ concept_id, signal, confidence, span }` | `{ ok }` | ✗ lands with the rubric graders |

**`run_code` does not take tests, and that is a deliberate departure from what this
document used to specify.** The tests come from the corpus item; the model supplies only
the source. Letting the model choose the tests would let it run a payload of its own
devising *and* mark its own work — the two things this design spends the most effort
preventing. Everything else about it holds: it is proxied to the executor's `POST /execute`,
it is the only way code runs, `outcome` is load-bearing, and passes are a count while only
failures are enumerated. `POST /probe` is still not a tool: it is a grading step, and the
agent does not grade.

`reveal_hint` takes no `item_id` — there is exactly one item in play, and letting the model
name a different one would be a way to read ahead. Levels are enforced monotonic rather
than trusted: skipping to the last hint is what a model trying to be helpful does, and it
is the most expensive one.

The two unbuilt tools are unbuilt for reasons rather than for time. `check_answer` is
quant-only and `POST /sessions` refuses every mode but `coding`, so no reachable session
can call it. `record_observation` writes `concept_evidence`, which has exactly one producer
today — the grader — and a second producer before rubric grading exists risks counting one
item's concept twice.

There is deliberately **no** tool that writes the corpus, sends anything outbound, reads
secrets, or edits mastery. Grading is not a tool — it runs after the turn loop, so the
interviewer cannot score itself.

`record_observation` requires a `span` citing the transcript for the same reason rubric
criteria do ([GRADING.md](GRADING.md#system-design-and-behavioral)): an observation the
agent cannot point at is not evidence.

## Auth

**Built (2026-08-20).** Single user. GitHub OAuth in, a signed session cookie afterwards —
`HttpOnly`, `Secure` (configurable for plain-http localhost), `SameSite=Lax`. One allowed
GitHub account id, in config. Everything under `/api/v1` requires it; `/health` and
`/auth/*` do not, and they are outside the prefix so that exemption is structural rather
than a case inside the dependency.

| Route | Does |
|---|---|
| `GET /auth/login` | Redirects to GitHub with a signed, cookie-echoed `state` |
| `GET /auth/callback` | Exchanges the code, checks the account, sets the cookie, answers JSON |
| `GET /auth/me` | The principal, or `401` |
| `POST /auth/logout` | Clears the cookie, `204` |

**The cookie is signed, not encrypted, and carries no secret** — a user id, its GitHub id,
and an expiry, under HMAC-SHA256 with `SESSION_SECRET`. Verification never touches the
database, so `GET /api/v1/corpus/status` still needs no connection; the cost is that a
cookie stays valid until it expires (30 days), and `POST /auth/logout` clears the browser's
copy rather than revoking the token. Rotating `SESSION_SECRET` is what invalidates every
session at once.

**Nothing else mints a session.** There is no local-login route, no dev bypass and no
`AUTH_MODE` flag, because a flag is a thing that can be wrong in production. Development
signs its own cookie *outside* the process with `make login`
(`python -m api.mint_session`), which needs the same secret the server verifies with — so
the deployed API has no code path that issues a session without GitHub, rather than one
that is merely switched off.

**Configuration fails closed.** No `SESSION_SECRET` and every `/api/v1` route answers
`503` naming the variable, not `401` — no credential would help, and a login problem is
not what is wrong. An incomplete OAuth configuration refuses `/auth/login` for the same
reason: an OAuth app with no `GITHUB_ALLOWED_ID` would let *any* GitHub user into a
single-user deployment, so the flow refuses rather than running a weaker version of itself.

Session and mastery queries are scoped to the caller, so another user's session id answers
`404` — the same answer a made-up id gets, since a `403` would confirm it exists. That is
query scoping, not multi-tenancy, which stays out of scope
([ARCHITECTURE.md](ARCHITECTURE.md#what-is-deliberately-not-here)).

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
| `400` | Malformed request, or an OAuth callback whose `state` does not match |
| `401` | No session cookie, one this server did not sign, or an expired one — the three are indistinguishable on the wire on purpose |
| `403` | Authenticated with GitHub, and not the account this deployment serves |
| `404` | Unknown session or item — including one belonging to somebody else |
| `409` | Wrong state — e.g. report requested before `complete` |
| `422` | Well-formed but invalid, e.g. submission for an item not in the plan |
| `429` | **Token budget exceeded** (`budget-exceeded`) — refused, never silently downgraded ([COST.md](COST.md#hard-budgets)), and refused *before* the provider is called. Also `provider-rate-limited`, when the throttling is the provider's rather than ours: same status, different slug, because one means wait and the other means stop |
| `503` | Executor or model provider unavailable, or the server is missing configuration the request needs (`not-configured`) |

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
