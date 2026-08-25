import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, idempotencyKey } from "./api";

/**
 * The fetch layer every page depends on.
 *
 * Three rules live here rather than at the call sites, so they are tested here: the
 * cookie travels on every request, a 401 sends the browser to `/login` instead of
 * rendering an error, and failures branch on the RFC 9457 `type` slug rather than prose.
 */

const replace = vi.fn();

beforeEach(() => {
  replace.mockClear();
  vi.stubGlobal("window", {
    location: { replace, pathname: "/" },
  });
});

afterEach(() => vi.unstubAllGlobals());

function answer(body: unknown, status = 200, contentType = "application/json") {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(status === 204 ? null : JSON.stringify(body), {
          status,
          headers: { "Content-Type": contentType },
        }),
    ),
  );
}

function lastInit(): RequestInit {
  const mock = globalThis.fetch as unknown as { mock: { calls: unknown[][] } };
  return mock.mock.calls.at(-1)![1] as RequestInit;
}

describe("request", () => {
  it("sends the cookie on every request", async () => {
    answer({ measured: 0, calibrating: 0, concepts: [] });
    await api.mastery();
    expect(lastInit().credentials).toBe("include");
  });

  it("prefixes /api/v1 for API paths and leaves /auth alone", async () => {
    answer({ authenticated: true, user_id: "u", github_id: 1 });
    await api.me();
    const mock = globalThis.fetch as unknown as { mock: { calls: unknown[][] } };
    expect(mock.mock.calls.at(-1)![0]).toBe("/auth/me");

    answer({ concepts: [], measured: 0, calibrating: 0 });
    await api.mastery();
    expect((globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.at(-1)![0]).toBe(
      "/api/v1/mastery",
    );
  });

  it("only sets a Content-Type when there is a body", async () => {
    answer({ concepts: [], measured: 0, calibrating: 0 });
    await api.mastery();
    expect((lastInit().headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("sends the idempotency key it is given", async () => {
    answer({ id: "s1", state: "briefing", plan: {} });
    await api.createSession({ mode: "coding", budget_minutes: 45 }, "key-1");
    expect((lastInit().headers as Record<string, string>)["Idempotency-Key"]).toBe("key-1");
  });

  it("mints a distinct key each time", () => {
    expect(idempotencyKey()).not.toBe(idempotencyKey());
  });
});

describe("failures", () => {
  it("sends the browser to /login on a 401 rather than rendering an error", async () => {
    // There is no useful message for an expired cookie, and both causes are fixed by
    // logging in.
    answer({}, 401);
    await expect(api.mastery()).rejects.toBeInstanceOf(ApiError);
    expect(replace).toHaveBeenCalledWith("/login");
  });

  it("does not bounce off /login onto itself", async () => {
    vi.stubGlobal("window", { location: { replace, pathname: "/login" } });
    answer({}, 401);
    await expect(api.me()).rejects.toBeInstanceOf(ApiError);
    expect(replace).not.toHaveBeenCalled();
  });

  it("branches on the type slug, never on the title", async () => {
    answer(
      {
        type: "https://interview-helper.local/errors/budget-exceeded",
        title: "Session token budget exceeded",
        status: 429,
        detail: "Session consumed 400k of 400k tokens.",
      },
      429,
    );

    const error = await api.mastery().catch((e: unknown) => e as ApiError);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).slug).toBe("budget-exceeded");
    expect((error as ApiError).isBudgetExceeded).toBe(true);
    expect((error as ApiError).message).toContain("400k");
  });

  it("recognises a missing-configuration 503 as not a login problem", async () => {
    answer(
      { type: "https://interview-helper.local/errors/not-configured", title: "x", status: 503 },
      503,
    );
    const error = (await api.mastery().catch((e) => e)) as ApiError;
    expect(error.isNotConfigured).toBe(true);
  });

  it("treats a 409 as wrong state", async () => {
    answer({ type: "x/wrong-state", title: "Wrong session state", status: 409 }, 409);
    const error = (await api.report("s1").catch((e) => e)) as ApiError;
    expect(error.isWrongState).toBe(true);
  });

  it("survives a failure that is not a problem document", async () => {
    // A proxy or a crash can answer with HTML. A JSON parse failure must not become the
    // error the user sees instead of the status that caused it.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>502 Bad Gateway</html>", { status: 502 })),
    );

    const error = (await api.mastery().catch((e) => e)) as ApiError;
    expect(error.status).toBe(502);
    expect(error.slug).toBe("http-502");
    expect(error.problem).toBeNull();
  });

  it("returns nothing for a 204 rather than trying to parse it", async () => {
    answer(null, 204);
    await expect(api.logout()).resolves.toBeUndefined();
  });
});

describe("query building", () => {
  it("puts filters on the wire the server actually reads", async () => {
    answer({ problems: [], next_cursor: null });
    await api.listProblems({ status: "pending_classification", conceptId: "trie" });

    const url = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.at(-1)![0] as string;
    expect(url).toContain("status=pending_classification");
    expect(url).toContain("concept_id=trie");
    expect(url).toContain("limit=50");
  });

  it("omits the session id from the budget route when there is none", async () => {
    answer({ session: {}, day: {} });
    await api.budget();
    const url = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.at(-1)![0] as string;
    expect(url).toBe("/api/v1/costs/budget");
  });
});
