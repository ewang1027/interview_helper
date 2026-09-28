import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./fixtures";

/**
 * The part of "the visual layer is unreviewed" that a machine can check.
 *
 * docs/WEB.md has said since Phase 5 landed that contrast in situ, focus order and
 * keyboard navigation were unproven, and that the component tests "would not catch a
 * collision, an overflow, or a control nothing can reach by keyboard". The browser gate
 * on 2026-09-22 did not close that — it watches requests and text. This does the
 * contrast and structure half; `mobile.spec.ts` does the overflow half.
 *
 * **What this asserts is the set of rule ids per route.** It began, on 2026-09-24, with
 * two known violations named per route so the gate could land green and still fail on
 * anything new. Both were fixed on 2026-09-28 and every route now expects **none**; the
 * `KNOWN` table stays as the place a future, deliberately deferred one would go, and a
 * rule id listed there that stops appearing fails too, so the table cannot outlive its
 * debt.
 *
 * **Both colour schemes.** Until 2026-09-28 axe ran at the default scheme only, and the
 * dark theme had never been measured. It had three failures, all in the mastery
 * heatmap, which picked its cell ink with a rule written for the light ramp.
 *
 * Node counts are deliberately not asserted: they scale with how much data is in the
 * database, and drifted between two runs of the same page (228 and 227 on `/concepts`).
 */

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

/**
 * Known violations, per route. Empty since 2026-09-28. What was here, and the fix:
 *
 * - `color-contrast` — `--ink-muted: #898781` at 3.4–3.49:1 and white on `--accent`
 *   at 4.41:1. Two token values in `globals.css`, now #6f6d67 and #2670c9.
 * - `nested-interactive` — a `<Link>` inside the weakness list's `<summary>`. The row
 *   is now a link and an `aria-expanded` button side by side.
 */
const KNOWN: Record<string, string[]> = {
  "/": [],
  "/session/new": [],
  "/jobs": [],
  "/practice": [],
  "/concepts": [],
  "/history": [],
  "/corpus": [],
  "/costs": [],
};

for (const scheme of ["light", "dark"] as const) {
  for (const [route, known] of Object.entries(KNOWN)) {
    test(`${route} (${scheme}) has no accessibility violation beyond the known ones`, async ({
      page,
    }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(route);
      await page.waitForLoadState("networkidle");

      const { violations } = await new AxeBuilder({ page }).withTags(WCAG).analyze();
      const found = [...new Set(violations.map((violation) => violation.id))].sort();

      expect(
        found,
        `axe rule ids on ${route} in the ${scheme} scheme. Anything not in the known list ` +
          "is new breakage; if one of the known ones is now absent, take it out of KNOWN " +
          "rather than leaving the gate weaker than the app.\n" +
          violations
            .map((violation) => `  ${violation.id} (${violation.nodes.length}) ${violation.help}`)
            .join("\n"),
      ).toEqual([...known].sort());
    });
  }
}

test("focus is visible on whatever the keyboard reaches first", async ({ page }) => {
  await page.goto("/");

  // Tab off the document and onto the first control. `globals.css` sets a global
  // `:focus-visible` outline; a keyboard Tab is what makes it apply, which is why this
  // cannot be checked by focusing an element programmatically.
  await page.keyboard.press("Tab");

  const focused = await page.evaluate(() => {
    const element = document.activeElement;
    if (!element || element === document.body) return null;
    const style = getComputedStyle(element);
    return {
      tag: element.tagName.toLowerCase(),
      outlineWidth: style.outlineWidth,
      outlineStyle: style.outlineStyle,
    };
  });

  expect(focused, "Tab moved focus nowhere").not.toBeNull();
  expect(focused!.outlineStyle, `${focused!.tag} has no focus outline`).not.toBe("none");
  expect(
    parseFloat(focused!.outlineWidth),
    `${focused!.tag}'s focus outline is ${focused!.outlineWidth}`,
  ).toBeGreaterThan(0);
});

test("every nav link is reachable by keyboard, in the order it is written", async ({ page }) => {
  await page.goto("/");

  // The nav is the one control surface on every page, so a tab order that skips part of
  // it is a fault on all ten routes at once. This walks forward from the document start
  // and records the nav hrefs in the order the keyboard reaches them.
  const expected = await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link")
    .evaluateAll((links) => links.map((link) => link.getAttribute("href") ?? ""));

  const reached: string[] = [];
  for (let press = 0; press < 40 && reached.length < expected.length; press += 1) {
    await page.keyboard.press("Tab");
    const href = await page.evaluate(() => {
      const element = document.activeElement as HTMLElement | null;
      if (!element || !element.closest('nav[aria-label="Main"]')) return null;
      return element.getAttribute("href");
    });
    if (href !== null && !reached.includes(href)) reached.push(href);
  }

  expect(reached, "nav links in keyboard order").toEqual(expected);
});
