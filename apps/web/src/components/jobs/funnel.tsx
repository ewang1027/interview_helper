"use client";

import { Empty } from "@/components/ui/primitives";
import { percent } from "@/lib/format";
import type { FunnelStep } from "@/lib/types";

/**
 * The application funnel — how many got to each rung of the ladder.
 *
 * Three things about it are decisions rather than styling:
 *
 * - **It counts `furthest_stage`, not `current_stage`**, and the server computes
 *   it that way (docs/JOBS.md). A rejection after an onsite still counts in
 *   every rung it reached, so these bars cannot improve because something went
 *   badly — which is what they would do if a rejection removed an application
 *   from the buckets above `applied`.
 * - **One series, one hue.** Length encodes the count; colour encodes nothing,
 *   so it does not vary. A ramp across the rungs would imply the *stage* had a
 *   magnitude, which it does not — that is what the ability heatmap's ramp is
 *   for and this is not that.
 * - **Two numbers per rung, both printed.** `reached` alone is misleading: 40%
 *   of applications reaching an assessment says nothing about how the
 *   assessments go. The step-to-step conversion is where a pipeline actually
 *   leaks, and it is the number worth acting on.
 *
 * Every value is directly labelled, so this reads as a table that happens to be
 * drawn — nothing here is available only by hovering, and nothing is carried by
 * colour alone.
 */
export function Funnel({ steps, total }: { steps: FunnelStep[]; total: number }) {
  if (!total) {
    return (
      <Empty
        title="Nothing applied to yet"
        detail="Paste a list or add one by hand, and the funnel fills in from the stages you record."
      />
    );
  }

  return (
    <ol className="space-y-2" aria-label="Application funnel">
      {steps.map((step, index) => {
        // Width is a share of the widest rung, which is always `applied`, so the
        // top bar is full and the rest are read against it.
        const width = total ? (step.reached / total) * 100 : 0;
        const dropped = index > 0 ? steps[index - 1].reached - step.reached : 0;
        return (
          <li key={step.stage} className="group">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-ink text-sm font-medium">{step.label}</span>
              <span className="text-ink-muted text-xs tabular-nums">
                {index > 0 ? (
                  <>
                    {percent(step.conversion)} of {steps[index - 1].label.toLowerCase()}
                    {dropped > 0 ? ` · ${dropped} fell out` : null}
                  </>
                ) : (
                  "everything applied to"
                )}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-3">
              {/* The track is the full width so the bars are read against a
                  constant, not against each other's ends. */}
              <div className="bg-sunken relative h-6 min-w-0 flex-1 overflow-hidden rounded">
                <div
                  className="h-full rounded bg-[var(--accent)] transition-[width] duration-300"
                  style={{ width: `${Math.max(width, step.reached > 0 ? 1.5 : 0)}%` }}
                />
              </div>
              <span className="text-ink w-16 shrink-0 text-right text-sm font-semibold tabular-nums">
                {step.reached}
                <span className="text-ink-muted font-normal"> / {total}</span>
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
