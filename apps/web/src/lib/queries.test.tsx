import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useTaxonomy } from "./queries";
import { fixtures, stubFetch } from "@/test/harness";

/**
 * The taxonomy is build-time content, and the cache has to say that twice.
 *
 * `staleTime: Infinity` only means "do not refetch while something is watching
 * it". `gcTime` decides how long the entry survives *after* the last watcher
 * unmounts, and its default is five minutes — so a value that cannot change
 * was being re-fetched on a five-minute cycle, 81 KB at a time, across the
 * three pages that read it.
 */
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function Consumer() {
  const { concepts, isLoading } = useTaxonomy();
  return <span data-testid="count">{isLoading ? "loading" : concepts.length}</span>;
}

const tabClient = () =>
  new QueryClient({
    defaultOptions: { queries: { staleTime: 15_000, refetchOnWindowFocus: false, retry: false } },
  });

const mount = (client: QueryClient) =>
  render(
    <QueryClientProvider client={client}>
      <Consumer />
    </QueryClientProvider>,
  );

describe("useTaxonomy", () => {
  it("is fetched once across a remount an hour later", async () => {
    // Fake timers installed *before* the unmount, because that is when the
    // eviction is scheduled — advancing a clock the timeout was not booked on
    // proves nothing, and an earlier version of this test passed against the
    // bug for exactly that reason.
    vi.useFakeTimers({ shouldAdvanceTime: true });

    const fetched = stubFetch({ "/concepts": fixtures.concepts });
    const concepts = () => fetched.calls.filter((url) => url.includes("/concepts")).length;
    const client = tabClient();

    const first = mount(client);
    expect(await screen.findByText("2")).toBeInTheDocument();
    expect(concepts()).toBe(1);

    first.unmount();

    // Well past the five-minute default that used to evict it.
    await vi.advanceTimersByTimeAsync(60 * 60 * 1000);

    mount(client);

    expect(await screen.findByText("2")).toBeInTheDocument();
    expect(concepts()).toBe(1);
  });
});
