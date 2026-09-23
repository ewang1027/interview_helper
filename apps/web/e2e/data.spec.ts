import { expect, expectClean, expectStillAuthenticated, test } from "./fixtures";

/**
 * The pages render the database, not just their shell.
 *
 * `routes.spec.ts` proves each route mounts and its queries succeed. That is still
 * satisfied by a page stuck on skeletons, so these assert the figures and rows that
 * only exist once real data arrived — and they take the expected values from the API
 * at run time rather than hard-coding them, because this stack's database is a real
 * one that grows. A test that hard-codes "40 problems" fails the next time one is
 * logged, and a gate that fails for the wrong reason is one people learn to skip.
 */

// The same labels `mastery-heatmap.tsx` renders. Duplicated rather than imported
// because it is a private const there, and four strings are cheaper than an export
// that exists only for a test.
const DOMAIN_LABEL: Record<string, string> = {
  coding: "Coding",
  quant: "Quant",
  system_design: "System design",
  behavioral: "Behavioral",
};

interface CorpusStatus {
  concepts: number;
  concepts_by_domain: Record<string, number>;
  items: number;
  archetypes: number;
  instances: number;
}

test("the dashboard shows the figures GET /corpus/status reports", async ({
  page,
  request,
  diagnostics,
}) => {
  const status: CorpusStatus = await (await request.get("/api/v1/corpus/status")).json();

  await page.goto("/");
  await page.waitForLoadState("networkidle");

  // The denominator under "Concepts measured". It comes from a different endpoint
  // than the heatmap's cells, so seeing it agree in the DOM is a real cross-check.
  await expect(page.getByText(`of ${status.concepts} in the taxonomy`)).toBeVisible();

  // "Corpus" reports the item count, with the split beneath it.
  await expect(
    page.getByText(`${status.archetypes} archetypes · ${status.instances} instances`),
  ).toBeVisible();

  // Every stat left its loading dash behind.
  await expect(page.getByText("—", { exact: true })).toHaveCount(0);

  expectClean(diagnostics);
});

test("the mastery heatmap groups the whole taxonomy by domain", async ({
  page,
  request,
  diagnostics,
}) => {
  const status: CorpusStatus = await (await request.get("/api/v1/corpus/status")).json();

  await page.goto("/concepts");
  await page.waitForLoadState("networkidle");

  // One section per domain, each headed "<n> of <total> measured". The total is the
  // domain's concept count, which `/corpus/status` reports independently of the
  // taxonomy the heatmap is built from.
  for (const [domain, count] of Object.entries(status.concepts_by_domain)) {
    const heading = page.getByRole("heading", { level: 3 }).filter({
      hasText: DOMAIN_LABEL[domain] ?? domain,
    });
    await expect(heading, `no heatmap section for ${domain}`).toBeVisible();
    await expect(heading).toContainText(`of ${count} measured`);
  }

  await expectStillAuthenticated(page, "/concepts");
  expectClean(diagnostics);
});

test("/corpus agrees with GET /corpus/status", async ({ page, request, diagnostics }) => {
  const status: CorpusStatus = await (await request.get("/api/v1/corpus/status")).json();

  await page.goto("/corpus");
  await page.waitForLoadState("networkidle");

  for (const [label, value] of [
    ["Items", status.items],
    ["Archetypes", status.archetypes],
    ["Instances", status.instances],
    ["Concepts", status.concepts],
  ] as const) {
    // A Stat is a label div above a value div, with no role of its own, so the value
    // is reached from the label's parent — `48` on its own matches half the page, and
    // `filter({ has })` matches the label div itself, which contains no value.
    // Scoped to `main` because the nav also says "Concepts".
    const stat = page
      .locator("main")
      .getByText(label, { exact: true })
      .locator("xpath=..");
    await expect(stat, `the ${label} stat`).toContainText(String(value));
  }

  expectClean(diagnostics);
});

