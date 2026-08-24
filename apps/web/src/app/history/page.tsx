"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { ApiErrorNotice } from "@/components/api-error";
import { Badge, Button, Card, CardBody, Empty, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { when } from "@/lib/format";
import { keys } from "@/lib/queries";
import { MODES, REPORTABLE, type Mode, type SessionSummary } from "@/lib/types";

/**
 * Session history.
 *
 * Paged by cursor, and the pages are *accumulated* rather than replaced: the
 * API's cursor describes where the scan reached, so a filtered page can come
 * back short or empty with a cursor to continue from. Filtering happens here,
 * over everything fetched, which is why "load more" and the mode filter are
 * independent of each other.
 */
export default function History() {
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [pages, setPages] = useState<SessionSummary[]>([]);
  const [mode, setMode] = useState<Mode | undefined>(undefined);

  const query = useQuery({
    queryKey: keys.sessions(cursor),
    queryFn: async () => {
      const page = await api.listSessions({ cursor, limit: 25 });
      setPages((current) => {
        const seen = new Set(current.map((row) => row.id));
        return [...current, ...page.sessions.filter((row) => !seen.has(row.id))];
      });
      return page;
    },
  });

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

      {query.data?.next_cursor ? (
        <Button
          variant="secondary"
          disabled={query.isFetching}
          onClick={() => setCursor(query.data!.next_cursor!)}
        >
          {query.isFetching ? "Loading…" : "Load more"}
        </Button>
      ) : (
        <p className="text-ink-muted text-xs">
          {pages.length > 0 ? "That is everything." : null}
        </p>
      )}
    </div>
  );
}
