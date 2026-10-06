# Web app

> **Status:** Built (2026-08-24, `/jobs` added 2026-08-25) — **every route below
> exists**: the dashboard, `/session/new`, the live session view with a workspace per
> mode, the report, `/concepts`, `/concepts/{id}`, `/history`, `/corpus`, `/costs`,
> `/practice` and `/jobs`. `make check-web` and a CI job run eslint, tsc and 106 component
> tests. `/jobs` gained a **time-in-stage card** on 2026-09-29 — component tests only; the
> browser gate below has not been run since it landed.
> **Browser gate (2026-09-22, extended 2026-09-24, 2026-09-28 and 2026-09-29):** `make test-browser`
> drives all ten routes through Chromium against the containerised stack — **62 tests**,
> including axe-core **in both colour schemes**, keyboard focus order, and every route at
> a phone, a tablet (768px) and a small-laptop (1024px) width. **CI runs it** since
> 2026-09-29, in a job that builds the stack from the commit. The two contrast/structure violations it found were **fixed
> 2026-09-28**, and axe now reports none on any route, light or dark. It also found a real
> overflow on `/jobs`, **fixed 2026-09-24** — two causes, not the one first recorded; see
> **Testing**. **Theme:** follows the OS, or is pinned from the picker in the nav
> (2026-09-28); see **Colour**. The
> **full per-mode session** run is still owed. ~~CI has no stack to point the gate at~~ —
> **it does since 2026-09-29**; see **Testing**.
> **Not built:** `/corpus` lists nothing. ~~because the endpoint it needs does not
> exist~~ — **corrected 2026-09-22:** `GET /corpus/items` and `GET /corpus/items/{id}`
> were both built 2026-08-25 ([API](API.md)), and this page and the card on `/corpus`
> both went on saying otherwise for four weeks. The page was never wired to them; that
> is the work, and it is smaller than this line implied.
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
| `/history` | Session history, filterable by mode and date. Pages accumulate in the query cache (`useInfiniteQuery`), so they survive leaving the page and coming back |
| `/corpus` | Browse the corpus. Statements of unseen items stay redacted |
| `/jobs` | The job tracker — the application funnel, the category breakdown, the rejections tracker, time in stage, paste-import, and the board (searchable, filterable by outcome, twenty rows at a time) |
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
path, not the exception, and it gets a searchable picker over the whole 186-concept
taxonomy rather than a 186-option `<select>`. Since 2026-09-09 the picker searches each
concept's **aliases** as well as its name and id — the problem names a person actually has
in mind, *meeting rooms*, *group anagrams* — and shows the alias it matched beside the
name, so the reason a concept came up is visible. A name match ranks above an alias match.

