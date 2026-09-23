import { expect, expectClean, expectStillAuthenticated, test } from "./fixtures";

/**
 * The two paths through a session view that no component test can reach.
 *
 * docs/WEB.md is explicit that a page tested against a stubbed `api` object proves
 * nothing about the wiring — the cookie, the 401 redirect, the problem-document
 * parsing, the event stream. Both tests here are about that wiring, in a browser,
 * through the front door.
 */

interface SessionRow {
  id: string;
  mode: string;
  state: string;
}

async function anySession(request: {
  get: (url: string) => Promise<{ json: () => Promise<unknown> }>;
}): Promise<SessionRow | null> {
  const body = (await (await request.get("/api/v1/sessions")).json()) as {
    sessions: SessionRow[];
  };
  return body.sessions[0] ?? null;
}

test("a live session view connects its event stream", async ({ page, request, diagnostics }) => {
  const session = await anySession(request);
  test.skip(session === null, "no sessions in this database to open");
  const { id, mode, state } = session!;
  const finished = state === "complete" || state === "abandoned";

  await page.goto(`/session/${id}`);

  // Scoped to the page's own header throughout. The layout's nav is also a `<header>`,
  // and "open" is a word the item-status badges use too — unscoped, it matched the
  // connection indicator and an item badge and failed on strict mode.
  const header = page.locator("main header");

  await expect(page.getByRole("heading", { level: 1, name: `${mode} session` })).toBeVisible();
  await expect(header.getByText(state, { exact: true })).toBeVisible();

  // The connection indicator renders its state as text, so "open" is the browser
  // saying `EventSource` fired `onopen` — observed, rather than inferred from when a
  // header block lands on a socket, which is all the 2026-09-21 compression wave could
  // claim.
  //
  // Timed deliberately. The bug that wave found was Caddy's encoder holding the
  // *header* block until the first body byte, and the API pings every 15s — so a
  // regression there does not break the transcript, it just makes this take fifteen
  // seconds. A generous assertion would pass straight through it.
  const started = Date.now();
  const expected = finished ? "stream closed" : "open";
  await expect(header.getByText(expected, { exact: true })).toBeVisible({ timeout: 12_000 });
  const elapsed = Date.now() - started;

  if (!finished) {
    expect(
      elapsed,
      `the stream took ${elapsed}ms to open. Over ~15s means the front door is ` +
        "buffering the response header again — see infra/compose/Caddyfile.",
    ).toBeLessThan(10_000);
  }

  // No `networkidle` here: the event stream stays open by design on a live session,
  // so the network never goes idle and waiting for it would always time out.
  await expectStillAuthenticated(page, `/session/${id}`);
  expectClean(diagnostics);
});

test("a report that does not exist yet renders its problem document", async ({
  page,
  request,
  diagnostics,
}) => {
  const session = await anySession(request);
  test.skip(session === null, "no sessions in this database to open");
  const { id, state } = session!;
  test.skip(
    state === "complete" || state === "abandoned",
    "this session has a report; the error path needs one that does not",
  );

  await page.goto(`/session/${id}/report`);

  // A 409 is not a 401: the page renders the problem document rather than redirecting.
  // This is the whole of `ApiErrorNotice`'s contract — branch on the RFC 9457 `type`
  // slug, never the prose — exercised against a real problem document for the first
  // time.
  await expect(page.getByText("wrong-state", { exact: true })).toBeVisible();
  await expect(page.getByText("Wrong session state")).toBeVisible();
  await expect(
    page.getByText("The session is not in a state where this is possible yet."),
  ).toBeVisible();

  await expectStillAuthenticated(page, `/session/${id}/report`);

  // `expectClean` would be wrong here: the 409 *is* the expected behaviour. Asserting
  // the exact failure instead of no failure keeps the check honest — a 500, or a
  // second failed request, still fails this test.
  expect(diagnostics.failedRequests).toEqual([
    { path: `/api/v1/sessions/${id}/report`, status: 409 },
  ]);
  expect(diagnostics.pageErrors, "uncaught exceptions").toEqual([]);

  // Chrome logs every >=400 response to the console itself, so one console error is
  // expected here and is not the app's. It is matched rather than waived: anything
  // the app logged would not mention the 409 and would still fail.
  expect(diagnostics.consoleErrors, "console errors beyond the browser's 409 note").toEqual([
    expect.stringContaining("409"),
  ]);
});
