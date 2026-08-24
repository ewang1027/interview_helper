import { afterEach, describe, expect, it, vi } from "vitest";
import { probeAuth } from "./auth-state";
import { api } from "./api";

/**
 * The three states `/login` has to tell apart.
 *
 * The one that matters is `not-configured`: without it the app sends an
 * unauthenticated browser to `/auth/login`, which answers `503` when OAuth is
 * unset, and the user is left looking at raw problem+json with no way forward.
 */
afterEach(() => vi.restoreAllMocks());

describe("probeAuth", () => {
  it("reports a live session without asking whether sign-in is possible", async () => {
    const me = vi.spyOn(api, "me").mockResolvedValue({
      authenticated: true,
      user_id: "u1",
      github_id: 1,
    });
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    expect(await probeAuth()).toBe("signed-in");
    expect(me).toHaveBeenCalled();
    // No point probing the login route when we are already in.
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("reports not-configured when the login route refuses with a 503", async () => {
    vi.spyOn(api, "me").mockRejectedValue(new Error("401"));
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("{}", { status: 503 }) as Response,
    );

    expect(await probeAuth()).toBe("not-configured");
  });

  it("reads an opaque redirect as a working GitHub flow", async () => {
    // A configured server answers a 3xx toward github.com. Under
    // `redirect: "manual"` that arrives as an opaque response with status 0,
    // not as a cross-origin fetch that throws.
    vi.spyOn(api, "me").mockRejectedValue(new Error("401"));
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      type: "opaqueredirect",
      status: 0,
      ok: false,
    } as Response);

    expect(await probeAuth()).toBe("ready");
  });

  it("does not claim not-configured when the network simply failed", async () => {
    // Guessing here would tell someone their OAuth app is broken when their
    // API is merely down.
    vi.spyOn(api, "me").mockRejectedValue(new Error("401"));
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("failed to fetch"));

    expect(await probeAuth()).toBe("unknown");
  });
});
