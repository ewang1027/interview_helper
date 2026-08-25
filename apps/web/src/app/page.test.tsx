import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Dashboard from "./page";
import { fixtures, renderPage, stubFetch } from "@/test/harness";

vi.mock("next/navigation", () => ({ usePathname: () => "/", useRouter: () => ({ push: vi.fn() }) }));



const ROUTES = {
  "/api/v1/mastery/weaknesses": fixtures.weaknesses,
  "/api/v1/mastery": fixtures.mastery,
  "/api/v1/concepts": fixtures.concepts,
  "/api/v1/corpus/status": fixtures.corpusStatus,
  "/api/v1/costs": fixtures.costs,
  "/api/v1/practice/review-queue": fixtures.emptyQueue,
  "/api/v1/sessions": fixtures.sessions,
};

beforeEach(() => stubFetch(ROUTES));
afterEach(() => vi.unstubAllGlobals());

describe("dashboard", () => {
  it("reports what it measured against the size of the taxonomy", async () => {
    // "1 concept measured" reads very differently once you know there are 159, which is
    // why the API returns `measured` alongside the rows at all.
    renderPage(<Dashboard />);

    expect(await screen.findByText("Concepts measured")).toBeInTheDocument();
    expect(await screen.findByText("of 159 in the taxonomy")).toBeInTheDocument();
  });

  it("draws the whole taxonomy, not only the measured part", async () => {
    renderPage(<Dashboard />);
    // Both concepts render as cells; only one has a mastery row behind it.
    expect(await screen.findByText(/1 of 2 concepts measured/)).toBeInTheDocument();
  });

  it("asks the concepts endpoint once rather than one ranking per mode", async () => {
    // This used to be four requests for static build-time content.
    const stub = stubFetch(ROUTES);
    renderPage(<Dashboard />);

    await screen.findByText("Concepts measured");
    await waitFor(() =>
      expect(stub.calls.filter((url) => url.includes("/api/v1/concepts"))).toHaveLength(1),
    );
  });

  it("sends the session cookie on every request", async () => {
    // `credentials: "include"` is what makes the whole app work behind the proxy, and
    // omitting it fails as a 401 rather than as anything obviously wrong.
    stubFetch(ROUTES);
    renderPage(<Dashboard />);

    await screen.findByText("Concepts measured");
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    for (const [, init] of calls) {
      expect((init as RequestInit).credentials).toBe("include");
    }
  });

  it("says the queue is empty rather than showing nothing", async () => {
    renderPage(<Dashboard />);
    expect(await screen.findByText("Nothing due")).toBeInTheDocument();
  });

  it("survives an endpoint that fails without taking the page with it", async () => {
    // One failing panel must not blank the dashboard: the others are independent
    // queries and their data is still worth showing.
    stubFetch({ ...ROUTES, "/api/v1/costs": { __status: 503, type: "x/dependency-unavailable" } });
    renderPage(<Dashboard />);

    expect(await screen.findByText("Concepts measured")).toBeInTheDocument();
  });
});