test("/history lists the sessions the API returns, newest first", async ({
  page,
  request,
  diagnostics,
}) => {
  const { sessions } = await (await request.get("/api/v1/sessions")).json();
  test.skip(sessions.length === 0, "no sessions in this database to list");

  await page.goto("/history");
  await page.waitForLoadState("networkidle");

  // Row links only: `/session/new` is in the nav on every page, and a reportable row
  // adds a `/session/<id>/report` link beside its own. Counting `a[href^="/session/"]`
  // found sixteen rows for fifteen sessions, which is how this got written.
  const rows = page.locator('main a[href^="/session/"]');
  const hrefs = (
    await rows.evaluateAll((links) => links.map((link) => link.getAttribute("href") ?? ""))
  ).filter((href) => /^\/session\/[^/]+$/.test(href));

  // The page pages its results, so the count is bounded rather than equal — but the
  // first row has to be the API's first session, which pins the order as well as the
  // rendering.
  expect(hrefs.length, "session rows rendered").toBeGreaterThan(0);
  expect(hrefs.length).toBeLessThanOrEqual(sessions.length);
  expect(hrefs[0]).toBe(`/session/${sessions[0].id}`);

  expectClean(diagnostics);
});

test("/practice counts the whole log and pages the rows", async ({
  page,
  request,
  diagnostics,
}) => {
  // `limit` caps at 100 — 500 is a 400, not a bigger page — so the whole log is read
  // by following `next_cursor` rather than by asking for one big page. This is what
  // `api.allProblems()` does in the app.
  let total = 0;
  let cursor: string | null = null;
  do {
    const query = new URLSearchParams({ limit: "100" });
    if (cursor) query.set("cursor", cursor);
    const body = await (await request.get(`/api/v1/practice/problems?${query}`)).json();
    total += body.problems.length;
    cursor = body.next_cursor ?? null;
  } while (cursor);
  test.skip(total === 0, "no logged problems in this database to list");

  await page.goto("/practice");
  await page.waitForLoadState("networkidle");

  // "Logged" is the whole log, not a page — the distinction the page's own docstring
  // makes, and the reason it loads every row before rendering any.
  const logged = page.locator("main").getByText("Logged", { exact: true }).locator("xpath=..");
  await expect(logged, "the Logged stat").toContainText(String(total));

  // The rows themselves are paged at twenty. This is what the first version of this
  // test got wrong: "loaded whole" is a claim about the data in memory, not about the
  // DOM, and asserting one row per problem found 38 links for 40 problems.
  const FIRST_PAGE = 20;
  if (total > FIRST_PAGE) {
    await expect(page.getByText(`Showing ${FIRST_PAGE} of ${total}`)).toBeVisible();

    // And the pager is real: asking for more renders more.
    await page.getByRole("button", { name: /^Load \d+ more$/ }).click();
    await expect(page.getByText(`Showing ${FIRST_PAGE} of ${total}`)).toBeHidden();
  }

  expectClean(diagnostics);
});

test("a concept page opens from its id", async ({ page, request, diagnostics }) => {
  const { concepts } = await (await request.get("/api/v1/mastery/weaknesses?limit=1")).json();
  test.skip(concepts.length === 0, "nothing ranked to open");
  const id = concepts[0].concept_id;

  await page.goto(`/concepts/${id}`);
  await page.waitForLoadState("networkidle");

  // The heading is the concept id itself, set in mono.
  await expect(page.getByRole("heading", { level: 1, name: id })).toBeVisible();

  await expectStillAuthenticated(page, `/concepts/${id}`);
  expectClean(diagnostics);
});

test("a logged problem opens from its id", async ({ page, request, diagnostics }) => {
  const { problems } = await (await request.get("/api/v1/practice/problems?limit=1")).json();
  test.skip(problems.length === 0, "no logged problems to open");
  const problem = problems[0];

  await page.goto(`/practice/${problem.id}`);
  await page.waitForLoadState("networkidle");

  await expect(page.getByRole("heading", { level: 1, name: problem.title })).toBeVisible();

  expectClean(diagnostics);
});
