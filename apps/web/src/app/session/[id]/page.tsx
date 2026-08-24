"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiErrorNotice } from "@/components/api-error";
import { Transcript } from "@/components/transcript";
import { Badge, Button, Card, Skeleton } from "@/components/ui/primitives";
import { Workspace, type Draft } from "@/components/workspaces";
import { api, idempotencyKey } from "@/lib/api";
import { cn } from "@/lib/cn";
import { duration, percent } from "@/lib/format";
import { keys } from "@/lib/queries";
import { REPORTABLE, type ItemOutcome } from "@/lib/types";
import { useSessionStream } from "@/lib/use-session-stream";

export default function LiveSession() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [said, setSaid] = useState("");

  const session = useQuery({
    queryKey: keys.session(id),
    queryFn: () => api.session(id),
    // The stream carries state changes; this is the fallback for what it cannot
    // (a page opened after the fact) and for grading results that landed while
    // the tab was closed.
    refetchInterval: (query) =>
      query.state.data && REPORTABLE.includes(query.state.data.state) ? false : 15_000,
  });

  const stream = useSessionStream(id, Boolean(session.data));

  // The stream is authoritative for state while connected, but a session opened
  // cold has no events at all — the bus is in-process and bounded.
  const state = stream.state ?? session.data?.state ?? null;
  const finished = state ? REPORTABLE.includes(state) : false;

  // A grading result on the stream means `GET /sessions/{id}` has moved on too.
  const gradingCount = Object.keys(stream.gradings).length;
  useEffect(() => {
    if (gradingCount) queryClient.invalidateQueries({ queryKey: keys.session(id) });
  }, [gradingCount, id, queryClient]);

  const turn = useMutation({
    mutationFn: (content: string) => api.turn(id, content),
    onMutate: (content) => stream.said(content),
  });

  const submit = useMutation({
    mutationFn: (body: Draft & { item_id: string }) =>
      api.submit(
        id,
        {
          item_id: body.item_id,
          kind: body.kind,
          content: body.content,
          language: body.language,
          elapsed_seconds: session.data?.elapsed_seconds ?? 0,
        },
        idempotencyKey(),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.session(id) }),
  });

  const end = useMutation({
    mutationFn: () => api.endSession(id),
    onSuccess: () => router.push(`/session/${id}/report`),
  });

  const onDraftChange = useCallback((next: Draft) => setDraft(next), []);

  // Which item is in play: the stream says so directly, otherwise the first
  // planned item nothing has been submitted for.
  const currentItem: ItemOutcome | null = useMemo(() => {
    const items = session.data?.items ?? [];
    if (stream.item) {
      return items.find((row) => row.item_id === stream.item!.item_id) ?? null;
    }
    return items.find((row) => row.status === "not_attempted") ?? items[0] ?? null;
  }, [session.data?.items, stream.item]);

  if (session.isLoading) {
    return <Skeleton className="h-96" />;
  }
  if (session.error) {
    return <ApiErrorNotice error={session.error} />;
  }
  if (!session.data) return null;

  const detail = session.data;
  const submitted = currentItem ? currentItem.status !== "not_attempted" : true;

  return (
    <div className="space-y-4">
      {stream.budgetWarning ? (
        // A banner, not a toast: docs/WEB.md — it needs to persist.
        <div className="rounded-md border border-[var(--status-warning)] px-3 py-2">
          <Badge tone="warning">budget</Badge>
          <span className="text-ink ml-2 text-sm">
            {stream.budgetWarning.consumed.toLocaleString()} of{" "}
            {stream.budgetWarning.limit.toLocaleString()} tokens used on this{" "}
            {stream.budgetWarning.scope}. It will be refused, not downgraded.
          </span>
        </div>
      ) : null}

      {stream.error ? (
        <div className="rounded-md border border-[var(--status-critical)] px-3 py-2">
          <Badge tone="critical">{stream.error.code}</Badge>
          <span className="text-ink ml-2 text-sm">{stream.error.message}</span>
        </div>
      ) : null}

      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-ink text-lg font-semibold tracking-tight">
          {detail.mode} session
        </h1>
        <Badge tone={finished ? "good" : "accent"}>{state}</Badge>
        <ConnectionDot connection={stream.connection} finished={finished} />
        <Timer elapsed={detail.elapsed_seconds} budgetMinutes={detail.budget_minutes} />
        <div className="ml-auto flex items-center gap-2">
          {finished ? (
            <Link
              href={`/session/${id}/report`}
              className="bg-accent text-accent-ink inline-flex h-9 items-center rounded-md px-4 text-sm font-medium hover:opacity-90"
            >
              See the report
            </Link>
          ) : (
            <Button variant="secondary" onClick={() => end.mutate()} disabled={end.isPending}>
              {end.isPending ? "Ending…" : "End session"}
            </Button>
          )}
        </div>
      </header>

      <ItemStrip items={detail.items} currentId={currentItem?.item_id ?? null} />

      {submit.error ? <ApiErrorNotice error={submit.error} /> : null}
      {turn.error ? <ApiErrorNotice error={turn.error} /> : null}
      {end.error ? <ApiErrorNotice error={end.error} /> : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card className="flex h-[32rem] flex-col overflow-hidden">
          <div className="border-hairline flex items-center justify-between border-b px-3 py-2">
            <span className="text-ink text-sm font-medium">
              {stream.item?.title ?? currentItem?.title ?? "The problem"}
            </span>
            {currentItem ? <Badge>{currentItem.status.replace("_", " ")}</Badge> : null}
          </div>
          {stream.item?.statement_md ? (
            <div className="border-hairline text-ink-secondary max-h-40 overflow-y-auto border-b p-3 text-sm whitespace-pre-wrap">
              {stream.item.statement_md}
            </div>
          ) : null}
          <div className="min-h-0 flex-1">
            <Transcript
              entries={stream.entries}
              streaming={stream.streaming}
              hints={stream.hints}
              observations={stream.observations}
              gaps={stream.gaps}
            />
          </div>
          <form
            className="border-hairline flex gap-2 border-t p-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (!said.trim() || turn.isPending) return;
              turn.mutate(said.trim());
              setSaid("");
            }}
          >
            <input
              value={said}
              onChange={(event) => setSaid(event.target.value)}
              disabled={finished || turn.isPending}
              placeholder={finished ? "This session has ended." : "Say something…"}
              aria-label="Message the interviewer"
              className="border-hairline bg-surface text-ink min-w-0 flex-1 rounded-md border px-2 py-1.5 text-sm"
            />
            <Button size="sm" disabled={finished || turn.isPending || !said.trim()}>
              {turn.isPending ? "…" : "Send"}
            </Button>
          </form>
        </Card>

        <Card className="flex h-[32rem] flex-col overflow-hidden">
          <div className="min-h-0 flex-1">
            <Workspace mode={detail.mode} onChange={onDraftChange} disabled={finished || submitted} />
          </div>
          <div className="border-hairline flex items-center gap-3 border-t p-2">
            <Button
              size="sm"
              disabled={
                finished ||
                submitted ||
                submit.isPending ||
                !currentItem ||
                !draft?.content.trim()
              }
              onClick={() => currentItem && draft && submit.mutate({ ...draft, item_id: currentItem.item_id })}
            >
              {submit.isPending ? "Submitting…" : "Submit"}
            </Button>
            <span className="text-ink-muted text-xs">
              {submitted
                ? "One submission per item — this one is in."
                : "Grading runs after you submit; results arrive on the stream."}
            </span>
          </div>
        </Card>
      </div>
    </div>
  );
}

