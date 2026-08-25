import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import { vi } from "vitest";
import type { ReactElement } from "react";

/**
 * Render a page with a real TanStack Query client and a stubbed `fetch`.
 *
 * Stubbing at `fetch` rather than at `api` is deliberate: it exercises the client in
 * `lib/api.ts` too — the problem+json parsing, the 401 redirect, the `credentials`
 * option — which is where a page's error handling actually lives. A page tested against
 * a stubbed `api` object would pass while every one of those was broken.
 */
export type Routes = Record<string, unknown | ((url: string) => unknown)>;

export interface StubbedFetch {
  calls: string[];
}

/**
 * @param routes  path fragment -> body, matched by `includes` so a query string does
 *                not have to be reproduced exactly. A value may be a function of the
 *                url, or `{ __status }` to answer an error.
 */
export function stubFetch(routes: Routes): StubbedFetch {
  const calls: string[] = [];

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      calls.push(url);

      const key = Object.keys(routes)
        // Longest match wins, so "/corpus/items/x" beats "/corpus/items".
        .sort((a, b) => b.length - a.length)
        .find((candidate) => url.includes(candidate));

      if (key === undefined) {
        return new Response(JSON.stringify({ type: "x/not-found", status: 404 }), {
          status: 404,
          headers: { "Content-Type": "application/problem+json" },
        });
      }

      const value = routes[key];
      const body = typeof value === "function" ? (value as (u: string) => unknown)(url) : value;
      const status =
        body && typeof body === "object" && "__status" in body
          ? (body as { __status: number }).__status
          : 200;

      return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );

  return { calls };
}

export function renderPage(ui: ReactElement): RenderResult {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

/** Fixtures shaped exactly as the API returns them — checked against live responses. */
export const fixtures = {
  mastery: {
    concepts: [
      {
        concept_id: "sliding-window",
        ability: 1501.14,
        normalized_ability: 0.4096,
        observations: 5,
        calibrating: false,
        stability_days: 0.02,
        due_at: new Date(Date.now() - 86_400_000).toISOString(),
        last_seen: new Date(Date.now() - 86_400_000).toISOString(),
      },
    ],
    measured: 1,
    calibrating: 0,
  },
  concepts: {
    concepts: [
      {
        id: "sliding-window",
        name: "Sliding window",
        domain: "coding",
        description: "Maintain a contiguous window…",
        band: "core",
        tags: [],
        prereqs: [],
        unlocks: [],
        servable: true,
        measured_by_some_item: true,
      },
      {
        id: "conditional-probability",
        name: "Conditional probability",
        domain: "quant",
        description: "Bayes and friends",
        band: "core",
        tags: [],
        prereqs: [],
        unlocks: [],
        servable: false,
        measured_by_some_item: false,
      },
    ],
    total: 2,
    servable: 1,
  },
  corpusStatus: {
    concepts: 159,
    concepts_by_domain: { coding: 52, quant: 51 },
    items: 48,
    archetypes: 16,
    instances: 32,
  },
  costs: {
    since: "2026-08-18T00:00:00+00:00",
    calls: 29,
    cost_usd: 0.0696,
    input_tokens: 14500,
    output_tokens: 1740,
    cache_read_tokens: 0,
    cache_write_tokens: 0,
    by_job: [{ job: "grading", calls: 6, cost_usd: 0.0144 }],
    by_model: [{ model: "us.anthropic.claude-sonnet-4-6", calls: 29, cost_usd: 0.0696 }],
  },
  emptyQueue: { as_of: "2026-08-25T00:00:00Z", due: [] },
  sessions: {
    sessions: [
      {
        id: "01M0MWM8SAK93RS18Y8KMAR9GD",
        mode: "coding",
        state: "complete",
        started_at: "2026-08-22T14:05:08Z",
        ended_at: "2026-08-22T14:45:00Z",
      },
    ],
    next_cursor: null,
  },
  weaknesses: {
    mode: null,
    weights: {
      weakness: 0.35,
      recent_errors: 0.25,
      overdue: 0.2,
      unlocks: 0.1,
      recent_exposure: 0.2,
    },
    concepts: [
      {
        concept_id: "big-o-analysis",
        name: "Asymptotic complexity analysis",
        domain: "coding",
        priority: 0.2989,
        ability: 1550,
        observations: 0,
        calibrating: true,
        unseen: true,
        terms: {
          weakness: 0.1989,
          recent_errors: 0,
          overdue: 0,
          unlocks: 0.1,
          recent_exposure: -0,
        },
      },
    ],
  },
};
