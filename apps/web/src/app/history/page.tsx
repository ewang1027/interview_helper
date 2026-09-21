"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import { ApiErrorNotice } from "@/components/api-error";
import { Badge, Button, Card, CardBody, Empty, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { when } from "@/lib/format";
import { keys } from "@/lib/queries";
import { MODES, REPORTABLE, type Mode, type SessionSummary } from "@/lib/types";

const PAGE_SIZE = 25;

/**
 * Session history.
 *
 * Paged by cursor, and the pages are *accumulated* rather than replaced: the
 * API's cursor describes where the scan reached, so a filtered page can come
 * back short or empty with a cursor to continue from. Filtering happens here,
 * over everything fetched, which is why "load more" and the mode filter are
 * independent of each other.
 *
 * **The accumulator is `useInfiniteQuery`'s, not this component's**, and the
 * correction is worth keeping because the bug it fixes was invisible. Until
 * 2026-09-21 the pages were collected into `useState` from inside a `queryFn`
 * keyed `["sessions", cursor]` — a key the dashboard also used, with a
 * different `limit`. Arriving here from the dashboard inside the 15s
 * `staleTime` found that entry fresh, so the `queryFn` never ran, the
 * accumulator never filled, and `isLoading` was already false: the page
 * rendered "No sessions yet" over a cache holding twenty of them, with a
 * working "Load more" underneath. Keeping the pages in the query cache fixes
 * the collision's other half too — navigating away and back used to discard
 * every page past the first.
 */
export default function History() {
  const [mode, setMode] = useState<Mode | undefined>(undefined);

  const query = useInfiniteQuery({
    queryKey: keys.sessionPages(PAGE_SIZE),
    queryFn: ({ pageParam }) => api.listSessions({ cursor: pageParam, limit: PAGE_SIZE }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  // Deduplicated across pages: a cursor describes where the scan reached, not a
  // disjoint slice, so an id arriving twice is the API behaving as documented.
  const pages = useMemo(() => {
    const seen = new Set<string>();
    const rows: SessionSummary[] = [];
    for (const page of query.data?.pages ?? []) {
      for (const row of page.sessions) {
        if (!seen.has(row.id)) {
          seen.add(row.id);
          rows.push(row);
        }
      }
    }
    return rows;
  }, [query.data]);

  const rows = mode ? pages.filter((row) => row.mode === mode) : pages;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-ink text-xl font-semibold tracking-tight">History</h1>
          <p className="text-ink-muted mt-0.5 text-sm">
            {pages.length} session{pages.length === 1 ? "" : "s"} loaded
            {mode ? ` · ${rows.length} in ${mode}` : ""}
          </p>
        </div>
        <div className="flex gap-1">
          {[undefined, ...MODES].map((option) => (
            <button
              key={option ?? "all"}
              type="button"
              onClick={() => setMode(option)}
              aria-pressed={mode === option}
              className={cn(
                "rounded px-2 py-1 text-xs transition-colors",
                mode === option ? "bg-accent text-accent-ink" : "text-ink-secondary hover:bg-sunken",
              )}
            >
              {option ?? "All"}
            </button>
          ))}
        </div>
      </div>

      {query.error ? <ApiErrorNotice error={query.error} /> : null}

      <Card>
        <CardBody className="pt-4">
          {query.isLoading && pages.length === 0 ? (
            <Skeleton className="h-48" />
          ) : rows.length === 0 ? (
            <Empty title={mode ? `No ${mode} sessions loaded` : "No sessions yet"} />
          ) : (
            <ul className="divide-hairline divide-y">
              {rows.map((session) => {
                const reportable = REPORTABLE.includes(session.state);
                return (
                  <li key={session.id} className="flex flex-wrap items-baseline gap-3 py-2">
                    <Link
                      href={`/session/${session.id}`}
                      className="text-ink font-mono text-xs hover:underline"
                    >
                      {session.id.slice(-8)}
                    </Link>
                    <span className="text-ink-secondary text-sm">{session.mode}</span>
                    <Badge
                      tone={
                        session.state === "complete"
                          ? "good"
                          : session.state === "failed"
                            ? "critical"
                            : "neutral"
                      }
                    >
                      {session.state}
                    </Badge>
                    <span className="text-ink-muted ml-auto text-xs">
                      {when(session.started_at)}
                    </span>
                    {reportable ? (
                      <Link
                        href={`/session/${session.id}/report`}
                        className="text-ink-secondary text-xs underline underline-offset-2"
                      >
                        report
                      </Link>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </CardBody>
      </Card>

      {query.hasNextPage ? (
        <Button
          variant="secondary"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {query.isFetchingNextPage ? "Loading…" : "Load more"}
        </Button>
      ) : (
        <p className="text-ink-muted text-xs">
          {pages.length > 0 ? "That is everything." : null}
        </p>
      )}
    </div>
  );
}