function Timer({ elapsed, budgetMinutes }: { elapsed: number; budgetMinutes: number }) {
  // Counts from the server's figure rather than replacing it: the server owns
  // when the session started, this only keeps the display moving between polls.
  const [ticks, setTicks] = useState(0);
  const base = useRef(elapsed);
  base.current = elapsed;

  useEffect(() => {
    setTicks(0);
    const handle = setInterval(() => setTicks((value) => value + 1), 1000);
    return () => clearInterval(handle);
  }, [elapsed]);

  const seconds = base.current + ticks;
  const over = seconds > budgetMinutes * 60;

  return (
    <span
      className={cn("tabular text-sm", over ? "text-[var(--status-critical)]" : "text-ink-muted")}
    >
      {duration(seconds)} of {budgetMinutes}m
    </span>
  );
}

function ConnectionDot({ connection, finished }: { connection: string; finished: boolean }) {
  const label = finished ? "stream closed" : connection;
  const tone =
    connection === "open"
      ? "var(--status-good)"
      : connection === "error"
        ? "var(--status-critical)"
        : "var(--ink-muted)";

  return (
    <span className="text-ink-muted flex items-center gap-1.5 text-xs">
      <span
        aria-hidden
        className="inline-block h-2 w-2 rounded-full"
        style={{ background: finished ? "var(--ink-muted)" : tone }}
      />
      {label}
    </span>
  );
}

function ItemStrip({ items, currentId }: { items: ItemOutcome[]; currentId: string | null }) {
  if (!items.length) return null;

  return (
    <ol className="flex flex-wrap gap-2">
      {items.map((item, index) => (
        <li
          key={item.item_id}
          className={cn(
            "border-hairline flex items-center gap-2 rounded-md border px-2 py-1 text-xs",
            item.item_id === currentId && "border-[var(--accent)]",
          )}
        >
          <span className="tabular text-ink-muted">{index + 1}</span>
          <span className="text-ink-secondary max-w-48 truncate">{item.title ?? item.item_id}</span>
          {item.status === "graded" ? (
            <Badge tone="good">{percent(item.score)}</Badge>
          ) : item.status === "failed" ? (
            <Badge tone="critical">failed</Badge>
          ) : item.status === "grading" ? (
            <Badge tone="warning">grading</Badge>
          ) : (
            <Badge>open</Badge>
          )}
        </li>
      ))}
    </ol>
  );
}
