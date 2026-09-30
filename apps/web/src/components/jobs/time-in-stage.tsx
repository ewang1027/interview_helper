"use client";

import { CategoryDot } from "@/components/jobs/category-breakdown";
import { Empty } from "@/components/ui/primitives";
import type { TimeInStage as TimeInStageView } from "@/lib/types";

/**
 * Time in stage — how long applications sit on each rung, read off the event log.
 *
 * The rejections tracker answered one slice of this (applying to the no). This is
 * the rest, and it keeps two readings apart because they answer different
 * questions (docs/JOBS.md, decision 6):
 *
 * - **Before moving on** — the median days on a rung over every application that
 *   left it, whichever way it went. How long a company usually takes at that step.
 * - **Waiting longest** — the open applications, each on its current rung since
 *   its last event. What is sitting *now*, and for how long.
 *
 * A row that arrived mid-ladder (imported at `final`) was never timed into that
 * rung, so it adds nothing to the first reading; it still waits in the second,
 * from when it was recorded there — a lower bound, and labelled as "since".
 */
export function TimeInStage({ report }: { report: TimeInStageView }) {
  const rungs = report.stages.filter((step) => step.left > 0 || step.waiting > 0);
  if (!rungs.length) {
    return (
      <Empty
        title="Nothing timed yet"
        detail="Once an application moves from one stage to the next, the time it spent there shows up here."
      />
    );
  }

  return (
    // `min-w-0` on both columns for the reason docs/WEB.md records against the
    // rejections card: a `truncate` role name otherwise floors a grid column at its
    // full string width and the page scrolls sideways on a phone.
    <div className="grid gap-6 md:grid-cols-2">
      <div className="min-w-0">
        <h3 className="text-ink-secondary text-xs font-medium tracking-wide uppercase">
          Before moving on
        </h3>
        <ol className="divide-hairline mt-2 divide-y" aria-label="Time spent at each stage">
          {rungs.map((step) => (
            <li key={step.stage} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5">
              <span className="text-ink min-w-0 text-sm font-medium">{step.label}</span>
              <span className="text-ink-muted ml-auto shrink-0 text-xs tabular-nums">
                {step.median_days === null
                  ? "none moved on yet"
                  : `median ${days(step.median_days)} · mean ${days(step.mean_days ?? 0)} · ${step.left} moved on`}
                {step.waiting ? ` · ${step.waiting} waiting` : null}
              </span>
            </li>
          ))}
        </ol>
      </div>

      <div className="min-w-0">
        <h3 className="text-ink-secondary text-xs font-medium tracking-wide uppercase">
          Waiting longest
        </h3>
        {report.longest_waiting.length ? (
          <ol className="divide-hairline mt-2 divide-y" aria-label="Open applications waiting longest">
            {report.longest_waiting.map((row) => (
              <li key={row.id} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 py-1.5">
                {row.category ? <CategoryDot category={row.category} /> : null}
                <span className="text-ink min-w-0 text-sm font-medium">{row.company}</span>
                <span className="text-ink-secondary min-w-0 truncate text-sm">{row.role}</span>
                <span className="text-ink-muted ml-auto shrink-0 text-xs tabular-nums">
                  {row.stage_label.toLowerCase()} · {row.days}d since
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-ink-muted mt-2 text-xs">Nothing open.</p>
        )}
      </div>
    </div>
  );
}

function days(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return `${rounded}d`;
}
