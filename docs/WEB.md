# Web app

> **Status:** Built (2026-08-24) — **every route below exists**: the dashboard,
> `/session/new`, the live session view with a workspace per mode, the report,
> `/concepts`, `/concepts/{id}`, `/history`, `/corpus` and `/costs`. `make check-web` and
> a CI job run eslint, tsc and 26 component tests.
> **Not built:** the Playwright gate; `/corpus` lists nothing, because the endpoint it
> needs does not exist (see that section); Monaco loads from a CDN. Nothing here has been
> opened in a browser yet — see the caveat under **Testing**, which is the most important
> line on this page.
> Related: [API](API.md) (everything here consumes it) · [ADAPTIVE](ADAPTIVE.md) (what the dashboard visualizes)

Next.js 15 App Router, React 19, TypeScript strict, Tailwind v4, shadcn/ui, TanStack
Query v5, pnpm — matching the conventions already used in `backtest-lab`. **Pinned to
15.5.20**, because `create-next-app@latest` now installs Next 16 and taking a major
version this document had not sanctioned is not a scaffolding decision. shadcn primitives
are vendored by hand into `src/components/ui/` rather than pulled through its CLI, which
is what that project's copy-in model amounts to anyway.

The web app is a **pure consumer of [API.md](API.md)**. It holds no secrets, contains no
business logic, and never talks to the database or a model provider. If a rule about
interviewing lives in the frontend, it is in the wrong place.

## One origin, and why

