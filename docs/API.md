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
> five tools) and **the SSE stream**, carrying the interviewer's text as it is generated.
> Vapi in **Phase 7**.
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
- **`any state ──▶ abandoned` means any non-terminal state**, and that was a claim this
  document made before the code kept it. `POST /end` refused anything outside
  `{briefing, interviewing}`, which made `wrapping` a permanent dead end: the interviewer
  ending the last round with nothing submitted moves a session there, and from there
  `/end` 409ed as "already wrapping", `/report` 409ed as unreportable, and `/turns` and
  `/submissions` 409ed as not open. Nothing could finish it either, because `wrapping`
  waits for gradings and `_maybe_complete` only runs from a grading callback that would
  never fire. The session could not be finished, abandoned, read, or continued.
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
| `GET` | `/sessions/{id}` | Current state, plan, per-item grading status, elapsed time, spend | ✅ built |
| `GET` | `/sessions/{id}/events` | **SSE stream** — the live channel (below) | ✅ built |
| `POST` | `/sessions/{id}/turns` | Candidate says something | ✅ built |
| `POST` | `/sessions/{id}/submissions` | Candidate submits code or an answer | ✅ built |
| `POST` | `/sessions/{id}/end` | End early → `abandoned` | ✅ built |
| `GET` | `/sessions/{id}/report` | Full report; 409 until `complete` or `abandoned` | ✅ built |
| `GET` | `/sessions` | History, paginated | ✅ built |

**All four modes can be created and graded** since the quant grader landed (2026-08-21).
The `422` that refuses a mode with no grader is still there and now has no subject: creating
a session in a mode nothing can grade would produce an interview that can never complete, so
the guard stays for the next mode added, and a test asserts the two sets have not drifted
apart.

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

**`GET /sessions/{id}` reports `tokens_consumed`, `token_budget` and `budget_enforced`**,
read from the `llm_calls` ledger and scoped to that session. All three were a constant
until 2026-08-24 — `0`, absent, and `false` — under a comment saying budgets were "enforced
nowhere" and no model call had ever been made. Both halves had been untrue since the
model-call path landed on 2026-08-20, so the route was telling every client budgets were
off while `enforce_budget` refused calls and `/costs` reported the spend. Nothing caught it
because nothing asserted on the two fields; a test does now, and the limit ships beside the
figure because a consumed count with no denominator reads as smaller than it is.

**`POST /sessions/{id}/turns`**

```jsonc
{ "content": "I'd use a sliding window here — is that the right shape?" }
```

→ `200` with `{ item_id, state, message, tool_calls[], hints_revealed, round_ended,
end_reason, truncated }`.

Synchronous, unlike a submission: a turn is a conversation and the candidate is waiting for
the reply. The tools the interviewer used are reported rather than hidden, for the same
reason the plan is — you should be able to see that it ran your code before telling you
something about it. `truncated` says the interviewer hit one of two per-turn caps, both
cost controls and both reported rather than silently swallowed.

There are two because they bound different things, and only one of them existed. **Rounds**
(5) bound model calls. **Tool executions** (12) bound `tool_use` blocks — nothing did, and
the loop executed every block in every response. Measured with 60 blocks per response
across the 5 rounds: **300 executor round-trips inside one synchronous HTTP request**, 307
transcript rows, and 603 events against a 256-slot buffer — so a single turn evicted the
session's entire event history (`item.presented`, `hint.revealed`, `grading.result`) with
no `stream.gap`, because that check runs once, at stream open. A candidate reaches this
without a malicious model, by asking for it: "run each of these sixty variants".

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

### Practice log

*Built 2026-08-21.* Problems you solved elsewhere, folded into the same mastery —
[PRACTICE_LOG](PRACTICE_LOG.md) is the design.

| Method | Path | Purpose | State |
|---|---|---|---|
| `POST` | `/practice/problems` | Log a solved problem; classifies it synchronously | ✅ built |
| `GET` | `/practice/problems` | List, cursor-paginated, filterable by `concept_id` and `status` | ✅ built |
| `GET` | `/practice/problems/{id}` | Detail, solve history, and the evidence those solves produced | ✅ built |
| `PATCH` | `/practice/problems/{id}/classification` | Confirm or correct the tag; writes the held evidence | ✅ built |
| `POST` | `/practice/problems/{id}/reviews` | Record a re-solve; `409` unless the problem is `active` | ✅ built |
| `GET` | `/practice/review-queue` | What is due, most overdue first | ✅ built |

**`POST /practice/problems` is synchronous and answers `201`**, unlike a submission's
`202`. A submission may involve a sandbox and a complexity probe; this is one small
structured-output call with nothing to wait on, and returning the classification already
resolved is the difference between logging a problem and logging one and then polling.

**A classification below `0.75` confidence writes no evidence.** The problem lands
`pending_classification` — recorded, listed, out of the review queue, feeding nothing —
until `PATCH .../classification` confirms or corrects it. `concept_evidence` is immutable,
so this is what stops a guess becoming a permanent fact about your mastery. Resolving a
classification that was already acted on is a `409` that says so.

**A provider that is down does not lose the entry.** Classification failure lands the
problem in the same pending state, which a human already resolves — so an outage costs a
confirmation rather than the record of something you actually solved.

**A `concept_id`-filtered page can come back shorter than `limit`, or empty, with a cursor
to continue from.** The cursor describes where the *scan* reached, not how many rows
matched; page until `next_cursor` is null. The alternative — deciding the cursor after
filtering — returns no cursor for a page whose rows all fail the filter, so a client stops
believing it has seen everything while matching problems sit further back. A short page is
ordinary; a truncated list that looks complete is not.

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

