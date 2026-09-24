import { expect, expectClean, test } from "./fixtures";

/**
 * Every route at a phone width.
 *
 * docs/WEB.md named "a collision, an overflow" as the kind of fault the component tests
 * cannot see, and the 2026-09-22 browser gate ran at one desktop viewport only, so it
 * could not see them either. The first run of this found a real one on `/jobs`.
 *
 * The assertion is that the **page** does not scroll sideways. A deliberately scrollable
 * element inside the page is fine and several exist — the nav is `overflow-x-auto` by
 * design, and so is the corpus table — which is why this measures the document rather
 * than hunting for wide descendants.
 */

// 390x844 is an iPhone 14/15 at its CSS width, the narrowest thing worth designing for.
test.use({ viewport: { width: 390, height: 844 } });

const ROUTES = [
  "/",
  "/session/new",
  "/practice",
  "/concepts",
  "/history",
  "/corpus",
  "/costs",
] as const;

async function horizontalOverflow(page: import("@playwright/test").Page): Promise<number> {
  await page.waitForLoadState("networkidle");
  return page.evaluate(() => {
    const root = document.documentElement;
    // +1 to absorb sub-pixel rounding, which otherwise reports a 0.5px overflow on a
    // page that is fine.
    return Math.max(0, root.scrollWidth - root.clientWidth - 1);
  });
}

for (const route of ROUTES) {
  test(`${route} does not scroll sideways on a phone`, async ({ page, diagnostics }) => {
    await page.goto(route);
    const overflow = await horizontalOverflow(page);
    expect(overflow, `${route} overflows its viewport by ${overflow}px`).toBe(0);
    expectClean(diagnostics);
  });
}

/**
 * `/jobs` overflows by ~86px, and this test is marked as expected to fail so that the
 * bug is recorded in executable form rather than as a sentence in a document.
 *
 * The cause is the rejections tracker's rows. Each is a flex row of a fixed `w-10`
 * count, a `flex-1 min-w-0` bar, and a label reading "67% of rejections" that carries
 * neither `shrink-0` nor a wrapping allowance — so the label holds its ~100px intrinsic
 * width, the row cannot compress below the sum, and the whole page inherits the
 * overflow. It is a layout fix in `apps/web/src/components/jobs/`, not a test fix, and
 * it is left alone here deliberately: this commit is the gate, not a redesign.
 *
 * **When somebody fixes it, this test starts passing and Playwright fails the run for
 * it** — "expected to fail but passed" — which is the prompt to delete these lines and
 * move `/jobs` into ROUTES above.
 */
test.fail(
  "/jobs does not scroll sideways on a phone — KNOWN FAILURE, the rejections tracker",
  async ({ page }) => {
    await page.goto("/jobs");
    const overflow = await horizontalOverflow(page);
    expect(overflow, `/jobs overflows its viewport by ${overflow}px`).toBe(0);
  },
);
