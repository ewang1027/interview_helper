# interview_helper

An adaptive mock-interview trainer for software engineering and quant trading interviews.
It runs practice interviews in four modes (coding, quant math, system design and
behavioral), grades each answer against the concepts it tests, and uses that history to
decide what to practice next. Single user, self-hosted.

## How it works

- **Corpus.** `packages/corpus` is the question bank as versioned JSON: a taxonomy of 186
  concepts and 48 items (12 per mode), checked by a JSON Schema and a validator.
- **Sessions.** `apps/api` (FastAPI, Postgres) plans a session, runs an LLM interviewer
  that streams over server-sent events, grades each submission and records evidence for
  every concept it touched.
- **Grading.** Coding answers run in `apps/executor` (Docker containers, no network,
  capped memory, CPU and processes) against tests, timed at several input sizes to check
  complexity. Quant answers get a symbolic check plus a rubric for the working; design and
  behavioral answers are graded by the model against a rubric.
- **Mastery.** Each concept has an Elo rating for ability and an FSRS schedule for review,
  both recomputed from the evidence. The planner favors weak and overdue concepts and
  shows why it picked each item.
- **Web app.** `apps/web` (Next.js 15) has the live interview, reports, a concept heatmap,
  a log for problems solved elsewhere (LeetCode, NeetCode) that feeds the same mastery
  model, and a job-application tracker.

## Running it locally

You need Docker, [uv](https://docs.astral.sh/uv/) and Node 22.

```sh
cp .env.example .env   # set SESSION_SECRET; see the file for the rest
make setup             # Python and web dependencies, plus the git hooks
make dev               # start Postgres and run migrations
make seed              # load the corpus
make up-stack          # build and start everything on http://localhost:3000
```

Sign-in uses GitHub OAuth (variables in `.env.example`). Without an OAuth app,
`make login` prints a session cookie you can set by hand. Live interviews need model
access: AWS Bedrock by default, or `MODEL_PROVIDER=anthropic` with an API key. For hot
reload, run `make dev-api` and `make dev-web` instead of `make up-stack`.

`make check` runs lint, type checks, unit tests, the corpus validator, the doc checks and
the web checks. Tests that need Postgres, Docker or a browser have their own targets
(`make test-db`, `make test-sandbox`, `make test-browser`), and CI runs all of them.

## Status

It runs end to end on one machine with Docker Compose. An AWS deployment (ECS Fargate) is
in progress but not live. The corpus is a small first set, the mastery weights are
placeholders until real sessions can tune them, and voice interviews are not started.

## Docs

| Doc | Covers | Status |
|---|---|---|
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Services, trust boundaries, data model | Partly built |
| [GLOSSARY](docs/GLOSSARY.md) | Project vocabulary | Reference |
| [CONCEPTS](docs/CONCEPTS.md) | The concept taxonomy and its rules | Built |
| [CORPUS](docs/CORPUS.md) | What an item is and what the validator checks | Built |
| [GRADING](docs/GRADING.md) | The four graders | Built |
| [ADAPTIVE](docs/ADAPTIVE.md) | Elo, FSRS and session planning | Built |
| [API](docs/API.md) | Endpoints, session lifecycle, SSE events | Mostly built |
| [SECURITY](docs/SECURITY.md) | Threat model, sandbox isolation, dependency audit | Built |
| [COST](docs/COST.md) | Model routing, budgets, the cost ledger | Built |
| [WEB](docs/WEB.md) | Web app routes and browser tests | Built |
| [PRACTICE_LOG](docs/PRACTICE_LOG.md) | Logging problems solved elsewhere | Built |
| [JOBS](docs/JOBS.md) | The job-application tracker | Built |
| [INFRA](docs/INFRA.md) | Docker Compose today, the AWS plan | Partly built |
| [OPERATIONS](docs/OPERATIONS.md) | Backups, restores, runbook | Partly built |
| [VOICE](docs/VOICE.md) | Voice interviews via Vapi | Spec |
