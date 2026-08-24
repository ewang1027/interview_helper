"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { ApiErrorNotice } from "@/components/api-error";
import { LeetCodeImport } from "@/components/leetcode-import";
import { Badge, Button, Card, CardBody, CardHeader, Empty, Skeleton, Stat } from "@/components/ui/primitives";
import { api, idempotencyKey } from "@/lib/api";
import { cn } from "@/lib/cn";
import { relativeDue, when } from "@/lib/format";
import { keys } from "@/lib/queries";
import type { PracticeProblem, ProblemStatus, SourceSite } from "@/lib/types";

/**
 * The practice log: problems solved elsewhere, and when to solve them again.
 *
 * Phase 9 built six endpoints for this and docs/WEB.md — written as a Phase 5
 * spec, before Phase 9 existed — never gave it a route. So a logged solve moved
 * the same mastery a graded submission does, and there was no way to log one.
 *
 * The state this page is really designed around is `pending_classification`. A
 * classification below 0.75 confidence writes no evidence, and neither does one
 * whose provider was unreachable — the problem is recorded, listed, kept out of
 * the review queue, and feeds nothing until a human confirms the tag.
 * `concept_evidence` is immutable, so that gate is what stops a guess becoming a
 * permanent fact about your mastery. It is also the common case here today,
 * because no model provider is reachable yet.
 */

const SITES: SourceSite[] = ["leetcode", "codeforces", "other"];

const FILTERS: { label: string; value: ProblemStatus | undefined }[] = [
  { label: "All", value: undefined },
  { label: "Needs a tag", value: "pending_classification" },
  { label: "Active", value: "active" },
  { label: "Retired", value: "retired" },
];

