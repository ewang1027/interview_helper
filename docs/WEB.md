# Web app

> **Status:** Specification — not started. Lands in **Phase 5**.
> Related: [API](API.md) (everything here consumes it) · [ADAPTIVE](ADAPTIVE.md) (what the dashboard visualizes)

Next.js 15 App Router, React 19, TypeScript strict, Tailwind v4, shadcn/ui, TanStack
Query v5, pnpm — matching the conventions already used in `backtest-lab`.

The web app is a **pure consumer of [API.md](API.md)**. It holds no secrets, contains no
business logic, and never talks to the database or a model provider. If a rule about
interviewing lives in the frontend, it is in the wrong place.

## Routes

| Route | Purpose |
|---|---|
| `/` | Dashboard — mastery heatmap, due queue, weakness list, recent sessions |
| `/session/new` | Pick mode and budget; shows the plan **before** you commit to it |
| `/session/[id]` | The live interview. Mode-specific workspace (below) |
| `/session/[id]/report` | Post-session report: per-item scores, per-concept evidence, hints taken |
| `/concepts` | The DAG, coloured by mastery — click through to a concept's evidence |
| `/concepts/[id]` | One concept: ability over time, the evidence behind it, related items |
| `/history` | Session history, filterable by mode and date |
| `/corpus` | Browse the corpus. Statements of unseen items stay redacted |
| `/costs` | Token and dollar spend from the ledger |

## The live session view

One shell, four workspaces. Shared: transcript panel, timer against the budget, hint
button showing its own cost, and an end-session control.

| Mode | Workspace |
|---|---|
| `coding` | Monaco editor, language toggle (Python/C++), run-tests button, test result panel |
| `quant` | Scratchpad for derivation, answer field with unit, optional timer for mental-math items |
| `design` | Structured component canvas — palette of nodes and edges, not freehand |
| `behavioral` | Transcript only, plus a STAR structure hint rail |

**Design mode uses a structured canvas, not freehand drawing.** A freehand diagram is far
harder to grade reliably, and a grader that cannot read the artifact produces vibes.
A constrained palette makes the artifact machine-readable, which is what
[GRADING.md](GRADING.md#system-design-and-behavioral) needs to cite criteria against it.

### Streaming

One `EventSource` per session against `GET /sessions/{id}/events`. Rules:

- Render `agent.message.delta` optimistically; **reconcile on `agent.message.done`**,
  which is authoritative.
- Track `seq` and reconnect with `Last-Event-ID` on drop; a gap means loss, and loss is
  visible rather than silently patched over.
- `budget.warning` surfaces as a banner, not a toast — it needs to persist.

## Dashboard

The mastery heatmap is the primary artifact: concepts as cells, coloured by ability,
sized or bordered by overdue-ness, grouped by domain.

Charts follow the `dataviz` skill — one visual system, accessible in both themes. Two
rules specific to this app:

- **Never colour ability on a red-to-green scale alone.** Overdue and weak are different
  states and must be separable without relying on hue discrimination.
- **Show evidence counts, not just scores.** A concept at 0.4 ability from two attempts is
  a different situation from 0.4 from thirty, and a heatmap that hides that is misleading.

## State management

- **Server state:** TanStack Query. Sessions, mastery, corpus, costs.
- **Live session state:** a reducer fed by the SSE stream. The server is the only writer
  of session state ([API.md](API.md#session-state-machine)); the client mirrors it.
- **Local UI state:** component-local. No global store — there is very little genuinely
  global state, and adding one invites business logic to migrate into the frontend.

## Testing

- Component tests for the four workspaces against recorded SSE fixtures, so no live
  backend is required.
- One Playwright end-to-end run per mode, against a seeded local stack. This is the
  Phase 5 gate: a full session in each mode driven entirely from the browser.

## Deployment

Built as a container like the other services, so `docker compose up` runs it anywhere
([INFRA.md](INFRA.md)). Whether it stays a Fargate service or becomes static hosting
behind CloudFront is a Phase 6 decision, deferred until there is something real to
measure.
