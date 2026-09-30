import { expect, expectClean, test } from "./fixtures";

/**
 * Every route at a phone width, and at the two widths between a phone and a desktop.
 *
 * docs/WEB.md named "a collision, an overflow" as the kind of fault the component tests
 * cannot see, and the 2026-09-22 browser gate ran at one desktop viewport only, so it
 * could not see them either. The first run of this found a real one on `/jobs` — 86px,
 * traced to `CardHeader`'s action slot and fixed on 2026-09-24.
 *
 * Every route is asserted, not just the one that broke, and that is what caught the
 * first attempted fix: making the action slot shrinkable cleared `/jobs` and overflowed
 * `/concepts` by 111px instead. A gate that watched only the page with the known bug
 * would have called that a success.
 *
 * **Tablet and small laptop since 2026-09-29.** Until then only 390px and the desktop
 * default were measured, and the band between them is where Tailwind's `md` (768px) and
 * `lg` (1024px) breakpoints switch layouts on — a two-column grid or an inline header
 * that fits at 1280 can still be too wide just past the point it switches on. 768 and
 * 1024 are those two breakpoints exactly, the narrowest width each wider layout has to
 * fit.
 *
 * The assertion is that the **page** does not scroll sideways. A deliberately scrollable
 * element inside the page is fine and several exist — the nav is `overflow-x-auto` by
 * design, and so is the corpus table — which is why this measures the document rather
 * than hunting for wide descendants.
 */

// 390x844 is an iPhone 14/15 at its CSS width, the narrowest thing worth designing for.
// 768x1024 is an iPad in portrait, and Tailwind's `md`; 1024x768 is the same tablet in
// landscape or a small laptop, and Tailwind's `lg`.
const VIEWPORTS = [
  { name: "a phone", width: 390, height: 844 },
  { name: "a tablet", width: 768, height: 1024 },
  { name: "a small laptop", width: 1024, height: 768 },
] as const;

const ROUTES = [
  "/",
  "/session/new",
  "/jobs",
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

for (const viewport of VIEWPORTS) {
  test.describe(`${viewport.width}px`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    for (const route of ROUTES) {
      test(`${route} does not scroll sideways on ${viewport.name}`, async ({
        page,
        diagnostics,
      }) => {
        await page.goto(route);
        const overflow = await horizontalOverflow(page);
        expect(
          overflow,
          `${route} overflows a ${viewport.width}px viewport by ${overflow}px`,
        ).toBe(0);
        expectClean(diagnostics);
      });
    }
  });
}
