import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import History from "./page";
import { api } from "@/lib/api";
import { keys } from "@/lib/queries";
import { stubFetch } from "@/test/harness";

vi.mock("next/navigation", () => ({ usePathname: () => "/history" }));

/**
 * History, and the cache it shares with the dashboard.
 *
 * The first test is the regression this page existed without for a month: the
 * dashboard and History both read `GET /sessions`, and until 2026-09-21 both
 * keyed it `["sessions", cursor]` — ignoring `limit`, which differs between
 * them. Navigating from one to the other inside `staleTime` therefore found a
 * fresh entry, skipped the fetch, and left History's accumulator empty while
 * its empty state rendered over a cache holding every row.
 *
 * It is driven through a *shared* client at the production `staleTime`, not
 * `renderPage`'s per-render one, because a per-render client cannot express the
 * bug: the collision only exists between two pages of the same tab.
 */
afterEach(() => vi.unstubAllGlobals());

const page = (count: number, cursor: string | null, from = 0) => ({
  sessions: Array.from({ length: count }, (_, n) => n + from).map((i) => ({
    id: `01M0MWM8SAK93RS18Y8KMAR9G${String(i).padStart(2, "0")}`,
    mode: i % 2 === 0 ? "coding" : "quant",
    state: "complete",
    started_at: "2026-08-22T14:05:08Z",
    ended_at: "2026-08-22T14:45:00Z",
  })),
  next_cursor: cursor,
});

/** Exactly the defaults src/app/providers.tsx sets for the real app. */
const tabClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { staleTime: 15_000, refetchOnWindowFocus: false, retry: false },
    },
  });

const renderWith = (client: QueryClient) =>
  render(
    <QueryClientProvider client={client}>
      <History />
    </QueryClientProvider>,
  );

describe("history", () => {
  it("renders its rows when the dashboard has already filled the sessions cache", async () => {
    stubFetch({ "/sessions": page(20, null) });
    const client = tabClient();

    // What the dashboard's useSessions() does, with its own default limit of 20.
    await client.fetchQuery({
      queryKey: keys.sessions(undefined),
      queryFn: () => api.listSessions({}),
    });

    renderWith(client);

    expect(await screen.findByText(/20 sessions loaded/)).toBeInTheDocument();
    expect(screen.queryByText("No sessions yet")).not.toBeInTheDocument();
  });

  it("keeps the pages it has already loaded across a remount", async () => {
    stubFetch({
      "/sessions": (url: string) =>
        url.includes("cursor=") ? page(5, null, 25) : page(25, "01M0MWM8SAK93RS18Y8KMAR9G24"),
    });
    const client = tabClient();

    const first = renderWith(client);
    expect(await screen.findByText(/25 sessions loaded/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText(/30 sessions loaded/)).toBeInTheDocument();

    // Navigate away and back. The second page used to live in component state,
    // so it went with the unmount and the user re-paged from scratch.
    first.unmount();
    renderWith(client);

    expect(await screen.findByText(/30 sessions loaded/)).toBeInTheDocument();
  });

  it("filters by mode over everything fetched, not just the newest page", async () => {
    stubFetch({ "/sessions": page(20, null) });
    const client = tabClient();
    renderWith(client);

    await screen.findByText(/20 sessions loaded/);
    await userEvent.click(screen.getByRole("button", { name: "quant" }));

    await waitFor(() => expect(screen.getByText(/10 in quant/)).toBeInTheDocument());
  });

  it("says so when there is genuinely nothing", async () => {
    stubFetch({ "/sessions": page(0, null) });
    renderWith(tabClient());

    expect(await screen.findByText("No sessions yet")).toBeInTheDocument();
  });
});
