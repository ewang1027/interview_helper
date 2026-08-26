"use client";

import { useMutation } from "@tanstack/react-query";
import { CATEGORY_LABEL, CategoryDot } from "@/components/jobs/category-breakdown";
import { Badge, Button, Empty } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { titleCase, when } from "@/lib/format";
import type { JobApplication, JobCatalog, Stage } from "@/lib/types";

/**
 * The board: every application, and the control that moves one along.
 *
 * The stage control writes an **event** rather than setting a field
 * (docs/JOBS.md), which is why moving something to `rejected` does not erase the
 * rounds it got through first — the funnel above is still counting those. That
 * is invisible here by design: the person clicking should not have to know the
 * difference, and the history is on the row's own page.
 *
 * A row awaiting a tag is marked rather than hidden. Unlike the practice log's
 * confidence gate, this one holds nothing back — an application writes no
 * evidence — so `pending_classification` is a nudge, not a quarantine.
 */

const TONE_FOR_OUTCOME = {
  open: "neutral",
  offer: "good",
  rejected: "critical",
  withdrawn: "neutral",
  ghosted: "warning",
} as const;

export function Pipeline({
  applications,
  catalog,
  onChanged,
}: {
  applications: JobApplication[];
  catalog: JobCatalog | undefined;
  onChanged: () => void;
}) {
  if (!applications.length) {
    return <Empty title="No applications yet" detail="Paste a list, or add one by hand." />;
  }
  return (
    <ul className="divide-hairline divide-y">
      {applications.map((application) => (
        <Row
          key={application.id}
          application={application}
          catalog={catalog}
          onChanged={onChanged}
        />
      ))}
    </ul>
  );
}

function Row({
  application,
  catalog,
  onChanged,
}: {
  application: JobApplication;
  catalog: JobCatalog | undefined;
  onChanged: () => void;
}) {
  const move = useMutation({
    mutationFn: (stage: Stage) => api.setJobStage(application.id, stage),
    onSuccess: onChanged,
  });
  const tag = useMutation({
    mutationFn: (subcategory: string) => api.setJobClassification(application.id, subcategory),
    onSuccess: onChanged,
  });
  const remove = useMutation({
    mutationFn: () => api.deleteJob(application.id),
    onSuccess: onChanged,
  });

  const stages = catalog ? [...catalog.ladder, ...catalog.terminal] : [];
  const subcategories = catalog
    ? Object.entries(catalog.categories).flatMap(([category, subs]) =>
        subs.map((sub) => ({ category, sub })),
      )
    : [];

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          {application.category ? <CategoryDot category={application.category} /> : null}
          <span className="text-ink truncate text-sm font-medium">{application.company}</span>
          <span className="text-ink-secondary truncate text-sm">{application.role}</span>
          {application.url ? (
            <a
              href={application.url}
              target="_blank"
              rel="noreferrer noopener"
              className="text-ink-muted text-xs hover:underline"
            >
              posting ↗
            </a>
          ) : null}
        </div>
        <div className="text-ink-muted mt-0.5 flex flex-wrap items-center gap-x-2 text-xs">
          <span>{when(application.applied_at)}</span>
          {application.location ? <span>· {application.location}</span> : null}
          {application.category ? (
            <span>
              · {CATEGORY_LABEL[application.category]}
              {application.subcategory ? ` / ${titleCase(application.subcategory)}` : null}
            </span>
          ) : null}
          {application.source !== "manual" ? (
            <span>· {application.source === "paste+research" ? "researched" : "pasted"}</span>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {application.status === "pending_classification" ? (
          <span className="flex flex-wrap items-center gap-1">
            {/* Confirming the proposal is the common case and gets its own button.
                It used to be an option in the select below, pre-selected — which meant
                choosing it fired no `change` event at all, so the one action a person
                most wanted was the one the control could not perform. You could only
                confirm the proposal by picking a *different* tag first. */}
            {application.subcategory ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={tag.isPending}
                title={`Confirm ${CATEGORY_LABEL[application.category ?? "other"]} · ${titleCase(
                  application.subcategory,
                )} — proposed, not yet confirmed`}
                onClick={() => tag.mutate(application.subcategory!)}
              >
                {tag.isPending ? "Saving…" : `Confirm ${titleCase(application.subcategory)}`}
              </Button>
            ) : (
              <Badge tone="warning">needs a tag</Badge>
            )}
            <select
              aria-label={`Tag ${application.company}`}
              className="border-hairline bg-page text-ink rounded-md border px-2 py-1 text-xs"
              /* Always the placeholder, never a real tag. A `<select>` fires no `change`
                 when you pick the option it is already showing, so a control whose value
                 is one of its own tags has a dead option in it by construction. Pinning
                 it to "" makes every pick a change. */
              value=""
              disabled={tag.isPending}
              onChange={(event) => event.target.value && tag.mutate(event.target.value)}
            >
              <option value="">{application.subcategory ? "Change…" : "Choose a tag…"}</option>
              {subcategories.map(({ category, sub }) => (
                <option key={sub} value={sub}>
                  {titleCase(category)} · {titleCase(sub)}
                </option>
              ))}
            </select>
          </span>
        ) : null}

        <Badge tone={TONE_FOR_OUTCOME[application.outcome]}>
          {application.current_stage_label}
        </Badge>

        <select
          aria-label={`Move ${application.company} to a stage`}
          className={cn(
            "border-hairline bg-page text-ink rounded-md border px-2 py-1 text-xs",
            move.isPending && "opacity-50",
          )}
          value={application.current_stage}
          disabled={move.isPending}
          onChange={(event) => move.mutate(event.target.value as Stage)}
        >
          {stages.map((stage) => (
            <option key={stage} value={stage}>
              {catalog?.stage_labels[stage] ?? titleCase(stage)}
            </option>
          ))}
        </select>

        <Button
          variant="ghost"
          size="sm"
          title="Remove this application and its history"
          disabled={remove.isPending}
          onClick={() => remove.mutate()}
        >
          ✕
        </Button>
      </div>
    </li>
  );
}
