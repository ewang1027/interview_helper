"use client";

import Link from "next/link";
import { cn } from "@/lib/cn";
import { elo } from "@/lib/format";
import type { PriorityTerms, RankedConcept } from "@/lib/types";

/**
 * The weakness ranking, with the priority breakdown behind each rank.
 *
 * The breakdown is the feature, not decoration: docs/ADAPTIVE.md's weights are
 * placeholders waiting to be argued with, and "a ranking you cannot take apart
 * is a ranking you cannot argue with". Each row can be expanded into its five
 * terms, drawn as a diverging bar because one of them — recent exposure — is
 * negative by construction, and a magnitude-only bar would hide the fact that
 * it pushes a concept *down* the list.
 */

const TERM_LABEL: Record<keyof PriorityTerms, string> = {
  weakness: "Low ability",
  recent_errors: "Recent errors",
  overdue: "Overdue",
  unlocks: "Unlocks others",
  recent_exposure: "Seen recently",
};

function TermBar({ term, value, scale }: { term: keyof PriorityTerms; value: number; scale: number }) {
  const width = scale === 0 ? 0 : (Math.abs(value) / scale) * 50;
  const negative = value < 0;

  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="text-ink-muted w-24 shrink-0 truncate">{TERM_LABEL[term]}</span>
      {/* One axis, zero in the middle: the sign is a direction, not a colour. */}
      <div className="relative h-2 min-w-0 flex-1">
        <span className="bg-hairline absolute inset-y-0 left-1/2 w-px" aria-hidden />
        <span
          className={cn(
            "absolute inset-y-0 rounded-[2px]",
            negative ? "bg-ability-2" : "bg-ability-4",
          )}
          style={
            negative
              ? { right: "50%", width: `${width}%` }
              : { left: "50%", width: `${width}%` }
          }
        />
      </div>
      <span className="tabular text-ink-muted w-12 shrink-0 text-right">{value.toFixed(3)}</span>
    </div>
  );
}

export function WeaknessList({
  concepts,
  weights,
}: {
  concepts: RankedConcept[];
  weights?: PriorityTerms;
}) {
  // One scale across every row, so a term's bar means the same thing everywhere.
  const scale = Math.max(
    0.001,
    ...concepts.flatMap((concept) => Object.values(concept.terms).map(Math.abs)),
  );

  return (
    <ol className="divide-hairline divide-y">
      {concepts.map((concept, index) => (
        <li key={concept.concept_id} className="py-2 first:pt-0 last:pb-0">
          <details className="group">
            <summary className="flex cursor-pointer list-none items-baseline gap-2">
              <span className="tabular text-ink-muted w-5 shrink-0 text-xs">{index + 1}</span>
              <span className="min-w-0 flex-1">
                <Link
                  href={`/concepts/${concept.concept_id}`}
                  className="text-ink text-sm hover:underline"
                  onClick={(event) => event.stopPropagation()}
                >
                  {concept.name}
                </Link>
                <span className="text-ink-muted ml-2 text-xs">
                  {concept.unseen
                    ? "never measured"
                    : `${elo(concept.ability)} · ${concept.observations} obs`}
                </span>
              </span>
              <span className="tabular text-ink-secondary shrink-0 text-xs">
                {concept.priority.toFixed(3)}
              </span>
              <span className="text-ink-muted shrink-0 text-xs group-open:hidden">▸</span>
              <span className="text-ink-muted hidden shrink-0 text-xs group-open:inline">▾</span>
            </summary>
            <div className="mt-2 space-y-1 pl-7">
              {(Object.keys(TERM_LABEL) as (keyof PriorityTerms)[]).map((term) => (
                <TermBar key={term} term={term} value={concept.terms[term]} scale={scale} />
              ))}
              {weights ? (
                <p className="text-ink-muted pt-1 text-[11px]">
                  Weights: {Object.entries(weights).map(([k, v]) => `${k} ${v}`).join(" · ")} —
                  placeholders until real sessions calibrate them.
                </p>
              ) : null}
            </div>
          </details>
        </li>
      ))}
    </ol>
  );
}