**Importing solved problems** ([API](API.md#practice-log)) is on the same page: paste links
or slugs, or give a public LeetCode username. Imports arrive with a concept suggested from
LeetCode's own topic tags and a **Confirm all** action beside them, because fifty imports
otherwise means fifty searches through a 186-concept list. It confirms only what the tags
actually named; anything held back stays held back.

**NeetCode links are accepted there too** (2026-09-07), and a row that came from one is
badged with the list it is on — `NeetCode 150`, or `NeetCode` for the wider set. The badge
is the only visible difference: a NeetCode link imports the LeetCode problem it names, so
the title, the difficulty and the suggested concept all read as they would from a LeetCode
link, and pasting both forms of the same problem imports it once.

**The log is filed, searched and filtered in the browser** (2026-09-10). The page loads the
whole log — `api.allProblems` follows `next_cursor` to the end, which is the applications
board's scale decision made again — and then every control is instant: a search across
title, concept, topic, label and notes; filters for status, **topic** (the family the
concept is filed under, [CONCEPTS](CONCEPTS.md#topics)), difficulty (Easy/Medium/Hard read
out of whatever label the site gave), source, NeetCode list, **label** and due state; six
sorts; and a group-by that sections the list under topic, difficulty, label or status with
a count on each. Filter options are built from the log itself, with counts, so no control
names a topic or a label nothing carries. Rows show the concept by **name** rather than id,
a difficulty badge, the topic, the NeetCode list, and the person's **labels** as chips —
removable with a click, added by typing on the row, each edit sending the whole list to
`PATCH /practice/problems/{id}`. Paging is the board's (twenty, then ten, both numbers
printed); a grouped view shows every match, because a section cut off mid-way would
misreport every group after it. A search that matches nothing says *Nothing matches* and
keeps its controls, for the reason the board's does. Four behaviours are pinned in
`practice.test.tsx`: topic filter and grouping, search and the empty match, label add and
remove, and the log loading across cursor pages.

Three refusals are surfaced rather than hidden, because each one means something:

- A problem awaiting its tag shows **needs a tag** and says plainly that it counts for
  nothing yet.
- Recording a re-solve against such a problem is a `409`, so the control is disabled with
  the reason given — the solve would have nowhere to write its evidence.
- A resolved classification cannot be re-tagged. `concept_evidence` is immutable, so the
  page says so instead of offering an edit that would be refused.

### The board: search, and twenty rows at a time

Added 2026-09-03, when the board had grown past fifty rows and the job it exists for —
*move this one along* — had become scrolling for the row first. Two affordances, and the
decisions behind them are worth stating because each has an obvious wrong version:

- **Search is client-side, and that is a scale decision rather than a shortcut.**
  `GET /jobs` already returns the whole list in one response (`limit` defaults to 200), so
  every row is in the browser before anything is typed. Filtering there costs no request
  and cannot go stale against the list it filters; a server-side `q=` would be a second
  way to ask a question the page has already asked. It stops being right when the list
  outgrows that limit, at which point the search belongs in SQL and the component keeps
  its shape.
- **It covers company, role and location**, matching every whitespace-separated term in
  any order — so "aurora backend" finds what "backend aurora" finds. Word order is not
  something a person should have to guess at, and the placeholder names the three fields
  rather than leaving the scope to be discovered by a search that silently matches
  nothing.
- **Twenty rows, then ten per click — and ten back.** The count beside the buttons prints
  both numbers (`Showing 20 of 47`), for the reason the heatmap prints evidence counts in
  its cells: a list that silently stops at twenty reads as a complete list of twenty. Each
  button names what it will actually do, so the tail of a list says `Load 5 more` rather
  than promising ten it cannot give, and `Load 5 less` when five is all that stands
  between the board and the twenty it opened with. Both steps are computed from the rows
  **on screen** rather than from the counter behind them, which can sit above it — the
  last `Load 5 more` of a 35-row list takes that counter to 40, and a collapse measured
  from there would hide five rows while promising ten. Neither button renders when it
  would do nothing: `Load less` is absent at twenty, `Load more` at the end of the list.

Two states that would otherwise be wrong are handled explicitly. A search matching nothing
says so **and keeps the search box** — "No applications yet" would be both false and
unrecoverable, since there would be no control left to clear. And the window survives a
refetch but not a filter change: moving a row's stage re-fetches the list, and collapsing
the board back to twenty there would scroll the row you were working on out of existence,
so the component is keyed on the category filter and deliberately not on its data. All
five behaviours are pinned by tests in `src/app/jobs/jobs.test.tsx`.

### The rejections tracker

Added 2026-09-09, asked for directly. A `Rejected` headline stat with its share of
everything applied to, and a card that reads the funnel downward: **which rung each no came
after** as one-hue bars — the share of rejections printed beside each, rungs above the last
one used dropped, an empty rung *between* used ones kept because it is the shape of the
pipeline — a median days-from-applying line, and the ten most recent rejections with the
stage each got to and how long it took. All of it comes from `GET /jobs/stats`'s
`rejections` block ([JOBS](JOBS.md), decision 5), so the card and the funnel cannot count
differently.

Two decisions worth stating. The bars share the funnel's hue rather than turning red: the
share is what varies, and a red ramp would say "worse" about a number that only means
"later". And the card links to the board rather than listing everything itself: *Show all
on the board* sets an **outcome filter** the board now carries beside the category one —
All · Live · Rejected — which re-keys the board so it opens fresh at twenty rows, exactly as
a category change does. Three behaviours are pinned in `jobs.test.tsx`: the rung and the
date, the empty state, and the filter reaching `GET /jobs?outcome=rejected`.

### Time in stage

Added 2026-09-29, from the list of what Phase 10 still owed. A card under the
rejections tracker, from `GET /jobs/stats`'s `time_in_stage` block ([JOBS](JOBS.md),
decision 6), in the same two-column shape. **Before moving on**: one line per rung that has
something to say — median and mean days over the applications that left it, how many did,
and how many are waiting there now. **Waiting longest**: the ten open applications that
have sat longest on their current rung, with the rung and the days since their last event.
Both columns are `min-w-0`, for the phone-overflow reason recorded against the rejections
card. Printed as text rather than bars: the medians are few, small and on different
denominators, and a bar would give a rung with one stint the same visual weight as one
with forty.

The import result also says **how many rows the research pass was sent** —
`researched N rows · M searches` — because the trigger is per row now and "researched"
alone no longer says which rows were looked up.

Pinned in `jobs.test.tsx`: the per-rung line and the longest-waiting order, the empty
state, and the researched-row count.

## The live session view

One shell, four workspaces. Shared: transcript panel, timer against the budget, hint
button showing its own cost, and an end-session control.

| Mode | Workspace |
|---|---|
| `coding` | Monaco editor, language toggle (Python/C++), run-tests button, test result panel |
| `quant` | Scratchpad for derivation, answer field with unit, optional timer for mental-math items |
| `design` | Structured component canvas — palette of nodes and edges, not freehand |
| `behavioral` | Transcript only, plus a STAR structure hint rail |

### Monaco is vendored, and only the part this editor uses

`@monaco-editor/react` loads the editor from `cdn.jsdelivr.net` unless told otherwise,
which would mean a self-hosted deployment with no egress has a workspace that never
finishes loading, and a version chosen by the loader package rather than by this
lockfile. `scripts/vendor-monaco.mjs` copies it out of `node_modules` into
`public/monaco/<version>/vs` at build time instead; the tree is gitignored, because it is a
build artifact of a pinned dependency.

**It copies 12.93 MB of the 23.29 MB `min/vs` weighs** (2026-09-21). `min/vs` is Monaco's
everything-build, and this editor only ever holds Python or C++, so the TypeScript, CSS,
HTML and JSON language workers (8.8 MB, `ts.worker` alone 6.7 MB) and the twelve locale
bundles (1.7 MB) are left behind. Both were checked against the code that would request
them rather than assumed: a locale is fetched only when `availableLanguages["*"]` is set
to something other than `"en"`, and a language worker only when a model of that language
exists. The small loader shims stay, so a language that somehow *were* used 404s on its
payload rather than failing obscurely — and that 404 is the signal the `SKIP` list needs
revisiting.

This is image size, not page load: nothing removed was ever fetched by a browser running
this app. The editor's critical path is 9 files and 3.14 MB, served and verified over
HTTP against a production build.

**It is cached for a year, and the version in the path is what makes that safe**
(2026-10-03). Next serves `public/` with `max-age=0`, so every coding session sent 18
conditional requests for Monaco and got 18 `304`s back. `next.config.ts` now sends
`public, max-age=31536000, immutable` for `/monaco/*`. Most of Monaco's files are
content-hashed, but `loader.js` and `editor.js` are not, so a year-long cache on a fixed
path would serve a stale loader after an upgrade. The vendor script therefore writes to
`public/monaco/<version>/vs`, `next.config.ts` reads the same version and inlines it as
`MONACO_VERSION`, and `coding.tsx` points the loader there. An upgrade gets a new URL.

**Per-concept links do not prefetch** (2026-10-03). The mastery heatmap and the weakness
list render one `<Link>` per concept, and Next prefetches every link in the viewport.
`/concepts/[id]` is dynamic, so each prefetch was a server render: `/` fired 137 of them
per load and `/concepts` fired 163, queued ahead of the page's own API calls. Those links
carry `prefetch={false}` and the route is fetched on click.

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
while its `limit` caps at 100 against 186 concepts, the largest single domain is 79, so
splitting by mode is what makes the heatmap complete rather than merely convenient. A
`GET /concepts` endpoint would replace this, and `/concepts` below needs one anyway to
draw the DAG.

## State management

- **Server state:** TanStack Query. Sessions, mastery, corpus, costs.
- **Live session state:** a reducer fed by the SSE stream. The server is the only writer
  of session state ([API.md](API.md#session-state-machine)); the client mirrors it.

  The stream re-renders this page **once per streamed token**. `Workspace` is therefore
  `memo`'d and the `onChange` handed to it is `useCallback`'d — a token has no business
  reaching the editor, and an inline arrow at the call site would silently undo that. For
  the same reason Monaco's `options` is a hoisted constant with `readOnly` merged through
  a `useMemo`: `@monaco-editor/react` keys `updateOptions()` on that object's identity,
  and a new one per render meant a validation pass per token (2026-09-21).
- **Local UI state:** component-local. No global store — there is very little genuinely
  global state, and adding one invites business logic to migrate into the frontend.

## Colour: two palettes, two jobs

Until `/jobs` there was one chart palette here — the **ability ramp**, a single hue from
light to dark, encoding *how much*. The job tracker needed a second kind, and the
distinction is worth stating because reaching for the wrong one is the usual way a chart
starts lying:

- **Sequential** (`--ability-1..5`) encodes **magnitude**. One hue. More is darker. The
  mastery heatmap uses it; so does anything where the steps are ordered.
- **Categorical** (`--series-swe`, `--series-ai`, `--series-quant`, `--series-other`)
  encodes **identity**. Four fixed hues, assigned per entity and never cycled or reordered,
  so hiding one category cannot repaint the others.

The funnel on `/jobs` uses *neither*: it is one series, so bar length carries the magnitude
and the colour is constant. A ramp across its rungs would imply the stage itself had a
magnitude.

The four categorical hues were **validated rather than chosen** — worst adjacent CVD ΔE 9.1
light / 8.4 dark, normal-vision 22.9 / 19.8, against both surfaces. Two of them sit below
3:1 on the light surface, so every mark using them ships a visible text label; identity is
never carried by colour alone on that page, which is the same rule the heatmap keeps when it
prints evidence counts in its cells.

### Light and dark (2026-09-28)

`globals.css` has carried a dark palette since Phase 5, applied under
`prefers-color-scheme: dark`, with `<html data-theme>` overriding the OS either way.
Until 2026-09-28 nothing set that attribute and nobody had measured the dark theme.

- **The picker** is a native `<select>` at the right of the nav — System, Light, Dark.
  A pinned choice is kept in `localStorage` under `theme`; "System" removes it. A
  one-line script in `<head>` (`lib/theme-bootstrap.ts`) applies it before first paint,
  so a pinned theme never flashes the other one. Storage that throws means "System".
- **Monaco** draws its own colours and reads no CSS variable, so the coding workspace
  asks `useIsDark()` (`lib/theme.ts`) and passes `vs-dark` or `light`. Before this it
  stayed a white editor inside a dark page.
- **Heatmap cell ink is a token per ramp step** (`--ability-ink-1..5`), set per theme.
  The light ramp wants white ink from step 4; the dark ramp only on step 5. The rule it
  replaced — dark ink on the two lightest steps and on unmeasured cells — was written for
  light mode, and in dark mode drew near-black on `--ability-none` (**1.25:1**) and white
  on the mid steps (**2.5:1**). Those were the only dark-mode failures axe found. The
  middle light step (`#2a78d6`) is the awkward one: `#0b0b0b` is 4.46:1 on it and white
  4.42:1, so it takes pure black at 4.76:1.

The contrast fixes moved three token values, each noted where it is defined:

| Token | Was | Now | Why |
|---|---|---|---|
| `--ink-muted` (light) | `#898781` | `#6f6d67` | 3.4–3.49:1 on page and surface; now ≥ 4.58:1 on all three surfaces |
| `--ink-muted` (dark) | `#898781` | `#918f89` | passed on page and surface, 4.38:1 on sunken; now 4.86:1 |
| `--accent` (light) | `#2a78d6` | `#2670c9` | white on it was 4.41:1; now 4.95:1. `--ability-3` and `--series-swe` keep the validated `#2a78d6` |

## Testing

- Component tests for the four workspaces against recorded SSE fixtures, so no live
  backend is required. **Built** — `pnpm test`, in `make check-web` and in CI. **106 tests**
  covering the stream reducer, the heatmap, three of the four workspaces, the API client,
  and the dashboard, session-creation, report, practice-log, applications, history and
  login pages.

  Pages are tested with **`fetch` stubbed, not `api` stubbed**, which is the choice that
  makes them worth having: it exercises the client in `lib/api.ts` too — the problem+json
  parsing, the `401` redirect, `credentials: "include"` — which is where a page's error
  handling actually lives. A page tested against a stubbed `api` object passes while every
  one of those is broken.

  The coding workspace's *contract* is deliberately untested: it renders Monaco, which
  does not run under jsdom, and asserting against a stub of the editor would test the
  stub. `coding.test.tsx` asserts something narrower that a stub can answer honestly —
  the identity of the props handed to the editor across a simulated token stream, which
  is a fact about this code rather than about Monaco.
- One Playwright end-to-end run per mode, against a seeded local stack. This is the
  Phase 5 gate: a full session in each mode driven entirely from the browser. **Still
  owed** — it needs a live interviewer, so it is gated on the same model access
  everything else here is.

### The browser gate that does exist — `make test-browser`

`apps/web/e2e/`, 20 tests in Chromium when it landed (62 since 2026-09-29, and in CI — see below), against the stack `make up-stack` runs rather
than a dev server this config starts. That distinction is the point: `next dev` proxies
the API itself, so only the container topology exercises the same-origin `/api/v1`, the
cookie and the SSE carve-out that the front door is responsible for.

Each route asserts four things, and the second is the one that makes the gate worth
having:

1. its `<h1>` renders — the route resolved and mounted;
2. **every `/api/v1` request the page made returned 2xx, and nothing threw.** Without
   this a page whose every query 500s still passes, because the heading comes from the
   server shell;
3. it did not navigate to `/auth/login` — a 401 redirects rather than rendering, so
   staying put is a direct test of the session cookie;
4. the figures on the page match what the API reports, read at run time rather than
   hard-coded, because this database is a real one that grows.

Authentication is a real signed cookie from `python -m api.mint_session`, the same
module `make login` calls, installed on the browser context — not a stub, so the
verifier is still under test.

**It was checked against broken code.** With one character changed in the cookie, all
eight route tests fail. A gate nobody has seen fail is not evidence it can.

### Accessibility and phone width — `a11y.spec.ts`, `mobile.spec.ts` (2026-09-24)

axe-core over the eight list routes at desktop width, **in the light and the dark scheme**
(dark added 2026-09-28), and every route measured again at 390×844. Focus and keyboard order are checked directly: a real `Tab` press has to land
on a control with a non-zero `:focus-visible` outline, and the nav's links have to be
reachable in the order they are written — the nav is on all ten routes, so a tab order
that skips part of it is one fault ten times over.

**The axe check asserts the set of rule ids per route.** It landed with two real
violations named per route in `KNOWN`, and each had a single cause. **Both fixed
2026-09-28** — every route now expects no violation in either scheme, and a rule id left
in `KNOWN` that stops appearing fails too:

| Rule | Cause | Scale |
|---|---|---|
| `color-contrast` | `--ink-muted: #898781` is **3.4–3.49:1** on the page and surface backgrounds where AA wants 4.5:1 — and it is the colour of every caption, stat note and hint. `--accent` under white ink is **4.41:1**, also just under | 12–228 nodes per route, from two token values |
| `nested-interactive` | the weakness list's `<summary>` contains a `<Link>`; a `summary` has an implicit button role, so the link is a focusable descendant of a control | 8 on the dashboard, 100 on `/concepts` |

**Fixed:** the three token values in **Colour → Light and dark** above; and the weakness
list's row is now a link and a separate `aria-expanded` button, siblings rather than one
inside the other, so the `stopPropagation` that worked around the nesting is gone.

They were carried as known debt because both were design decisions — darkening the
caption colour changes how every page looks — and **anything else failed** meanwhile,
including these two appearing on a route not listed. Node counts are not asserted: they scale with the database
and drifted between two runs of the same page (228, then 227 on `/concepts`).

~~`/jobs` **overflows a phone viewport by ~86px** … the rejections tracker's rows are a
fixed `w-10` count, a `flex-1 min-w-0` bar and a label reading "67% of rejections" that
carries neither `shrink-0` nor a wrapping allowance.~~ **Fixed 2026-09-24, and that
cause was wrong.** The label was a symptom picked out of a deepest-element-first listing;
the page had **two independent causes**, each about 420px wide, so fixing either alone
left the overflow looking barely changed:

1. **`CardHeader`'s action slot was `shrink-0`.** Correct for the short "All" link most
   cards put there; wrong for the ten filter buttons `/jobs` puts there. A `shrink-0`
   wrapper takes its width from its content, and that content is `flex flex-wrap`, whose
   base size is every button on one line — 427px. So it pinned the header row open.
2. **The rejections grid's two columns had no `min-w-0`.** A grid item's default
   `min-width: auto` floors it at its content's min-content width, and the role name in
   "Most recent" is `truncate`, therefore `white-space: nowrap`, therefore min-content is
   the whole string — 421px of "Software Engineer Intern, Cloud Services (Summer 2027)".
   The span's own `min-w-0 truncate` could do nothing about an ancestor's floor. Above
   `md` it never showed, because Tailwind's `grid-cols-2` already expands to
   `minmax(0, 1fr)`.

**The first attempt at (1) traded the bug for a worse one.** Making the action slot
shrinkable cleared `/jobs` and overflowed **`/concepts` by 111px**, because it puts five
mode buttons in that slot in a `flex` that does *not* wrap. The fix is `flex-wrap` on the
header row **and** a shrinkable action, together: when title and action cannot share a
line the action drops to its own, full-width, and then has room either to wrap or to stay
whole. Both halves are in `CardHeader`, with the measurement in a comment.

That trade is the argument for asserting **every** route rather than the one with the
known bug — a gate watching only `/jobs` would have called the first attempt a success.
`/jobs` was carried as a `test.fail()` until the fix landed, which was itself verified by
simulating a fix and watching the run go red with "expected to fail but passed".

**Still unproven:** screen-reader output, which no automated rule covers; the four
session workspaces, which need a live session to render — in either scheme, so the dark
Monaco theme has been wired but not seen; ~~and any viewport between 390px and 1440px~~
— **768px and 1024px measured 2026-09-29**, see below; widths between 1024px and the
1280px desktop default are still not asserted. ~~`prefers-color-scheme: dark` … has not
been measured~~ — **measured 2026-09-28**; see above.

### Tablet and small-laptop widths, and the gate in CI (2026-09-29)

**`mobile.spec.ts` runs every route at three widths**: 390×844, **768×1024** and
**1024×768** — 24 overflow tests where there were 8, 62 in the gate. 768 and 1024 are
Tailwind's `md` and `lg` breakpoints exactly, the narrowest width each wider layout
switches on at, which is where a two-column grid or an inline header that fits at 1280
is most likely not to. The assertion is the phone test's, unchanged: the document does
not scroll sideways. **Nothing overflowed** at either new width. That the new widths can
fail was checked, not assumed: a 900px element injected into every page failed all 16
tests at 390 and 768 and none at 1024, as it should.

**CI runs the gate** in a `browser` job of its own (`.github/workflows/ci.yml`). The
runner has Docker, so it runs the same compose file `make up-stack` does — Caddy, the
same-origin `/api`, the real cookie — built from the commit, then `playwright test`.
What it needs, and how the job provides it without a real secret:

| Needs | In CI |
|---|---|
| `SESSION_SECRET`, shared by the API container and the host-side `api.mint_session` | generated in the job into a throwaway `.env`, masked, gone with the runner |
| `COOKIE_SECURE=false` (plain http on localhost) | same `.env` |
| a migrated schema and the corpus | Postgres started alone, then `alembic upgrade head` and `api.seed` from the host |
| a `users` row to mint a cookie for | created by `mint_session` itself on first use (`single_user`) |
| a session, for `/history`, the event stream and the report's 409 | one `POST /api/v1/sessions` through the front door — the planner is deterministic, so no model |
| a model provider | **none** — no spec reaches a model |

**Two specs skip in CI**, with the reason they print: `/practice`'s count-and-pager and
opening a logged problem. Both need a logged practice problem, and logging one runs the
classification call, which is a model. Locally, against the real database, all 62 run.

On failure the job uploads `apps/web/.playwright/` — the HTML report, traces and
screenshots — and the stack's logs as the `playwright-report` artifact.

**The two runs mean different things.** Locally the gate runs against your real data,
which is what catches a page that breaks on the shape of real rows. In CI it runs
against the code on a nearly empty database, which is what catches a change that breaks
the page on every machine. Neither replaces the other.

## Deployment

Built as a container like the other services, so `docker compose up` runs it anywhere
([INFRA.md](INFRA.md)). Whether it stays a Fargate service or becomes static hosting
behind CloudFront is a Phase 6 decision, deferred until there is something real to
measure.
