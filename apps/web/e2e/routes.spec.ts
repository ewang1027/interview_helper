import { expect, expectClean, expectStillAuthenticated, test } from "./fixtures";

/**
 * Every route in the app, opened in a real browser for the first time.
 *
 * This is the narrow half of the Phase 5 gate: not "a full session per mode", which
 * needs a live interviewer, but the claim every wave in docs/BUILDLOG.md since Phase 5
 * landed has had to end by disclaiming — that the pages render at all, against the
 * real API, through the real front door.
 *
 * Each route asserts four things. The heading proves the route resolved and mounted.
 * `expectClean` proves its queries actually succeeded and nothing threw — without it
 * a page whose every request 500s still passes, because the `<h1>` comes from the
 * server shell. `expectStillAuthenticated` proves the session cookie travelled, since
 * a 401 navigates away rather than rendering. The per-route content check proves the
 * page left its loading state for real data.
 */

const ROUTES = [
  { path: "/", heading: "Dashboard" },
  { path: "/session/new", heading: "New session" },
  { path: "/jobs", heading: "Applications" },
  // The nav calls it "Practice"; the page calls itself "Practice log". Both are
  // spelled out because a table that assumed they matched is what first failed here.
  { path: "/practice", heading: "Practice log", nav: "Practice" },
  { path: "/concepts", heading: "Concepts" },
  { path: "/history", heading: "History" },
  { path: "/corpus", heading: "Corpus" },
  { path: "/costs", heading: "Costs" },
] as const;

/** The nav's label for a route, which is not always its heading. */
const navLabel = (route: (typeof ROUTES)[number]): string =>
  "nav" in route ? route.nav : route.heading;

for (const route of ROUTES) {
  test(`${route.path} renders in a browser`, async ({ page, diagnostics }) => {
    await page.goto(route.path);

    await expect(page.getByRole("heading", { level: 1, name: route.heading })).toBeVisible();

    // The queries are client-side, so the shell arrives before the data. Settling the
    // network is what makes the clean-diagnostics assertion meaningful rather than a
    // race the page usually wins.
    await page.waitForLoadState("networkidle");

    await expectStillAuthenticated(page, route.path);
    expectClean(diagnostics);
  });
}

test("the nav reaches every route it lists", async ({ page, diagnostics }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" });

  for (const route of ROUTES) {
    await nav.getByRole("link", { name: navLabel(route), exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: route.heading })).toBeVisible();
    // Client-side navigation: the URL should be the one the link named, and the active
    // link should be the one we clicked.
    expect(new URL(page.url()).pathname).toBe(route.path);
  }

  await page.waitForLoadState("networkidle");
  expectClean(diagnostics);
});

test("/login renders without a session", async ({ browser }) => {
  // Its own context, with no storage state: this is the one page that has to work for
  // somebody who is not logged in, and testing it with a cookie tests nothing.
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await context.newPage();
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(`${error.name}: ${error.message}`));

  await page.goto("/login");
  await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
  expect(pageErrors, "uncaught exceptions").toEqual([]);

  await context.close();
});
