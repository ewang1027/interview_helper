"use client";

import { CategoryDot } from "@/components/jobs/category-breakdown";
import { Empty } from "@/components/ui/primitives";
import { percent } from "@/lib/format";
import type { Rejections as RejectionsView } from "@/lib/types";

/**
 * The rejections tracker — the half of the funnel that reads downward.
 *
 * The funnel says how many reached each rung. This says, of the ones that ended
 * in a rejection, **which rung they were rejected after**, and when. Both are
 * read off `furthest_stage` (docs/JOBS.md), for the same reason the funnel is:
 * a rejection after an onsite is a different fact from a rejection at `applied`,
 * and a tracker that files both under "rejected" has thrown away the only thing
 * worth knowing about either. Ten noes at `applied` is a problem with the
 * applications; ten after a final round is a different problem.
 *
 * The bars share the funnel's one hue on purpose — the share is what varies,
 * and a red ramp here would say "worse" about a number that is only "later".
 * Every value is printed, so nothing is carried by length alone.
 */
export function Rejections({ rejections }: { rejections: RejectionsView }) {
  if (!rejections.total) {
    return (
      <Empty
        title="Nothing rejected yet"
        detail="When an application is moved to rejected, it is filed here under the stage it got to first."
      />
    );
  }

  const widest = Math.max(...rejections.after_stage.map((step) => step.count), 1);
  const rungs = rejections.after_stage.filter(
    // Rungs nothing was rejected after are noise below the top of the ladder, but an
    // empty rung *between* two used ones is the shape of the pipeline and stays.
    (step, index, steps) => step.count > 0 || steps.slice(index + 1).some((later) => later.count > 0),
  );

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <div>
        <h3 className="text-ink-secondary text-xs font-medium tracking-wide uppercase">
          Rejected after
        </h3>
        <ol className="mt-2 space-y-2" aria-label="Rejections by stage reached">
          {rungs.map((step) => (
            <li key={step.stage}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-ink text-sm font-medium">{step.label}</span>
                <span className="text-ink-muted text-xs tabular-nums">
                  {percent(step.share)} of rejections
                </span>
              </div>
              <div className="mt-1 flex items-center gap-3">
                <div className="bg-sunken relative h-5 min-w-0 flex-1 overflow-hidden rounded">
                  <div
                    className="h-full rounded bg-[var(--accent)] transition-[width] duration-300"
                    style={{ width: `${(step.count / widest) * 100}%` }}
                  />
                </div>
                <span className="text-ink w-10 shrink-0 text-right text-sm font-semibold tabular-nums">
                  {step.count}
                </span>
              </div>
            </li>
          ))}
        </ol>
        <p className="text-ink-muted mt-3 text-xs">
          {rejections.median_days_to_rejection === null
            ? "No rejection dates recorded yet."
            : `Median ${Math.round(rejections.median_days_to_rejection)} days from applying to the no.`}
        </p>
      </div>

      <div>
        <h3 className="text-ink-secondary text-xs font-medium tracking-wide uppercase">
          Most recent
        </h3>
        <ol className="divide-hairline mt-2 divide-y" aria-label="Recent rejections">
          {rejections.recent.map((row) => (
            <li key={row.id} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 py-1.5">
              {row.category ? <CategoryDot category={row.category} /> : null}
              <span className="text-ink min-w-0 text-sm font-medium">{row.company}</span>
              <span className="text-ink-secondary min-w-0 truncate text-sm">{row.role}</span>
              <span className="text-ink-muted ml-auto shrink-0 text-xs tabular-nums">
                after {row.furthest_stage_label.toLowerCase()}
                {row.days_after_applying !== null ? ` · ${row.days_after_applying}d in` : null}
                {row.rejected_at ? ` · ${shortDate(row.rejected_at)}` : null}
              </span>
            </li>
          ))}
        </ol>
        {rejections.total > rejections.recent.length ? (
          <p className="text-ink-muted mt-2 text-xs">
            {rejections.recent.length} of {rejections.total} — filter the board below to see
            every one.
          </p>
        ) : null}
      </div>
    </div>
  );
}

function shortDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
