# Cost governance

> **Status:** Built (2026-08-20), except the measurements. `api.llm` is the one path to a
> model: it checks the budget, makes the call, and writes the `llm_calls` row — so the
> ledger has a producer and the hard budgets have teeth (`429`, refused, never downgraded).
> `GET /costs` and `GET /costs/budget` are live, and two callers use it: the interviewer
> (`job="interviewing"`) and the rubric grader (`job="grading"`). The per-session cost
> table below is still empty
> because no full session has been run against a live provider: this account's Bedrock
> access is gated behind a use-case form (below). AWS alarms in **Phase 6**.
> Related: [ARCHITECTURE](ARCHITECTURE.md#model-routing) · [OPERATIONS](OPERATIONS.md#monitoring) · [RESEARCH](RESEARCH.md#where-it-runs-and-why-that-matters) (why research is free) · [PRACTICE_LOG](PRACTICE_LOG.md) (uses the existing classification job)

This is a designed-in subsystem, not a dashboard bolted on later. A previous project
(`learning_files`) exhausted a monthly usage cap mid-run and lost sixteen concurrent
sessions. The rule that came out of that: **the system refuses work rather than
overspending.**

## Where the money goes

| Work | Provider | Funded by |
|---|---|---|
| Corpus research and authoring | Claude Code on your machine | **Max plan** — no API spend |
| Live interview sessions | Bedrock | **AWS credits** (promotional credits cover Bedrock third-party model spend) |
| Escape hatch | Anthropic API direct | Out of pocket — only if Bedrock is unavailable |

Moving research to build time is the single biggest cost decision in the project. It is
the expensive half of the workload and it costs nothing.

## Model routing

Set in `.env`, resolved by `ModelRouter`; call sites never name a model.

| Job | Model | `effort` | Rationale |
|---|---|---|---|
| Session planning | Opus 5 | `high` | Once per session |
| Interviewing turns | Sonnet 5 | `medium` | The hot loop; dialogue, not a judgement that compounds |
| Grading | Opus 5 | `high` | Errors compound into mastery |
| Classification, extraction | Haiku 4.5 | `low` | Mechanical |

`effort` is now resolved per job by `ModelRouter.effort_for`, as this document asked. It is
**omitted** rather than sent for a model whose family predates 4.6, because those reject
`output_config.effort` outright and an unusable model is a worse failure than a default
effort.

### What actually runs today

The routing table above is the *design*. Measured against this project's AWS account on
2026-08-20, by making the calls:

| Model id | Result |
|---|---|
| `us.anthropic.claude-sonnet-4-6` | **answers** |
| `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | answers |
| `us.anthropic.claude-opus-5`, `us.anthropic.claude-sonnet-5`, `us.anthropic.claude-opus-4-8` | `403 not available for this account` — a different refusal from the form gate, and it may or may not lift when the form is submitted |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | `404 model use case details have not been submitted for this account` |
| `anthropic.claude-opus-5` (the id shipped here since Phase 3) | `404 does not exist` on the Mantle endpoint; `on-demand throughput isn't supported` on InvokeModel |

Two things follow. Bedrock ids for current models are **cross-region inference profiles** —
`us.` prefixed, often dated and versioned — and the undecorated ids this repo shipped for
four months were never callable. And the four jobs all default to Sonnet 4.6 today, which
is a deliberate, documented substitution rather than the design.

**Then it stopped working, a few calls later.** The same two ids that answered began
returning `404 Model use case details have not been submitted for this account. Fill out
the Anthropic use case details form before using the model.` So the account got a handful
of calls through and then hit the gate. Nothing in this repo changed between the call that
worked and the one that did not — which is worth knowing before reading a `404` here as a
regression.

### Getting the routing table back

**The advice this section carried on 2026-08-20 was wrong, and the correction is the
useful part.** It said to request access in the Bedrock console under *Model access*. That
page no longer exists: AWS retired it on 2025-09-29 and now enables every serverless
foundation model automatically, along with the `PutFoundationModelEntitlement` permission
and its API. Control moved to IAM policies and SCPs. Anyone following the old instruction
goes looking for a console page that was removed a year ago.

What actually gates this account is the one exception to that change: **Anthropic models
are enabled but require a one-time use-case form before first use.** The account's own
answer says so precisely —

```
$ aws bedrock get-foundation-model-availability --model-id anthropic.claude-sonnet-4-6
  "agreementAvailability": { "status": "NOT_AVAILABLE" },
  "authorizationStatus": "AUTHORIZED",
  "entitlementAvailability": "AVAILABLE",
  "regionAvailability": "AVAILABLE"

$ aws bedrock get-use-case-for-model-access
  ResourceNotFoundException: You have not filled out the request form.
```

Authorized, entitled, available in the region, and no agreement — which is exactly the
shape of "the form has not been submitted". Two ways to submit it:

1. **The Bedrock console playground.** Open any Anthropic model; it prompts the form once.
2. **`PutUseCaseForModelAccess`**, whose `formData` is base64-encoded JSON:
   `companyName`, `companyWebsite`, `intendedUsers`, `industryOption`,
   `otherIndustryOption`, `useCases`.

Then set the four `MODEL_*` variables back to their intended inference-profile ids if
Claude 5 becomes reachable. Nothing in the code changes: that is what `ModelRouter` is for.

Until the form is submitted `make test-llm` skips with the provider's own words, which is
the right behaviour for an environment condition, and every other gate runs against a
scripted model.

## Hard budgets

**Enforced.** Five limits, checked by `api.llm.enforce_budget` before every call:

```
MAX_USD_PER_SESSION=1.00        MAX_TOKENS_PER_SESSION=400000
MAX_USD_PER_DAY=10.00           MAX_TOKENS_PER_DAY=3000000
MAX_USD_PER_MONTH=100.00
```

**The dollar ceilings are checked first**, and they are the ones that mean something. A
token limit was a fine proxy for money while every job used one model; it stopped being one
the moment the routing table held Opus 5 and Sonnet 5 together. 3,000,000 tokens is roughly
$15 of Haiku input or $75 of Opus 5 output — which of those a "3M token" ceiling permits
depends on a line of `.env`, and that is not a ceiling anybody set deliberately.

The token limits stay because they bound a different thing: context volume, which is a
proxy for a runaway loop regardless of price. Both are enforced; a refusal names which
(`unit: "usd"` or `"tokens"`) because the fix is a different number in a different
variable.

**A month is not thirty days.** `MAX_USD_PER_MONTH` exists because thirty quiet days
followed by one bad one is exactly the shape a daily ceiling cannot see, and because a
month is how a bill arrives. It resets at UTC midnight on the first, for the same reason
the day resets at UTC midnight rather than rolling.

The defaults are calibrated against a measurement, not a guess: the first real session cost
**$0.0119**, so $1 a session is about eighty of those.

On breach the request is **refused** — `429 budget-exceeded`, carrying the scope, what was
consumed and the limit — not silently truncated and not downgraded to a cheaper model. A
session that stops and says why is recoverable; one that quietly degrades produces bad
evidence, which corrupts mastery. The refusal happens *before* the provider is called, so a
spent budget costs nothing to hit.

Three properties worth stating, because each is a choice:

- **A token is a token.** Input, output, cache reads and cache writes all count toward a
  token limit. Cache reads are cheap, not free, and they are still context the model
  processed. The *dollar* limits price each of those at its real rate, so a cache read
  costs a tenth of an input token there rather than the same.
- **A reservation is priced, not just counted.** `llm_calls.reserved_usd` is the dollar
  twin of `reserved_tokens`: what the call may cost if it runs to its limit, priced at its
  own model, held against the ceiling while it is in flight and zeroed when the row
  settles. It is stored rather than derived because `reserved_tokens` is one number and
  pricing needs the input and output halves separately — output costs five times input.

  Not a theoretical concern. Zeroing `reserved_usd` and running eight concurrent calls
  against a **$0.001** ceiling let **all eight through** — the same failure the token
  ceiling was measured having, in the other unit. The test that catches it uses a
  *deliberately slow* provider, because with an instant one the advisory lock plus fast
  settling makes the ceiling hold whether or not the reservation was ever priced. A
  concurrency test against a fake that returns immediately proves less than it appears to.
- **The check is "already spent" plus "what is in flight".** The input size is not known
  before the call, and asking the provider would itself be a call. So the last call before
  a refusal can overshoot its ceiling by at most its own `max_tokens` plus its estimated
  input, and the next one is refused.

  That bound used to be false under any concurrency at all, which is worth keeping because
  the sentence above read as if it were true. The check ran in a transaction that closed
  *before* the provider was called, so nothing recorded that a call was in progress and
  every call overlapping in time read the same pre-spend total. Measured: **eight
  concurrent calls against a 1000-token daily ceiling were all allowed, spending 8,000,000
  tokens** — an 8000x overshoot of a limit described here as bounded by one call. Every
  `/api/v1` handler is a synchronous `def`, so Starlette runs them in a threadpool; two
  browser tabs, a retrying client, or the interviewer and a practice-log entry together
  are enough.

  A row is now written to `llm_calls` **before** the call, inside the same transaction as
  the check and under `pg_advisory_xact_lock`, holding what the call may cost. It is
  settled with real usage afterwards. An in-flight row counts against the budget at its
  reservation, so a concurrent check sees it; a reservation older than fifteen minutes is
  treated as abandoned, which fails in the direction of being briefly too strict.
- **The day resets at UTC midnight**, not on a rolling 24-hour window. A rolling window is
  kinder to a late-night session and impossible to reconcile against a bill.

## The ledger

Every model call appends to `llm_calls`:

| Column | Why |
|---|---|
| `status`, `reserved_tokens`, `settled_at` | One row per **attempt**, not per success. `reserved` while in flight and counted against the budget at its reservation; then `settled` (usage is real) or `failed` (the call did not complete, and usage is whatever the provider admitted to). A streamed call that dropped after producing output used to write no row at all — the caller had already been handed billed tokens, and neither the ledger nor the next budget check ever saw them |
| `model`, `provider` | Attribute spend to a routing decision |
| `input_tokens`, `output_tokens` | The bill |
| `cache_read_tokens`, `cache_write_tokens` | Whether caching is actually working |
| `cost_usd` | Computed at call time from the rate table |
| `latency_ms` | Cost/latency tradeoffs need both numbers |
| `session_id`, `job` | Per-session and per-job attribution |

`make cost-report` reads it, and `GET /api/v1/costs` returns the same rollup split by job
and by model — by job says what is expensive to do, by model says what the routing table is
costing. `GET /api/v1/costs/budget` answers the other question: will the next call be
refused, and why. A `/costs` view in the web app will render both — `apps/web` is an empty
directory until Phase 5.

A streamed call and an unstreamed one are counted identically: `api.llm.complete` and
`api.llm.stream` share one request builder and one recording path, because two copies of
that is how a streamed call quietly stops being priced.

**`cost_usd` is computed once, at call time, and never recomputed on read.** Rates change,
and a ledger that silently re-prices last month's calls cannot be reconciled against a
bill. A model with no entry in the rate table is recorded at `$0` with a warning rather
than a guess, because the token counts are worth keeping even when the price is not.

The rates in `api.pricing` are Anthropic first-party list prices. For the model this
project actually runs they are not an approximation: Bedrock's own rate card, read on
2026-08-20 with `aws bedrock list-foundation-model-agreement-offers --model-id
anthropic.claude-sonnet-4-6`, gives `$3.00/M` in, `$15.00/M` out, `$0.30/M` cache read and
`$3.75/M` cache write — identical, and confirming the cache multipliers. It also prices a
one-hour cache write at 2x input rather than 1.25x, which is why this system asks for the
five-minute default and nothing offers to change it.

[PRACTICE_LOG](PRACTICE_LOG.md)'s problem-classification calls log here with
`job="practice_log_classify"` (built 2026-08-21). They ride the same *model* as
"Classification, extraction" above, through a router entry of their own — this document
used to say no new entry was needed, which conflated the two. The ledger records the job
the router was asked for, so granularity here and shared routing above are the same
decision, not a trade between them.

These are also the only calls in the system with **no `session_id`**: a problem you solved
elsewhere belongs to no interview, so they land against the daily budget and appear in
`/costs` under their own job rather than under any session's spend.

`api.llm.record_call` writes the row, **in its own transaction**, before the caller sees the
completion. The spend happened whatever the caller does next, and a caller that raises
afterwards would otherwise roll back the only record of it — the same reasoning that puts a
failed grading in a fresh session.

## Prompt caching

The frozen per-mode system prompt and item context sit above the `cache_control`
breakpoint; volatile turn content sits below. Opus 5's 512-token cache minimum means
even short prefixes are cacheable.

**The assertion this document asked for now exists**, as
`test_an_identical_prefix_is_served_from_cache` in `apps/api/tests/test_llm_live.py`: two
calls with an identical prefix, and the second must report a non-zero
`cache_read_input_tokens`. It is marked `llm` and runs via `make test-llm`, not in CI —
CI has no credentials, and a cache assertion against a fake provider asserts nothing.
Cache invalidation is silent — a timestamp interpolated into a system prompt, a tool list
that reorders, a dict serialized without sorted keys — and the only symptom is the bill.

One implementation note that is easy to get wrong: **automatic (top-level) `cache_control`
is not available on Bedrock**, which is the default provider here. `api.llm.cached_system`
places the breakpoint on the system block by hand, and the shape of that request is pinned
by a test, because the failure mode is a larger bill and nothing else.

## AWS-side guards

- **AWS Budgets alarm** on the credit balance, with a threshold well below exhaustion.
- **CloudWatch alarm** on Bedrock spend rate, to catch a runaway loop within minutes
  rather than at month end.
- Credits are checked in the Billing console during Phase 0 to confirm they are the
  kind that covers Bedrock third-party model spend.

## What a session actually costs (measured 2026-08-25)

The first real session in this project's history, on the Anthropic API rather than Bedrock.
Coding, three interviewer turns including one that ran the candidate's code in the sandbox,
then a submission graded against hidden tests:

| Call | Model | in | out | cache write | cache read | $ |
|---|---|---|---|---|---|---|
| interviewing | `claude-sonnet-5` | 89 | 110 | 2,301 | 0 | 0.0070 |
| interviewing | `claude-sonnet-5` | 280 | 216 | 0 | 2,301 | 0.0032 |
| interviewing | `claude-sonnet-5` | 387 | 46 | 0 | 2,301 | 0.0017 |
| | | | | | **total** | **$0.0119** |

Three things this settles that were previously estimates:

- **A coding session costs about a cent**, and **grading it is free** — the coding grader is
  hidden tests in a sandbox, not a model. The modes that cost more are the three whose
  graders *are* a model call.
- **Prompt caching works and pays immediately.** The system prompt was written once at 2,301
  tokens and read on both subsequent turns. The assertion this document names is now
  exercised by a passing test rather than an argument.
- **The per-session ceiling is far away.** 400,000 tokens against ~3,700 used — a session
  would have to run about a hundred times longer to be refused.

### The provider switch

`MODEL_PROVIDER=anthropic` was built in Phase 3, described in the code as "the escape
hatch", and had never been used. Switching to it took four lines of `.env` and no code:

```sh
MODEL_PROVIDER=anthropic
ANTHROPIC_API_KEY=…
MODEL_PLANNER=claude-opus-5        # the two jobs the router runs at `high` effort
MODEL_INTERVIEWER=claude-sonnet-5
MODEL_GRADER=claude-opus-5
MODEL_UTILITY=claude-sonnet-5
```

It worked first time because `pricing.normalise` already strips both the `us.` geo prefix
and the `anthropic.` provider prefix, so `us.anthropic.claude-sonnet-4-6` and
`claude-sonnet-4-6` price identically. A ledger that only understood one provider's ids
would have written `$0` and a warning for every call.

Opus 5 sits on planning and grading because both **compound**: a plan decides what you are
drilled on for weeks, and a grade writes immutable evidence that moves mastery permanently.
Interviewing is the hot loop and its output is dialogue.

**Bedrock is still the intended home**, once the use-case form clears and credits absorb the
spend. Nothing about the switch is one-way — it is one environment variable back.

## Measuring before optimizing

Phase 3's gate records real measured cost per session, per mode, in this file. Every
optimization after that is judged against those numbers rather than against intuition.
**Still empty, and now for a smaller reason than before:** the machinery to measure exists
and is exercised, but no session calls a model yet, so there is nothing to average.

| Mode | Measured $/session | Recorded |
|---|---|---|
| Coding | — | Phase 3 |
| Quant | — | Phase 3 |
| System design | — | Phase 3 |
| Behavioral | — | Phase 3 |
