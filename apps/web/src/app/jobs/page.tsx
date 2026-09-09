"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiErrorNotice } from "@/components/api-error";
import { CATEGORY_LABEL, CategoryBreakdown } from "@/components/jobs/category-breakdown";
import { Funnel } from "@/components/jobs/funnel";
import { ImportForm, ManualForm } from "@/components/jobs/import-form";
import { Pipeline } from "@/components/jobs/pipeline";
import { Rejections } from "@/components/jobs/rejections";
import {
  Card,
  CardBody,
  CardHeader,
  Skeleton,
  Stat,
} from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { percent } from "@/lib/format";
import type { JobCategory, JobOutcome } from "@/lib/types";

/** The board's outcome filter. `open` is what is live; `rejected` is the tracker's list. */
const OUTCOME_FILTERS: { value: JobOutcome | undefined; label: string }[] = [
  { value: undefined, label: "All" },
  { value: "open", label: "Live" },
  { value: "rejected", label: "Rejected" },
];

/**
 * The job tracker — what you applied to, and how far each one got.
 *
 * This page answers two different questions and keeps them apart, because
 * conflating them is what makes most application trackers useless. *Where does
 * the pipeline leak* is a question about history, and the funnel answers it off
 * `furthest_stage` — so a rejection after an onsite still counts as an onsite
 * reached (docs/JOBS.md). *What is live right now* is a question about the
 * present, and the board below answers that off `current_stage`.
 *
 * The response rate is a headline number rather than a chart, because it is one
 * number and a chart of one number is a decoration. It is also the figure most
 * worth seeing first: a hundred applications with a 4% response rate is a
 * problem with the applications, not with the interviews.
 *
 * The rejections tracker is the funnel read downward: of the applications that
 * ended in a no, which rung was it after, and how long did it take. It gets its
 * own card rather than a bar on the funnel because `rejected` is off the ladder
 * (docs/JOBS.md) — it is a way a pipeline ends, not a place in it.
 */
export default function Jobs() {
  const queryClient = useQueryClient();
  const [category, setCategory] = useState<JobCategory | undefined>();
  const [outcome, setOutcome] = useState<JobOutcome | undefined>();

  const catalog = useQuery({
    queryKey: ["jobs-catalog"],
    queryFn: api.jobCatalog,
    // Server-side constants: they cannot change while the process is up.
    staleTime: Infinity,
  });
  const stats = useQuery({ queryKey: ["jobs-stats"], queryFn: api.jobStats });
  const applications = useQuery({
    queryKey: ["jobs", category ?? "all", outcome ?? "any"],
    queryFn: () => api.listJobs({ category, outcome }),
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    queryClient.invalidateQueries({ queryKey: ["jobs-stats"] });
  };

  const summary = stats.data;
  const rows = applications.data?.applications ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-ink text-xl font-semibold tracking-tight">Applications</h1>
        <p className="text-ink-muted mt-0.5 text-sm">
          Where every application got to — and where the pipeline leaks. Stages are recorded
          as events, so a rejection never erases the rounds that came before it.
        </p>
      </div>

      {stats.error ? <ApiErrorNotice error={stats.error} /> : null}

      <Card>
        <CardBody className="grid grid-cols-2 gap-4 pt-4 sm:grid-cols-3 lg:grid-cols-6">
          {stats.isLoading || !summary ? (
            <Skeleton className="col-span-full h-14" />
          ) : (
            <>
              <Stat label="Applied" value={summary.total} />
              <Stat
                label="Heard back"
                value={percent(summary.response_rate)}
                note={`${summary.responded} of ${summary.total}`}
              />
              <Stat label="Live" value={summary.open} note="not yet closed out" />
              <Stat
                label="Offers"
                value={summary.offers}
                tone={summary.offers ? "default" : "muted"}
              />
              <Stat
                label="Rejected"
                value={summary.rejected}
                tone={summary.rejected ? "default" : "muted"}
                note={summary.rejected ? `${percent(summary.rejections.rate)} of applied` : "none yet"}
              />
              <Stat
                label="Need a tag"
                value={summary.needs_review}
                tone={summary.needs_review ? "default" : "muted"}
                note={summary.needs_review ? "proposed, not confirmed" : "all tagged"}
              />
            </>
          )}
        </CardBody>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Funnel"
            hint="How many ever reached each rung — counted off the furthest stage, not the current one."
          />
          <CardBody>
            {stats.isLoading || !summary ? (
              <Skeleton className="h-56" />
            ) : (
              <Funnel steps={summary.funnel} total={summary.total} />
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="By category"
            hint="Tagged by the model when you paste a list, correctable on any row."
          />
          <CardBody>
            {stats.isLoading || !summary ? <Skeleton className="h-56" /> : <CategoryBreakdown stats={summary} />}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Rejections"
          hint="Which stage each no came after, and how long it took — filed by the furthest stage reached, like the funnel."
          action={
            summary?.rejections.total ? (
              <button
                onClick={() => setOutcome(outcome === "rejected" ? undefined : "rejected")}
                className={cn(
                  "rounded-md px-2 py-1 text-xs transition-colors",
                  outcome === "rejected"
                    ? "bg-sunken text-ink font-medium"
                    : "text-ink-secondary hover:bg-sunken",
                )}
              >
                {outcome === "rejected" ? "Showing all on the board" : "Show all on the board"}
              </button>
            ) : null
          }
        />
        <CardBody>
          {stats.isLoading || !summary ? (
            <Skeleton className="h-40" />
          ) : (
            <Rejections rejections={summary.rejections} />
          )}
        </CardBody>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <ImportForm onImported={refresh} />
        <ManualForm catalog={catalog.data} onCreated={refresh} />
      </div>

      <Card>
        <CardHeader
          title="The board"
          hint="Newest first, twenty at a time — search to reach one directly. Changing a stage appends to its history."
          action={
            <div className="flex flex-wrap items-center gap-1">
              {([undefined, "swe", "ai", "quant", "other"] as const).map((value) => (
                <button
                  key={value ?? "all"}
                  onClick={() => setCategory(value)}
                  className={cn(
                    "rounded-md px-2 py-1 text-xs transition-colors",
                    category === value
                      ? "bg-sunken text-ink font-medium"
                      : "text-ink-secondary hover:bg-sunken",
                  )}
                >
                  {value ? CATEGORY_LABEL[value] : "All"}
                </button>
              ))}
              <span className="border-hairline mx-1 h-4 border-l" aria-hidden="true" />
              {OUTCOME_FILTERS.map(({ value, label }) => (
                <button
                  key={value ?? "any"}
                  onClick={() => setOutcome(value)}
                  aria-pressed={outcome === value}
                  className={cn(
                    "rounded-md px-2 py-1 text-xs transition-colors",
                    outcome === value
                      ? "bg-sunken text-ink font-medium"
                      : "text-ink-secondary hover:bg-sunken",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          }
        />
        <CardBody>
          {applications.isLoading ? (
            <Skeleton className="h-40" />
          ) : applications.error ? (
            <ApiErrorNotice error={applications.error} />
          ) : (
            /* Keyed on the filters so switching categories or outcomes starts the board
               over at twenty rows with an empty search — a different question deserves a
               fresh answer. Deliberately *not* keyed on the data: a refetch after a stage
               change must leave an expanded board expanded, or moving row forty along
               would scroll the row you are working on out of existence. */
            <Pipeline
              key={`${category ?? "all"}:${outcome ?? "any"}`}
              applications={rows}
              catalog={catalog.data}
              onChanged={refresh}
            />
          )}
        </CardBody>
      </Card>
    </div>
  );
}