export default function Practice() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<ProblemStatus | undefined>(undefined);

  const problems = useQuery({
    queryKey: ["practice-problems", status ?? "all"],
    queryFn: () => api.listProblems({ status }),
  });
  const queue = useQuery({ queryKey: keys.reviewQueue, queryFn: api.reviewQueue });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["practice-problems"] });
    queryClient.invalidateQueries({ queryKey: keys.reviewQueue });
  };

  const rows = problems.data?.problems ?? [];
  const pending = rows.filter((row) => row.status === "pending_classification").length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-ink text-xl font-semibold tracking-tight">Practice log</h1>
        <p className="text-ink-muted mt-0.5 text-sm">
          Problems you solved elsewhere, folded into the same mastery — and scheduled back
          before you forget them.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="space-y-6">
          <LeetCodeImport onImported={refresh} />
          <LogForm onLogged={refresh} />
        </div>

        <Card>
          <CardHeader
            title="Due to re-solve"
            hint="Most overdue first. A success stretches the interval; a miss shortens it."
          />
          <CardBody>
            {queue.isLoading ? (
              <Skeleton className="h-24" />
            ) : queue.data?.due.length ? (
              <ul className="divide-hairline divide-y">
                {queue.data.due.map((entry) => (
                  <li key={entry.id} className="flex flex-wrap items-baseline gap-2 py-2">
                    <Link
                      href={`/practice/${entry.id}`}
                      className="text-ink min-w-0 flex-1 truncate text-sm hover:underline"
                    >
                      {entry.title}
                    </Link>
                    <Badge tone={entry.days_overdue > 0 ? "critical" : "neutral"}>
                      {relativeDue(entry.due_at)}
                    </Badge>
                    <span className="text-ink-muted text-xs">
                      solved {entry.solve_count}×
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <Empty
                title="Nothing due"
                detail="Either nothing is scheduled yet, or you are up to date."
              />
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardBody className="grid grid-cols-2 gap-6 pt-4 md:grid-cols-4">
          <Stat label="Logged" value={problems.isLoading ? "—" : rows.length} />
          <Stat
            label="Awaiting a tag"
            value={problems.isLoading ? "—" : pending}
            note={pending ? "these feed nothing until confirmed" : undefined}
            tone={pending ? "default" : "muted"}
          />
          <Stat
            label="Due now"
            value={queue.isLoading ? "—" : (queue.data?.due.length ?? 0)}
          />
          <Stat
            label="Total solves"
            value={problems.isLoading ? "—" : rows.reduce((n, r) => n + r.solve_count, 0)}
          />
        </CardBody>
      </Card>

      <ConfirmSuggested rows={rows} onDone={refresh} />

      <Card>
        <CardHeader
          title="Everything logged"
          action={
            <div className="flex gap-1">
              {FILTERS.map((filter) => (
                <button
                  key={filter.label}
                  type="button"
                  onClick={() => setStatus(filter.value)}
                  aria-pressed={status === filter.value}
                  className={cn(
                    "rounded px-2 py-1 text-xs transition-colors",
                    status === filter.value
                      ? "bg-accent text-accent-ink"
                      : "text-ink-secondary hover:bg-sunken",
                  )}
                >
                  {filter.label}
                </button>
              ))}
            </div>
          }
        />
        <CardBody>
          {problems.error ? <ApiErrorNotice error={problems.error} /> : null}
          {problems.isLoading ? (
            <Skeleton className="h-32" />
          ) : rows.length === 0 ? (
            <Empty title="Nothing logged yet" detail="Add the first one on the left." />
          ) : (
            <ul className="divide-hairline divide-y">
              {rows.map((problem) => (
                <ProblemRow key={problem.id} problem={problem} />
              ))}
            </ul>
          )}
          {problems.data?.next_cursor ? (
            <p className="text-ink-muted mt-3 text-xs">
              More beyond this page. A filtered page can come back short — the cursor tracks
              the scan, not the matches.
            </p>
          ) : null}
        </CardBody>
      </Card>
    </div>
  );
}

/**
 * Confirm every suggestion at once.
 *
 * An import of fifty problems arrives with fifty suggestions and fifty confirmations
 * owed, which is the tedium the import was meant to remove — but each confirmation is a
 * real decision, since it writes immutable evidence. So the bulk action exists and says
 * exactly what it is about to do; it does not confirm anything the tags did not name.
 */
function ConfirmSuggested({
  rows,
  onDone,
}: {
  rows: PracticeProblem[];
  onDone: () => void;
}) {
  const ready = rows.filter(
    (row) => row.status === "pending_classification" && row.primary_concept_id,
  );

  const confirm = useMutation({
    mutationFn: async () => {
      // Sequential on purpose: each write moves the same mastery rows, and the server
      // serialises the projection anyway. Firing fifty at once would queue behind that
      // lock and time out rather than finish sooner.
      for (const row of ready) {
        await api.setClassification(row.id, row.primary_concept_id!);
      }
    },
    onSuccess: onDone,
  });

  if (ready.length === 0) return null;

  return (
    <Card>
      <CardBody className="flex flex-wrap items-center gap-3 pt-4">
        <div className="min-w-0 flex-1">
          <p className="text-ink text-sm font-medium">
            {ready.length} problem{ready.length === 1 ? "" : "s"} have a suggested concept
          </p>
          <p className="text-ink-muted mt-0.5 text-xs">
            Confirming writes evidence, and evidence is immutable — check anything you are
            unsure of first. Problems with no suggestion are left alone.
          </p>
        </div>
        {confirm.error ? <ApiErrorNotice error={confirm.error} /> : null}
        <Button disabled={confirm.isPending} onClick={() => confirm.mutate()}>
          {confirm.isPending ? `Confirming ${ready.length}…` : `Confirm all ${ready.length}`}
        </Button>
      </CardBody>
    </Card>
  );
}

function ProblemRow({ problem }: { problem: PracticeProblem }) {
  const needsTag = problem.status === "pending_classification";

  return (
    <li className="flex flex-wrap items-baseline gap-2 py-2">
      <Link
        href={`/practice/${problem.id}`}
        className="text-ink min-w-0 flex-1 truncate text-sm hover:underline"
      >
        {problem.title}
      </Link>
      <span className="text-ink-muted text-xs">{problem.source_site}</span>
      {problem.primary_concept_id ? (
        <span className="text-ink-secondary font-mono text-xs">
          {problem.primary_concept_id}
        </span>
      ) : null}
      {needsTag ? (
        <Badge tone={problem.primary_concept_id ? "serious" : "warning"}>
          {problem.primary_concept_id ? "suggested — confirm it" : "needs a tag"}
        </Badge>
      ) : problem.status === "retired" ? (
        <Badge tone="good">retired</Badge>
      ) : (
        <Badge>{relativeDue(problem.due_at)}</Badge>
      )}
      <span className="text-ink-muted text-xs">{when(problem.created_at)}</span>
    </li>
  );
}

function LogForm({ onLogged }: { onLogged: () => void }) {
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [site, setSite] = useState<SourceSite>("leetcode");
  const [difficulty, setDifficulty] = useState("");
  const [notes, setNotes] = useState("");

  const log = useMutation({
    mutationFn: () =>
      api.logProblem(
        {
          title: title.trim(),
          url: url.trim(),
          source_site: site,
          difficulty_label: difficulty.trim() || null,
          notes: notes.trim() || null,
        },
        idempotencyKey(),
      ),
    onSuccess: () => {
      setTitle("");
      setUrl("");
      setDifficulty("");
      setNotes("");
      onLogged();
    },
  });

  const ready = title.trim().length > 0 && url.trim().length > 0;

  return (
    <Card>
      <CardHeader
        title="Log a problem you solved"
        hint="The URL is a pointer and is never fetched — the problem text stays where it is."
      />
      <CardBody className="space-y-3">
        <Labelled label="Title" htmlFor="p-title">
          <input
            id="p-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Longest Substring Without Repeating Characters"
            className="border-hairline bg-surface text-ink w-full rounded-md border px-2 py-1.5 text-sm"
          />
        </Labelled>

        <Labelled label="URL" htmlFor="p-url">
          <input
            id="p-url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://leetcode.com/problems/…"
            className="border-hairline bg-surface text-ink w-full rounded-md border px-2 py-1.5 text-sm"
          />
        </Labelled>

        <div className="flex flex-wrap gap-3">
          <Labelled label="Source">
            <div className="flex gap-1">
              {SITES.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setSite(option)}
                  aria-pressed={site === option}
                  className={cn(
                    "rounded px-2 py-1 text-xs transition-colors",
                    site === option
                      ? "bg-accent text-accent-ink"
                      : "border-hairline text-ink-secondary hover:bg-sunken border",
                  )}
                >
                  {option}
                </button>
              ))}
            </div>
          </Labelled>
          <Labelled label="Difficulty" htmlFor="p-diff">
            <input
              id="p-diff"
              value={difficulty}
              onChange={(event) => setDifficulty(event.target.value)}
              placeholder="Medium"
              className="border-hairline bg-surface text-ink w-28 rounded-md border px-2 py-1.5 text-sm"
            />
          </Labelled>
        </div>

        <Labelled label="Notes" htmlFor="p-notes" hint="Your own words — what made it hard.">
          <textarea
            id="p-notes"
            rows={3}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            className="border-hairline bg-surface text-ink w-full resize-y rounded-md border px-2 py-1.5 text-sm"
          />
        </Labelled>

        {log.error ? <ApiErrorNotice error={log.error} /> : null}

        {log.isSuccess ? (
          <p className="text-ink-secondary text-sm">
            Logged.{" "}
            {log.data?.status === "pending_classification" ? (
              <>
                It needs a concept before it counts —{" "}
                <Link href={`/practice/${log.data.id}`} className="underline">
                  tag it now
                </Link>
                .
              </>
            ) : (
              <>
                Tagged{" "}
                <span className="font-mono">{log.data?.primary_concept_id}</span> and
                scheduled.
              </>
            )}
          </p>
        ) : null}

        <Button disabled={!ready || log.isPending} onClick={() => log.mutate()}>
          {log.isPending ? "Classifying…" : "Log it"}
        </Button>
        <p className="text-ink-muted text-xs">
          A tag the classifier is under 0.75 confident about writes no evidence — and with
          no model provider reachable yet, that is every entry. You name the concept and it
          counts from then on.
        </p>
      </CardBody>
    </Card>
  );
}

function Labelled({
  label,
  hint,
  htmlFor,
  children,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <label
        htmlFor={htmlFor}
        className="text-ink-muted mb-1 block text-xs font-medium tracking-wide uppercase"
      >
        {label}
        {hint ? <span className="ml-2 normal-case">{hint}</span> : null}
      </label>
      {children}
    </div>
  );
}
