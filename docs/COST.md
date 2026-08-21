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

**Enforced.** Two limits, checked by `api.llm.enforce_budget` before every call:

```
MAX_TOKENS_PER_SESSION=400000
MAX_TOKENS_PER_DAY=3000000
```

On breach the request is **refused** — `429 budget-exceeded`, carrying the scope, what was
consumed and the limit — not silently truncated and not downgraded to a cheaper model. A
session that stops and says why is recoverable; one that quietly degrades produces bad
evidence, which corrupts mastery. The refusal happens *before* the provider is called, so a
spent budget costs nothing to hit.

Three properties worth stating, because each is a choice:

- **A token is a token.** Input, output, cache reads and cache writes all count toward a
  limit. Cache reads are cheap, not free, and they are still context the model processed.
- **The check is "already spent", not "would this fit".** The input size is not known before
  the call, and asking the provider would itself be a call. So the last call before a
  refusal can overshoot its ceiling by at most its own `max_tokens`, and the next one is
  refused. Bounded and honest beats precise and expensive.
- **The day resets at UTC midnight**, not on a rolling 24-hour window. A rolling window is
  kinder to a late-night session and impossible to reconcile against a bill.

## The ledger

Every model call appends to `llm_calls`:

| Column | Why |
|---|---|
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
