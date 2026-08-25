import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Login from "./page";
import { renderPage } from "@/test/harness";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/login",
}));

/**
 * The front door, and the three states it has to tell apart.
 *
 * The one that matters is `not-configured`. Sending an unauthenticated browser straight
 * to `/auth/login` — what docs/WEB.md literally asks for — hands the user raw
 * problem+json when OAuth is unset, with no way forward.
 */
afterEach(() => vi.unstubAllGlobals());

function stub(handlers: { me: Response | (() => Response); login: Response | (() => Response) }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const pick = url.includes("/auth/me") ? handlers.me : handlers.login;
      return typeof pick === "function" ? pick() : pick;
    }),
  );
}

const UNAUTHENTICATED = () => new Response(JSON.stringify({ type: "x/unauthorized" }), { status: 401 });

describe("login", () => {
  it("explains an unconfigured deployment instead of showing a dead button", async () => {
    stub({ me: UNAUTHENTICATED, login: () => new Response("{}", { status: 503 }) });
    renderPage(<Login />);

    expect(await screen.findByText("not configured")).toBeInTheDocument();
    expect(await screen.findByText(/GITHUB_CLIENT_ID/)).toBeInTheDocument();
    // And says what to do instead, which is the whole point.
    expect(await screen.findByText("make login")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Sign in with GitHub/ })).not.toBeInTheDocument();
  });

  it("offers GitHub when the flow would actually work", async () => {
    // A configured server answers a 3xx toward github.com, which arrives here as an
    // opaque response rather than a cross-origin fetch that throws.
    stub({
      me: UNAUTHENTICATED,
      login: () => ({ type: "opaqueredirect", status: 0, ok: false }) as unknown as Response,
    });
    renderPage(<Login />);

    expect(await screen.findByRole("button", { name: /Sign in with GitHub/ })).toBeInTheDocument();
    expect(screen.queryByText("not configured")).not.toBeInTheDocument();
  });

  it("sends an already-signed-in visitor back where they came from", async () => {
    stub({
      me: () =>
        new Response(JSON.stringify({ authenticated: true, user_id: "u1", github_id: 1 }), {
          status: 200,
        }),
      login: () => new Response("{}", { status: 503 }),
    });
    renderPage(<Login />);

    expect(await screen.findByText(/Already signed in/)).toBeInTheDocument();
    expect(replace).toHaveBeenCalledWith("/");
  });

  it("does not blame the OAuth app when the network is what failed", async () => {
    // Telling somebody their OAuth app is broken when their API is merely down is a
    // worse error than saying nothing.
    stub({
      me: UNAUTHENTICATED,
      login: () => {
        throw new TypeError("failed to fetch");
      },
    });
    renderPage(<Login />);

    expect(await screen.findByRole("button", { name: /Sign in with GitHub/ })).toBeInTheDocument();
    expect(screen.queryByText("not configured")).not.toBeInTheDocument();
  });
});
