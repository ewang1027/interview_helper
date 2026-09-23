import { test as base, expect, type Page } from "@playwright/test";

/**
 * What a page did while it was open, as opposed to what it looks like.
 *
 * The component tests already assert structure and class names. The thing they cannot
 * see — and the reason this gate exists — is whether the page's real requests
 * succeeded, whether anything threw, and whether it stayed on the route it was sent
 * to. A page renders its `<h1>` from the server shell whether or not every query
 * beneath it failed, so a heading alone is a gate that cannot fail.
 */
export interface Diagnostics {
  consoleErrors: string[];
  pageErrors: string[];
  failedRequests: { path: string; status: number }[];
}

/**
 * Console noise that is not this app's doing and not worth failing a build over.
 *
 * Kept as an explicit allowlist rather than a severity filter: every entry here is a
 * message somebody has to justify, which is the property that stops it growing into
 * "ignore all errors". Nothing app-shaped belongs in it.
 */
const BENIGN_CONSOLE = [
  /favicon\.ico/i,
  // Next's dev overlay and React's hydration notes only appear on a dev server; the
  // gate runs against `next start`, so these are here for the E2E_BASE_URL case.
  /Download the React DevTools/i,
];

function isBenign(text: string): boolean {
  return BENIGN_CONSOLE.some((pattern) => pattern.test(text));
}

export const test = base.extend<{ diagnostics: Diagnostics }>({
  diagnostics: async ({ page }, use) => {
    const diagnostics: Diagnostics = {
      consoleErrors: [],
      pageErrors: [],
      failedRequests: [],
    };

    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const text = message.text();
      if (!isBenign(text)) diagnostics.consoleErrors.push(text);
    });

    page.on("pageerror", (error) => {
      diagnostics.pageErrors.push(`${error.name}: ${error.message}`);
    });

    page.on("response", (response) => {
      const url = new URL(response.url());
      const ours = url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/");
      if (!ours) return;
      if (response.status() >= 400) {
        diagnostics.failedRequests.push({
          path: url.pathname + url.search,
          status: response.status(),
        });
      }
    });

    await use(diagnostics);
  },
});

export { expect };

/**
 * Assert the page did its job quietly.
 *
 * All three are checked before any is reported, so a run tells you everything that
 * went wrong on a page rather than the first thing.
 */
export function expectClean(diagnostics: Diagnostics): void {
  expect(diagnostics.failedRequests, "API requests that failed").toEqual([]);
  expect(diagnostics.pageErrors, "uncaught exceptions").toEqual([]);
  expect(diagnostics.consoleErrors, "console errors").toEqual([]);
}

/**
 * A 401 sends the browser to `/auth/login` rather than rendering an error
 * (docs/WEB.md), which makes "did we stay put" a direct test of the session cookie.
 */
export async function expectStillAuthenticated(page: Page, route: string): Promise<void> {
  const path = new URL(page.url()).pathname;
  expect(
    path,
    `left ${route} for ${path} — a 401 redirects to /auth/login, so this is the ` +
      "session cookie, not the page",
  ).not.toMatch(/^\/auth\/login/);
}
