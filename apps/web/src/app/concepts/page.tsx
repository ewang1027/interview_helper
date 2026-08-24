"use client";

import { useState } from "react";
import { ApiErrorNotice } from "@/components/api-error";
import { MasteryHeatmap, toHeatmapConcepts } from "@/components/mastery-heatmap";
import { Card, CardBody, CardHeader, Skeleton } from "@/components/ui/primitives";
import { WeaknessList } from "@/components/weakness-list";
import { useMastery, useTaxonomy, useWeaknesses } from "@/lib/queries";
import { MODES, type Mode } from "@/lib/types";
import { cn } from "@/lib/cn";

const MODE_LABEL: Record<Mode, string> = {
  coding: "Coding",
  quant: "Quant",
  design: "System design",
  behavioral: "Behavioral",
};

export default function Concepts() {
  const [mode, setMode] = useState<Mode | undefined>(undefined);
  const taxonomy = useTaxonomy();
  const mastery = useMastery();
  const weaknesses = useWeaknesses(mode, 100);

  const concepts =
    taxonomy.concepts.length && mastery.data
      ? toHeatmapConcepts(taxonomy.concepts, mastery.data.concepts)
      : [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-ink text-xl font-semibold tracking-tight">Concepts</h1>
        <p className="text-ink-muted mt-0.5 text-sm">
          The whole taxonomy, coloured by mastery. Click a concept for the evidence behind
          its number.
        </p>
      </div>

      {taxonomy.error ? <ApiErrorNotice error={taxonomy.error} /> : null}

      <Card>
        <CardHeader title="Mastery" />
        <CardBody>
          {taxonomy.isLoading || mastery.isLoading ? (
            <Skeleton className="h-64" />
          ) : (
            <MasteryHeatmap concepts={concepts} />
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Ranked by weakness"
          hint="The priority the planner draws from — expand a row for its five terms."
          action={
            <div className="flex gap-1">
              {[undefined, ...MODES].map((option) => (
                <button
                  key={option ?? "all"}
                  type="button"
                  onClick={() => setMode(option)}
                  aria-pressed={mode === option}
                  className={cn(
                    "rounded px-2 py-1 text-xs transition-colors",
                    mode === option
                      ? "bg-accent text-accent-ink"
                      : "text-ink-secondary hover:bg-sunken",
                  )}
                >
                  {option ? MODE_LABEL[option] : "All"}
                </button>
              ))}
            </div>
          }
        />
        <CardBody>
          {weaknesses.isLoading ? (
            <Skeleton className="h-48" />
          ) : weaknesses.data ? (
            <WeaknessList
              concepts={weaknesses.data.concepts}
              weights={weaknesses.data.weights}
            />
          ) : null}
        </CardBody>
      </Card>
    </div>
  );
}
