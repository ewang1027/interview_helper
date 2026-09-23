import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { expect, test as setup } from "@playwright/test";
import { STORAGE_STATE } from "../playwright.config";

/**
 * Get a real session cookie into a real browser, the documented way.
 *
 * `api.auth` has no local-login route on purpose — a route that issues a session
 * without GitHub exists in production too, whatever flag guards it — so the cookie is
 * minted *outside* the server by whoever holds `SESSION_SECRET`, which is exactly what
 * `make login` does. This shells out to the same module rather than reimplementing the
 * signature, because a test that signs its own cookies stops testing the verifier.
 *
 * The cookie is `HttpOnly`, so nothing in the page can set it; it is installed on a
 * browser context instead, with the attributes the server would have set. `secure`
 * follows the base URL's scheme — the stack runs on plain http on localhost and `.env`
 * sets `COOKIE_SECURE=false` to match, but a cookie marked secure would simply not be
 * sent there, which is a silent failure worth not hard-coding.
 */

const REPO_ROOT = resolve(__dirname, "../../..");
const COOKIE_NAME = "ih_session";

setup("mint a session cookie and confirm the stack is live", async ({ browser, request, baseURL }) => {
  const origin = new URL(baseURL!);

  // Preflight, so a stack that is not running says so once instead of failing as a
  // dozen unrelated navigation timeouts.
  let health;
  try {
    health = await request.get("/health");
  } catch (cause) {
    throw new Error(
      `No stack answering at ${origin.origin}. Start one with \`make up-stack\` ` +
        `(or point E2E_BASE_URL at another).\n${String(cause)}`,
    );
  }
  expect(
    health.ok(),
    `GET /health returned ${health.status()} — the stack at ${origin.origin} is not healthy`,
  ).toBeTruthy();

  let token: string;
  try {
    token = execFileSync("uv", ["run", "python", "-m", "api.mint_session", "--raw"], {
      cwd: REPO_ROOT,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  } catch (cause) {
    throw new Error(
      "Could not mint a session cookie. `python -m api.mint_session` needs " +
        "SESSION_SECRET in .env and a database holding a users row — the same two " +
        `things \`make login\` needs.\n${String(cause)}`,
    );
  }
  expect(token, "mint_session printed nothing").not.toEqual("");

  // Prove the cookie authenticates before writing it out. A storage state holding a
  // cookie the server rejects would send every test to /auth/login and report a dozen
  // missing headings rather than one bad cookie.
  const probe = await request.get("/api/v1/mastery", {
    headers: { Cookie: `${COOKIE_NAME}=${token}` },
  });
  expect(
    probe.status(),
    `the minted cookie did not authenticate (GET /api/v1/mastery -> ${probe.status()}). ` +
      "The most likely cause is an API container built against a different " +
      "SESSION_SECRET than the one .env holds now.",
  ).toBe(200);

  const context = await browser.newContext();
  await context.addCookies([
    {
      name: COOKIE_NAME,
      value: token,
      domain: origin.hostname,
      path: "/",
      httpOnly: true,
      secure: origin.protocol === "https:",
      sameSite: "Lax",
      expires: -1,
    },
  ]);

  mkdirSync(dirname(STORAGE_STATE), { recursive: true });
  await context.storageState({ path: STORAGE_STATE });
  await context.close();
});