**Built (2026-08-20).** `GET /sessions/{id}/events` — `text/event-stream`. Every event is
JSON with a `type` and a monotonic `seq`. Every event below is emitted; the last of them,
`observation.recorded`, joined on 2026-08-21 with the tool that produces it.

| `type` | Payload | Meaning |
|---|---|---|
| `session.state` | `{ state, reason? }` | State machine transition |
| `item.presented` | `{ item_id, title, statement_md, expected_minutes }` | A problem is now in play |
| `agent.message.delta` | `{ text }` | Streaming interviewer text, as the model generates it |
| `agent.message.done` | `{ message_id, text }` | Complete turn; authoritative over deltas |
| `agent.tool_use` | `{ tool, input, tool_use_id }` | Interviewer invoked a tool |
| `tool.result` | `{ tool_use_id, output, is_error }` | What came back |
| `hint.revealed` | `{ item_id, level, text, score_penalty }` | A hint was given — **and what it cost**. `score_penalty` is the schedule in [GRADING.md](GRADING.md#hints-cost-score) — a fraction of the score still on the table, not absolute points |
| `observation.recorded` | `{ concept_id, signal }` | Mid-session evidence captured — a `concept_evidence` row is already written when this arrives |
| `grading.started` | `{ item_id }` | Grading began |
| `grading.result` | `{ item_id, score, criteria[], evidence_written[] }` | Grading finished |
| `budget.warning` | `{ consumed, limit, scope }` | Approaching a token budget |
| `session.error` | `{ code, message, recoverable }` | Something failed. **Specified, never emitted** — no publisher exists. Listed here so its absence is visible rather than assumed |

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

  The status is re-read on each poll. It used to be tested against a row loaded once,
  before the stream opened — so a stream attached while the session was `briefing` tested
  `briefing` forever, and ending the session left the generator neither yielding nor
  stopping. That is worse than a stuck tab: the database session is a `yield` dependency
  FastAPI releases only when the response completes, so each hung stream pinned a pooled
  connection, and the default pool is 5 + 10. Fifteen abandoned tabs stalled every request
  the API had.

  There is also a hard ceiling of 30 minutes on one connection, after which the server
  sends `stream.timeout` and closes. SSE clients reconnect on their own and
  `Last-Event-ID` makes that lossless, so a bounded stream costs a client nothing.
- **The bus is bounded in two directions.** 256 events per session, and 128 sessions,
  evicted least-recently-published first. `EventBus.forget` documented itself as "called
  when a session ends" and had no caller outside tests — but calling it there is wrong,
  not merely missing: the terminal `session.state` is the event a client most needs, and
  dropping the channel in order to publish it destroys it before anyone can read it. The
  bound belongs on the collection, which is the thing that actually grows.
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
| `check_answer` | `{ submitted }` | `{ correct, normalized, method, checks_remaining }` | ✅ built |
| `record_observation` | `{ concept_id, signal, confidence, span }` | `{ ok, concept_id, signal, observations_remaining }` | ✅ built |

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

**`check_answer` takes no `item_id` either, and this document used to say it did.** The
argument above applies to it unchanged; the signature simply had not caught up. Corrected
2026-08-21, when the tool was built.

**`check_answer` is rationed, because it is the only tool that is an oracle.** Ask it about
1, then 2, then 3, and you have the answer without the candidate having thought about
anything — the same failure mode `reveal_hint`'s monotonic check exists for, and a model
trying to be helpful is exactly who would do it. **Three successful checks per item per
session**, counted from the turn record rather than held in memory, because a tool context
is rebuilt every turn and an in-memory counter would reset with each thing the candidate
says. A refused check does not spend one — it told the model nothing about the answer — and
`checks_remaining` comes back with every result so the ration is visible rather than
discovered. It is the same function grading runs: an interviewer saying "that is right" and
a grader then scoring it zero would be two answers to one question.

**All five are built** as of 2026-08-21. There is deliberately **no** tool that writes the
corpus, sends anything outbound, or reads secrets. Grading is not a tool — it runs after the
turn loop, so the interviewer cannot score itself.

`record_observation` is how a conversation becomes evidence, and it is the third producer of
`concept_evidence` after session grading and the practice log. Four rules make that
defensible, none of them new — each is a control this project already applies somewhere:

- **A `span` citing the transcript**, for the same reason rubric criteria carry one
  ([GRADING.md](GRADING.md#system-design-and-behavioral)): an observation the agent cannot
  point at is not evidence. It is checked with the rubric grader's own citation check, and
  **against the candidate's turns only** — an observation quoting the interviewer's own
  leading question would be the model citing itself.
- **Three signals — `strong`, `shaky`, `wrong` — and no way to say "they never mentioned
  it".** Silence is not evidence, and the span requirement enforces that structurally: there
  is nothing to quote.
- **The model's `confidence` is scaled, not trusted.** It is multiplied by a ceiling of
  0.25, the lowest number in the system — below a rubric judgement's 0.5, because an
  observation is a read of a conversation, mid-flight, with no anchors at all. A model asked
  how sure it is answers "very".
- **Three per problem**, counted from the turn record rather than held in memory. Every
  successful call writes an immutable row, so a cap that reset each turn would be an
  unbounded producer of the softest evidence here.

An observation **never moves an item's rating** ([ADAPTIVE.md](ADAPTIVE.md#two-numbers-per-you-concept)):
it is a reading of the conversation, not an outcome of attempting the problem. That matters
mechanically as well as in principle — an observation is written *during* the round and a
grading afterwards, so without the rule it would take the rating move that belongs to the
result.

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
