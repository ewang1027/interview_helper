# Job applications

> **Status:** **Built and run live (2026-08-26).** Two tables, the stage projection, the
> paste parser, the web-search research pass and all ten endpoints, plus the `/jobs` page
> ([WEB](WEB.md)). ~~No real model has parsed a real list~~ — **both calls now have**: a
> deliberately messy five-application paste parsed into five correct rows, and the research
> pass completed six real web searches. 40 tests, 22 against live Postgres, 3 against a
> live model.
> **Not built:** `/jobs` has never been opened in a browser, like every other route here.
> Nothing writes `concept_evidence` or feeds [ADAPTIVE](ADAPTIVE.md)'s projection; see
> "What this deliberately does not do".
> **Two corrections kept**, both under "What the first live call found": the research pass
> was first routed through Bedrock, which cannot do web search at all; and all three of
> this feature's schemas carried JSON Schema keywords that constrained decoding rejects, so
> the first three live calls were 400s. The second one was not confined to this feature.

> Related: [API](API.md#job-applications) (the REST surface) · [WEB](WEB.md) (the page) ·
> [COST](COST.md) (what an import costs) · [ARCHITECTURE](ARCHITECTURE.md#data-model)
> (the tables) · [GLOSSARY](GLOSSARY.md)

A tracker for the applications themselves — which companies, which roles, and how far each
one got. It sits beside the practice log rather than inside it: the practice log is about
what you know, and this is about what is happening to you while you find out.

## The shape of it

You get applications into it two ways, and they meet in the same place:

```
  paste a list ──▶ parse + tag  (Sonnet 5, structured output)
                        │
                        ├── ≤ threshold ─────────────────────┐
                        │                                    │
                        └── > threshold ──▶ research         │
                                       (Opus 5 + web search) │
                                            │                │
  type one in ──────────────────────────────┴────────────────┴──▶ job_applications
                                                                          │
                                        every stage change appends to  job_application_events
                                                                          │
                                                            current_stage · furthest_stage · outcome
                                                                    (a projection, rebuildable)
```

## The four decisions

### 1. Stages are events, not a column

Every transition appends a row to `job_application_events`. The three columns on
`job_applications` that say where an application stands — `current_stage`,
`furthest_stage`, `outcome` — are a **projection** over that log, rebuilt from it by
`api.jobs.recompute` and by `POST /jobs/recompute`. This is the same relationship `mastery`
has to `concept_evidence` ([ADAPTIVE](ADAPTIVE.md#evidence-not-scores)), and it is here for
the same reason.

A single mutable `stage` column is cheaper, simpler, and cannot answer the question the
tracker exists to answer. *How many onsites did I get?* is asked in March, about a season
that ended in February, when every one of those applications has since become a rejection.
A column that was overwritten has thrown that away. A log has not.

### 2. `furthest_stage` is what the funnel counts

The funnel counts, for each rung, how many applications ever **reached** it — read off
`furthest_stage`, never `current_stage`.

Count it off `current_stage` and a rejection after a final round removes that application
from the "reached a final round" bucket. The funnel would then improve every time something
went badly, and the conversion rate from `final` to `offer` would climb towards 100% as the
rejections came in. That is exactly backwards, and it is subtle enough to go unnoticed for a
season.

Terminal stages — `rejected`, `withdrawn`, `ghosted` — are deliberately **not ranked**.
Ranking them would force a false question (is "withdrawn" further along than "round_2"?),
and whichever way it were answered every withdrawal would be counted as progress.

The ladder, in order:

| Stage | Label |
|---|---|
| `applied` | Applied |
| `oa` | Online assessment |
| `phone_screen` | Phone screen |
| `round_1` | First round |
| `round_2` | Second round |
| `final` | Final / onsite |
| `offer` | Offer |

and off the ladder: `rejected`, `withdrawn`, `ghosted`.

`furthest_stage` is a **maximum over the ladder**, not the last thing seen, so transitions
arriving out of order do not move you backwards — a recruiter screen booked after the
online assessment is a scheduling quirk, not a demotion. An application that arrives already
at `final` still gets an `applied` event written beneath it, because the funnel counts a
pipeline that reached the second round as having passed through the first, and the event log
is the only place that can be true.

### 3. The category is derived from the sub-category, never sent alongside it

Two levels: big categories `swe` · `ai` · `quant` · `other`, and sub-categories under each.
The model is given **one flat enum of sub-categories** and picks one; the big category is
looked up from it.

This is not a shortcut, it is the point. A model asked for both can return `quant` +
`frontend`, and then something has to notice and decide which half to believe. A model asked
for one cannot. The pair is consistent by construction rather than by a validation step that
has to remember to run — the same move as the practice log enumerating concept ids in its
response schema.

Sub-categories are therefore **globally unique**, and a test pins that: a name appearing
under two categories would make the lookup ambiguous and silently make one category
unreachable for that one role type.

| Category | Sub-categories |
|---|---|
| `swe` | backend, frontend, fullstack, distributed_systems, infrastructure, platform, security, mobile, embedded, compilers, data_engineering, site_reliability |
| `ai` | ml_engineering, ml_research, applied_ai, nlp, computer_vision, ai_infrastructure, agents, robotics |
| `quant` | quant_trading, quant_research, quant_developer, high_frequency_trading, risk, portfolio_management |
| `other` | data_science, product, hardware, design, unclassified |

`GET /jobs/catalog` serves this, rather than the web app carrying a second copy: the enum
the model is constrained to and the buttons a person clicks have to be the same list, and
the only way to guarantee that is for there to be one list.

### 4. Two calls, two tiers, and only one of them can fail the import

**The parse** (`job_parse` → Sonnet 5, structured output, effort `medium`) turns pasted text
into rows and tags each one. It runs on every import. If it fails, the import fails — there
is nothing to fall back to, and a `503` naming the provider is more useful than an import
that silently added nothing.

**The research pass** (`job_research` → Opus 5, web search, effort `high`) runs only when
the parse returned **more than `JOBS_RESEARCH_THRESHOLD` rows** (default 10). It looks up
the actual postings and fills in what a terse list left out: the real title, the location,
the URL, and a better sub-category now that it knows what the role involves.

The research pass **can never cost the import.** Every failure path returns the rows it was
given — a provider that is down, a model that never calls the tool, a loop that runs out of
rounds, or a returned list that is the wrong length. The ordering is what makes that
possible: the rows exist before the second call is made, so the second call is an
enrichment over data rather than a step in producing it.

That last case is the one worth naming. The failure this pass could cause that actually
matters is a **silently shortened list** — an import that quietly drops the four
applications whose postings could not be found. So a returned list that is not exactly as
long as the input is discarded whole rather than reconciled.

Two fields are carried over from the parse rather than taken from the research pass:
`stage` and `applied_on`. Nothing on the web knows whether you have had the phone screen
yet, and left to the model every row comes back `applied` because the posting does not
mention you.

#### Why the research pass is first-party only

**Web search is not available on Amazon Bedrock.** It is a first-party Claude API
server-side tool, and Bedrock does not offer it (nor web fetch, nor code execution).

This repo's default is `MODEL_PROVIDER=bedrock` and every other model path here is written
to run there, so the first version of this design had the research pass going through the
same router — which could not have worked at all. `api.jobs.research_available` checks the
provider **before** the call and returns a reason, so a Bedrock deployment gets the parse,
no research, and a sentence saying why. Discovering it as a 400 halfway through an import
would have been a worse way to learn it.

The correction is kept because the general shape recurs: a provider is not a
drop-in for another provider, and the routing table in
[ARCHITECTURE](ARCHITECTURE.md#model-routing) makes it easy to forget that a *job* can
depend on a capability rather than only on a model.

## What the first live call found

Everything below this heading was discovered by running the thing, on 2026-08-26, after it
had passed 32 tests against scripted models.

### Structured outputs accept a subset of JSON Schema

Three 400s in a row, each naming the next offending keyword:

```
output_config.format.schema: For 'array' type, property 'maxItems' is not supported
output_config.format.schema: For 'number' type, properties maximum, minimum are not supported
tools.1.custom: For 'array' type, property 'maxItems' is not supported
```

`type`, `enum`, `required` and `additionalProperties` survive. The range and length
keywords — `minimum`, `maximum`, `minItems`, `maxItems`, `minLength` — do not. The third
error is the useful one: it came from a **tool** schema, so the restriction tracks
`strict: true` rather than tools-versus-outputs. `api.agent.tools` sends `minimum` happily
on a non-strict tool and always has.

Nothing was lost. Every dropped keyword was a bound already enforced in code — confidence
is clamped in `_row_from`, the row count in `_rows_from`. `enum` is the constraint carrying
real weight here, and it is fully supported.

**Why no test caught it.** A scripted client answers whatever it is handed and never
validates the request, so a schema the provider would refuse looks identical to one it
would accept. Every test of this feature used one. `apps/api/tests/test_output_schemas.py`
is the static guard now — it walks every schema this repo sends under constrained decoding
and fails on a rejected keyword — and `test_schemas_live.py` sends two of them to the
provider, because a hand-written rule about what the API accepts can itself be wrong.

**This was not confined to the job tracker.** The same defect was found in
[PRACTICE_LOG](PRACTICE_LOG.md)'s classifier (since Phase 9) and, more seriously, in
[GRADING](GRADING.md)'s rubric grader (since Phase 3) — where it meant **design and
behavioral grading would have failed on their first real call**, while the buildlog said
all four modes graded. Both are fixed and both are now verified live.

### The cache breakpoint on the parse prompt does nothing

`api.llm.cached_system` marks every system prompt with `cache_control`, and the minimum
cacheable prefix is about 1024 tokens. Measured with `count_tokens`: the taxonomy block is
**882 tokens**. Below the floor, so the marker is accepted and silently has no effect.

Not worth fixing — at 882 tokens a 90% saving is a fraction of a cent — but worth knowing,
because "we cache the taxonomy" was the assumption. There is an assertion pinning it in
both directions: if the catalogue grows past the floor, caching switches on without anyone
deciding to, and the test says so.

### What it actually costs, measured

| Call | Model | Result | Cost |
|---|---|---|---|
| Parse, 5 messy rows | Sonnet 5 | 5 rows, correct categories and stages | **$0.0092** |
| Research, 2 thin rows | Opus 5 | 6 web searches, both rows completed | **$0.2266** |

The second number sharpens the open question below. **Six searches for two rows** is about
three per row, and the research pass is only triggered by lists of *more* than ten — so the
rule as written spends the most on the imports where it is least justified per row.
`JOBS_RESEARCH_MAX_SEARCHES` is what actually bounds it, and at the default of 30 a large
import is capped around $0.30 of search plus Opus tokens.

The prompts held up. The bare company name in the paste came back at **confidence 0.20** and
landed in review rather than being guessed at, and the research pass wrote "Could not
verify" and *lowered* its confidence to 0.15 on the row whose posting was ambiguous —
which is what its instructions ask for and the behaviour most likely to have been ignored.

## What an import costs

Two things are billed, and only one of them appears in `usage.*_tokens`:

- **tokens**, priced per model as everything else here is, and
- **web searches at $10 per 1,000** — flat, per search, on top of the tokens the results
  consume.

`llm_calls.web_search_requests` exists because of the second. A ledger that counted only
tokens would report a thirty-search research call at a fraction of what it cost, against
dollar ceilings that are supposed to be the thing that binds — thirty uncounted searches is
$0.30, about a third of the $1 session ceiling. `JOBS_RESEARCH_MAX_SEARCHES` (default 30) is
passed to the tool as `max_uses`, so the ceiling sits in the request the provider counts
against rather than in a check that runs after the money is spent.

See [COST](COST.md) for where this sits against the other jobs.

## The confidence gate, and why it is weaker than the practice log's

Below `AUTO_ACCEPT_CONFIDENCE` (0.6) a row lands `pending_classification`: recorded, listed,
counted in the funnel, and flagged for review. Confirming or correcting it through
`PATCH /jobs/{id}/classification` sets the tag and records confidence `1.0`, because a human
said so.

The practice log's gate is 0.75 and it **holds back an immutable evidence write**
([PRACTICE_LOG](PRACTICE_LOG.md)). This one holds back nothing. An application writes no
evidence and feeds no projection, so a doubtful tag mis-colours a chart until you fix it and
cannot do worse. The threshold is lower because the consequence is lower.

## What this deliberately does not do

- **It writes no `concept_evidence` and moves no mastery.** Applying to a quant firm is not
  evidence that you know stochastic calculus, and reaching an onsite is not evidence that
  you know anything in particular. Wiring this into [ADAPTIVE](ADAPTIVE.md)'s projection
  would put a number that is mostly about a recruiter's inbox into a rating that is supposed
  to be about what you can do.
- **It does not scrape job boards or apply to anything.** The research pass reads postings
  that already exist to complete rows you already made.
- **It stores no posting text.** At most one sentence of paraphrase in `notes`, the same
  rule the practice log keeps about problem statements.
- **It has no reminders, no follow-up nudges, no calendar.** Named because it is the most
  obvious next thing and its absence should read as a decision rather than an oversight.

## A note on this repo being public

**This repository is public, and job-application data is personal**: which companies, which
rejections, how far each one got. All of it lives in Postgres and none of it is a tracked
file. Every company name in the tests and in this document is invented — "Aurora Labs",
"Northwind Systems" — for that reason, and a fixture seeded with real applications would be
the one way this feature could leak something that matters.

## Open questions

- **The threshold is a row count, and cost runs the other way — now measured.** Two thin
  rows cost **$0.2266 and six searches**, about three searches per row. Above ten rows the
  import gets *more* expensive in total, and the trigger is length rather than need. The
  ceiling bounds it — 30 searches is about $0.30 plus Opus tokens — but the rule that would
  actually fit is "research the rows missing a title or a URL", whatever the length of the
  list. That is a per-row decision the current design does not make. It is the first thing
  to change here.
- **No gold set.** The same gap the practice log has: nothing hand-labelled to calibrate
  either the sub-category tagging or the confidence numbers against, so 0.6 is a placeholder
  like every other constant here.
- **Time-in-stage is recorded but not reported.** The events carry `occurred_at`, so "how
  long between the OA and hearing back" is answerable — and nothing answers it yet. It is
  probably the most useful thing this data can say that the funnel does not.
