"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiErrorNotice } from "@/components/api-error";
import { CATEGORY_LABEL, CategoryBreakdown } from "@/components/jobs/category-breakdown";
import { Funnel } from "@/components/jobs/funnel";
import { ImportForm, ManualForm } from "@/components/jobs/import-form";
import { Pipeline } from "@/components/jobs/pipeline";
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
import type { JobCategory } from "@/lib/types";

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
 */
export default function Jobs() {
  const queryClient = useQueryClient();
  const [category, setCategory] = useState<JobCategory | undefined>();

  const catalog = useQuery({
    queryKey: ["jobs-catalog"],
    queryFn: api.jobCatalog,
    // Server-side constants: they cannot change while the process is up.
    staleTime: Infinity,
  });
  const stats = useQuery({ queryKey: ["jobs-stats"], queryFn: api.jobStats });
  const applications = useQuery({
    queryKey: ["jobs", category ?? "all"],
    queryFn: () => api.listJobs({ category }),
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
        <CardBody className="grid grid-cols-2 gap-4 pt-4 sm:grid-cols-5">
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

      <div className="grid gap-6 lg:grid-cols-2">
        <ImportForm onImported={refresh} />
        <ManualForm catalog={catalog.data} onCreated={refresh} />
      </div>

      <Card>
        <CardHeader
          title="The board"
          hint="Newest first, twenty at a time — search to reach one directly. Changing a stage appends to its history."
          action={
            <div className="flex flex-wrap gap-1">
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
            </div>
          }
        />
        <CardBody>
          {applications.isLoading ? (
            <Skeleton className="h-40" />
          ) : applications.error ? (
            <ApiErrorNotice error={applications.error} />
          ) : (
            /* Keyed on the filter so switching categories starts the board over at
               twenty rows with an empty search — a different question deserves a fresh
               answer. Deliberately *not* keyed on the data: a refetch after a stage
               change must leave an expanded board expanded, or moving row forty along
               would scroll the row you are working on out of existence. */
            <Pipeline
              key={category ?? "all"}
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
