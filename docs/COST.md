# Cost governance

> **Status:** Policy set, nothing enforced yet — no model call has been made. Budgets and
> the ledger land in **Phase 3**; AWS alarms in **Phase 6**. The per-session cost table
> below is empty because no session has run.
> Related: [ARCHITECTURE](ARCHITECTURE.md#model-routing) · [OPERATIONS](OPERATIONS.md#monitoring) · [RESEARCH](RESEARCH.md#where-it-runs-and-why-that-matters) (why research is free)

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

| Job | Model | Rationale |
|---|---|---|
| Session planning | Opus 5 | Once per session |
| Interviewing turns | Sonnet 5 | The hot loop |
| Grading | Opus 5 | Errors compound into mastery |
| Classification, extraction | Haiku 4.5 | Mechanical |

`effort` is tuned per job rather than left at the default — grading runs high, utility
classification runs low.

## Hard budgets

Two limits, enforced in middleware before the call is made:

```
MAX_TOKENS_PER_SESSION=400000
MAX_TOKENS_PER_DAY=3000000
```

On breach the request is **refused with a clear error**, not silently truncated and not
downgraded to a cheaper model. A session that stops and says why is recoverable; one
that quietly degrades produces bad evidence, which corrupts mastery.

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

`make cost-report` reads it. `/costs` in the web app renders it.

## Prompt caching

The frozen per-mode system prompt and item context sit above the `cache_control`
breakpoint; volatile turn content sits below. Opus 5's 512-token cache minimum means
even short prefixes are cacheable.

**A CI assertion checks that repeated identical-prefix requests report a non-zero
`cache_read_input_tokens`.** Cache invalidation is silent — a timestamp interpolated
into a system prompt, a tool list that reorders, a dict serialized without sorted keys
— and the only symptom is the bill. Catching it in CI is much cheaper than catching it
monthly.

## AWS-side guards

- **AWS Budgets alarm** on the credit balance, with a threshold well below exhaustion.
- **CloudWatch alarm** on Bedrock spend rate, to catch a runaway loop within minutes
  rather than at month end.
- Credits are checked in the Billing console during Phase 0 to confirm they are the
  kind that covers Bedrock third-party model spend.

## Measuring before optimizing

Phase 3's gate records real measured cost per session, per mode, in this file. Every
optimization after that is judged against those numbers rather than against intuition.

| Mode | Measured $/session | Recorded |
|---|---|---|
| Coding | — | Phase 3 |
| Quant | — | Phase 3 |
| System design | — | Phase 3 |
| Behavioral | — | Phase 3 |
