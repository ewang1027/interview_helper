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
 * **What this asserts is the set of rule ids, not a clean bill of health.** The app has
 * two real, known violations, both traced to a single cause each (see below), and both
 * are design decisions rather than bugs to fix inside a test commit. A gate that failed
 * on them would be red from the day it landed, which this repo has already learned is a
 * gate people route around. So the known ids are named per route, and **anything new
 * fails** — including these two spreading to a route not listed here, which is the
 * signal that a11y debt is growing.
 *
 * Node counts are deliberately not asserted: they scale with how much data is in the
 * database, and drifted between two runs of the same page (228 and 227 on `/concepts`).
 * The counts as measured on 2026-09-24 are recorded in docs/WEB.md instead.
 */

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

/**
 * Known violations, per route, as of 2026-09-24.
 *
 * - `color-contrast` — one token. `--ink-muted: #898781` sits at 3.4–3.49:1 on the page
 *   and surface backgrounds where AA wants 4.5:1, and it is the colour of every caption,
 *   stat note and hint in the app. `--accent` with white ink is 4.41:1, also just under.
 *   Two token values, hundreds of nodes.
 * - `nested-interactive` — the weakness list's `<summary>` contains a `<Link>`. A
 *   `summary` has an implicit button role, so the link is a focusable descendant of a
 *   control; the `stopPropagation` already on it says the nesting was known to be
 *   awkward.
 */
const KNOWN: Record<string, string[]> = {
  "/": ["color-contrast", "nested-interactive"],
  "/session/new": ["color-contrast"],
  "/jobs": ["color-contrast"],
  "/practice": ["color-contrast"],
  "/concepts": ["color-contrast", "nested-interactive"],
  "/history": ["color-contrast"],
  "/corpus": ["color-contrast"],
  "/costs": ["color-contrast"],
};

for (const [route, known] of Object.entries(KNOWN)) {
  test(`${route} has no accessibility violation beyond the known ones`, async ({ page }) => {
    await page.goto(route);
    await page.waitForLoadState("networkidle");

    const { violations } = await new AxeBuilder({ page }).withTags(WCAG).analyze();
    const found = [...new Set(violations.map((violation) => violation.id))].sort();

    expect(
      found,
      `axe rule ids on ${route}. Anything not in the known list is new breakage; ` +
        "if one of the known ones is now absent, take it out of KNOWN rather than " +
        "leaving the gate weaker than the app.\n" +
        violations
          .map((violation) => `  ${violation.id} (${violation.nodes.length}) ${violation.help}`)
          .join("\n"),
    ).toEqual([...known].sort());
  });
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
