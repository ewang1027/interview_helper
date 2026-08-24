"use client";

import { Badge, Empty } from "@/components/ui/primitives";
import { elo, percent } from "@/lib/format";
import type { Plan } from "@/lib/types";

/**
 * What the planner decided, and why.
 *
 * docs/API.md returns the plan up front deliberately — "you should be able to
 * see what it decided to drill you on, and why, before the session starts.
 * Opaque adaptation is untrustworthy adaptation." This renders all of it: the
 * concept each item targets, what you were expected to score, whether that
 * lands in the informative band, and the concepts it weighed but did not serve.
 */
export function PlanPreview({ plan }: { plan: Plan }) {
  if (!plan.items.length) {
    return (
      <Empty
        title="The planner chose nothing"
        detail="No item in this mode measures a rankable concept as its primary concept."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {plan.calibration ? (
          <Badge tone="warning">calibrating — no evidence yet</Badge>
        ) : (
          <Badge tone="accent">adaptive</Badge>
        )}
        <Badge>{plan.strategy}</Badge>
        <Badge>
          {plan.estimated_minutes} of {plan.budget_minutes} min
        </Badge>
        <Badge>
          informative band {percent(plan.band[0])}–{percent(plan.band[1])}
        </Badge>
      </div>

      <p className="text-ink-secondary text-sm">{plan.why}</p>

      <ol className="space-y-2">
        {plan.items.map((item, index) => (
          <li key={item.item_id} className="border-hairline rounded-md border p-3">
            <div className="flex items-baseline gap-2">
              <span className="tabular text-ink-muted text-xs">{index + 1}</span>
              <span className="text-ink min-w-0 flex-1 text-sm font-medium">{item.title}</span>
              <span className="text-ink-muted text-xs">
                {item.expected_minutes ? `${item.expected_minutes} min` : "—"}
              </span>
            </div>
            <div className="text-ink-muted mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 pl-6 text-xs">
              <span>
                targets <span className="text-ink-secondary">{item.reason.targets}</span>
              </span>
              <span>
                expected{" "}
                <span className="text-ink-secondary tabular">
                  {percent(item.reason.expected_score)}
                </span>
              </span>
              <span className="tabular">item {elo(item.elo)} Elo</span>
              {item.reason.in_band ? (
                <Badge tone="good">in band</Badge>
              ) : (
                <Badge>outside band</Badge>
              )}
              {item.reason.calibrating ? <Badge tone="warning">calibrating</Badge> : null}
            </div>
            {item.reason.prerequisite_note ? (
              <p className="text-ink-muted mt-1.5 pl-6 text-xs italic">
                {item.reason.prerequisite_note}
              </p>
            ) : null}
          </li>
        ))}
      </ol>

      {plan.considered.length ? (
        <details className="group">
          <summary className="text-ink-secondary hover:text-ink cursor-pointer list-none text-xs">
            <span className="underline underline-offset-2">
              What it weighed but did not serve
            </span>
            <span className="ml-1 group-open:hidden">▸</span>
            <span className="ml-1 hidden group-open:inline">▾</span>
          </summary>
          <ul className="mt-2 space-y-1">
            {plan.considered.map((concept) => (
              <li
                key={concept.concept_id}
                className="text-ink-muted flex items-baseline gap-2 text-xs"
              >
                <span className="tabular w-12 shrink-0">{concept.priority.toFixed(3)}</span>
                <span className="min-w-0 flex-1 truncate">{concept.name}</span>
                <span>{concept.unseen ? "never measured" : `${concept.observations} obs`}</span>
              </li>
            ))}
          </ul>
          <p className="text-ink-muted mt-2 text-xs">
            The ranking covers the whole taxonomy; the planner serves only concepts some
            item measures as a <em>primary</em> concept, which is narrower on purpose.
          </p>
        </details>
      ) : null}
    </div>
  );
}