Auth is a cookie it never reads: `HttpOnly`, so JavaScript cannot see it by design. Every
request needs `credentials: "include"`, an unauthenticated route should send the browser to
`/auth/login` rather than rendering an error, and a `401` mid-session means the cookie
expired ([API.md](API.md#auth)).

**A 401 goes to `/login`, this app's own page, not to the API's `/auth/login`.** The
instruction above says to send the browser to `/auth/login`, and doing that literally
dead-ends: that route answers `503 not-configured` when OAuth is unset, so the user is
handed a raw `application/problem+json` document with no way forward. Correct of the
server — an OAuth app with no `GITHUB_ALLOWED_ID` would admit *any* GitHub user to a
single-user deployment, so it refuses rather than running weakened — and useless to a
person. `/login` works out which of three states the deployment is in first: signed in
(go back), OAuth ready (offer the button), or unconfigured (say what is unset, and that
`make login` is the supported way in locally). It never adds an unsupported one: there is
deliberately no dev-login route and no `AUTH_MODE` flag ([API](API.md#auth)), because a
flag is a thing that can be wrong in production.

**Running the OAuth flow through this origin means `GITHUB_REDIRECT_URI` is the web app's
port, not the API's.** The callback's `Set-Cookie` is stored against whichever origin
answered the request, so a callback on `:8000` produces a cookie the browser will not send
to `:3000` — the same cross-site problem the proxy exists to remove, arriving through the
one route that bypasses it. Next forwards `/auth/*` and passes `Set-Cookie` back unchanged
(verified), so the whole flow runs on one origin.

`credentials: "include"` is necessary and **not sufficient**, which is the first thing
building this found. The cookie is `SameSite=Lax` and set on the API's origin, and
`apps/api` mounts no CORS middleware — so a page on `localhost:3000` fetching
`localhost:8000` is cross-site, the cookie is withheld, and the request is refused before
that matters.

So there is only ever one origin. `next.config.ts` rewrites `/api/*`, `/auth/*` and
`/health` to `API_ORIGIN`; the browser talks to the Next server and nothing else. The
cookie stays first-party, the API keeps no browser-origin allowlist to get wrong, and this
is already the deployment shape — one ALB routing by path ([INFRA](INFRA.md)) — so
development and production differ in hostnames and nothing else. The alternative,
`SameSite=None; Secure` plus a CORS allowlist, weakens the cookie and adds a list to
maintain, for a service with exactly one browser client.

## Routes

| Route | Purpose |
|---|---|
| `/login` | Sign in — and, when OAuth is unconfigured, what to do instead |
| `/` | Dashboard — mastery heatmap, due queue, weakness list, recent sessions |
| `/session/new` | Pick mode and budget; shows the plan **before** you commit to it |
| `/session/[id]` | The live interview. Mode-specific workspace (below) |
| `/session/[id]/report` | Post-session report: per-item scores, per-concept evidence, hints taken |
| `/concepts` | The DAG, coloured by mastery — click through to a concept's evidence |
| `/concepts/[id]` | One concept: ability over time, the evidence behind it, related items |
| `/history` | Session history, filterable by mode and date |
| `/corpus` | Browse the corpus. Statements of unseen items stay redacted |
| `/practice` | The practice log — log a problem solved elsewhere, and what is due to re-solve |
| `/practice/[id]` | One logged problem: confirm its concept, record a re-solve, read its evidence |
| `/costs` | Token and dollar spend from the ledger |

`/corpus` shows what `GET /corpus/status` reports and then says plainly that browsing is
not built, rather than rendering an empty browser: reading an item you have not been
served defeats the measurement, so it needs `GET /corpus/items/{id}` (specified, not
built) *and* something listing item ids to reach it with (not specified). An empty
browser looks broken; a stated gap is a gap.

`/concepts` assembles the taxonomy from four weakness rankings, one per mode, for the
reason given under **Dashboard** — there is no `GET /concepts`.

### The practice log

Added 2026-08-24, and it was missing rather than deferred: this document is a **Phase 5**
spec written before **Phase 9** existed, so its route table never gained a page for the
practice log. The six endpoints shipped on 2026-08-21, a logged solve moved the same
mastery a graded submission does — and there was no way to log one. The dashboard's "due
for review" card read the queue and nothing could fill it.

The state the pages are designed around is **`pending_classification`**. A classification
below 0.75 confidence writes no evidence, and neither does one whose provider was
unreachable; the problem is recorded, listed, kept out of the review queue and feeds
nothing until a human confirms the tag ([PRACTICE_LOG](PRACTICE_LOG.md)). Since no model
provider is reachable yet, that is *every* entry today — so confirming a tag is the common
path, not the exception, and it gets a searchable picker over the whole 159-concept
taxonomy rather than a 159-option `<select>`.

**Importing from LeetCode** ([API](API.md#practice-log)) is on the same page: paste links
or slugs, or give a public username. Imports arrive with a concept suggested from LeetCode's
own topic tags and a **Confirm all** action beside them, because fifty imports otherwise
means fifty searches through a 159-concept list. It confirms only what the tags actually
named; anything held back stays held back.

Three refusals are surfaced rather than hidden, because each one means something:

- A problem awaiting its tag shows **needs a tag** and says plainly that it counts for
  nothing yet.
- Recording a re-solve against such a problem is a `409`, so the control is disabled with
  the reason given — the solve would have nowhere to write its evidence.
- A resolved classification cannot be re-tagged. `concept_evidence` is immutable, so the
  page says so instead of offering an edit that would be refused.

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
  which is authoritative. In practice that means *replacing* the delta buffer with the
  `done` payload rather than comparing against it — replacing is the only handling that
  survives a delta that never arrived.
- Track `seq` and reconnect with `Last-Event-ID` on drop; a gap means loss, and loss is
  visible rather than silently patched over.
- `budget.warning` surfaces as a banner, not a toast — it needs to persist.

Three properties of the server's wire format that a client has to be built around, each
found by building one:

- **Every frame is named.** The server writes `event: <type>`, and a browser dispatches a
  named frame only to a listener registered for that name — `onmessage` sees unnamed frames
  and nothing else. A client subscribing the obvious way sits silent for a whole session
  and reports no error, so `EVENT_TYPES` lives beside the event union and is the list that
  gets subscribed.
- **A terminal state has to close the stream from this side.** The server closes the
  connection when the session finishes; `EventSource` treats every close as a fault and
  reconnects indefinitely. Without an explicit close on the terminal `session.state`, a
  finished session in a background tab reopens a stream every few seconds forever.
- **`seq` is checked client-side too.** `stream.gap` is only sent for a *resume point* the
  buffer no longer holds, and that check runs once, at stream open — while a single turn
  can emit more events than the 256-slot buffer holds ([API.md](API.md#sse-event-stream)).
  A mid-stream jump is therefore invisible to the server, so the reducer flags it itself.

## Dashboard

The mastery heatmap is the primary artifact: concepts as cells, coloured by ability,
sized or bordered by overdue-ness, grouped by domain.

Charts follow the `dataviz` skill — one visual system, accessible in both themes. Two
rules specific to this app:

- **Never colour ability on a red-to-green scale alone.** Overdue and weak are different
  states and must be separable without relying on hue discrimination. Built: ability is a
  single-hue sequential ramp, and overdue is a ring **plus a corner wedge** — a shape, so
  the state survives greyscale entirely.
- **Show evidence counts, not just scores.** A concept at 0.4 ability from two attempts is
  a different situation from 0.4 from thirty, and a heatmap that hides that is misleading.
  Built: the observation count is printed in every cell.

**Cells band on Elo, not on the server's `normalized_ability`** — a legibility decision
with a measurement behind it. `normalized_ability` divides by the full rating scale (floor
600, ceiling 2800), so the 1550 every concept starts at normalises to 0.43 and a concept
moved 200 points by real evidence still sits between 0.34 and 0.52. Banded on it in equal
widths, sixteen measured concepts spanning 1501–1560 Elo all landed in one step and the
chart came out a single colour. The cutoffs are centred on 1550 instead and the legend
prints them.

**The taxonomy is assembled from four weakness rankings, one per mode.** There is no
`GET /concepts`, and `GET /mastery` returns only *measured* concepts, without a name or a
domain on the row. The weakness ranking carries both and ranks the whole taxonomy — and
while its `limit` caps at 100 against 159 concepts, the largest single domain is 52, so
splitting by mode is what makes the heatmap complete rather than merely convenient. A
`GET /concepts` endpoint would replace this, and `/concepts` below needs one anyway to
draw the DAG.

## State management

- **Server state:** TanStack Query. Sessions, mastery, corpus, costs.
- **Live session state:** a reducer fed by the SSE stream. The server is the only writer
  of session state ([API.md](API.md#session-state-machine)); the client mirrors it.
- **Local UI state:** component-local. No global store — there is very little genuinely
  global state, and adding one invites business logic to migrate into the frontend.

## Testing

- Component tests for the four workspaces against recorded SSE fixtures, so no live
  backend is required. **Built** — `pnpm test`, in `make check-web` and in CI. **73 tests**
  covering the stream reducer, the heatmap, three of the four workspaces, the API client,
  and the dashboard, session-creation, report, practice-log and login pages.

  Pages are tested with **`fetch` stubbed, not `api` stubbed**, which is the choice that
  makes them worth having: it exercises the client in `lib/api.ts` too — the problem+json
  parsing, the `401` redirect, `credentials: "include"` — which is where a page's error
  handling actually lives. A page tested against a stubbed `api` object passes while every
  one of those is broken.

  The coding workspace is deliberately untested: it renders Monaco, which does not run
  under jsdom, and asserting against a stub of the editor would test the stub.
- One Playwright end-to-end run per mode, against a seeded local stack. This is the
  Phase 5 gate: a full session in each mode driven entirely from the browser. **Owed.**

**Nothing here has been opened in a browser.** The environment building it has no browser
tooling, so layout, contrast in situ, focus order and keyboard navigation are unproven.
The component tests assert structure and class names, which is a weaker claim than it
looks: they would not catch a collision, an overflow, or a control nothing can reach by
keyboard. Treat the visual layer as unreviewed until the Playwright gate lands.

## Deployment

Built as a container like the other services, so `docker compose up` runs it anywhere
([INFRA.md](INFRA.md)). Whether it stays a Fargate service or becomes static hosting
behind CloudFront is a Phase 6 decision, deferred until there is something real to
measure.
