"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiErrorNotice } from "@/components/api-error";
import { PlanPreview } from "@/components/plan-preview";
import { Button, Card, CardBody, CardHeader, Skeleton } from "@/components/ui/primitives";
import { api, idempotencyKey } from "@/lib/api";
import { cn } from "@/lib/cn";
import { keys } from "@/lib/queries";
import { MODES, type Mode } from "@/lib/types";

const BUDGETS = [15, 30, 45, 60, 90] as const;

const MODE_LABEL: Record<Mode, string> = {
  coding: "Coding",
  quant: "Quant",
  design: "System design",
  behavioral: "Behavioral",
};

export default function NewSession() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("coding");
  const [budget, setBudget] = useState<number>(45);
  const [bias, setBias] = useState(0);

  const plan = useQuery({
    queryKey: keys.plan(mode, budget),
    queryFn: () => api.planNext(mode, budget),
  });

  const create = useMutation({
    mutationFn: () =>
      api.createSession(
        { mode, budget_minutes: budget, focus_concepts: [], difficulty_bias: bias },
        idempotencyKey(),
      ),
    onSuccess: (session) => router.push(`/session/${session.id}`),
  });

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-ink text-xl font-semibold tracking-tight">New session</h1>
        <p className="text-ink-muted mt-0.5 text-sm">
          The plan is shown before you commit to it — adaptation you cannot inspect is
          adaptation you cannot trust.
        </p>
      </div>

      <Card>
        <CardBody className="space-y-5 pt-4">
          <Field label="Mode">
            <div className="flex flex-wrap gap-2">
              {MODES.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setMode(option)}
                  aria-pressed={mode === option}
                  className={cn(
                    "rounded-md border px-3 py-1.5 text-sm transition-colors",
                    mode === option
                      ? "border-transparent bg-[var(--accent)] text-[var(--accent-ink)]"
                      : "border-hairline text-ink-secondary hover:border-axis hover:text-ink",
                  )}
                >
                  {MODE_LABEL[option]}
                </button>
              ))}
            </div>
          </Field>

          <Field label="Budget">
            <div className="flex flex-wrap gap-2">
              {BUDGETS.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setBudget(option)}
                  aria-pressed={budget === option}
                  className={cn(
                    "tabular rounded-md border px-3 py-1.5 text-sm transition-colors",
                    budget === option
                      ? "border-transparent bg-[var(--accent)] text-[var(--accent-ink)]"
                      : "border-hairline text-ink-secondary hover:border-axis hover:text-ink",
                  )}
                >
                  {option} min
                </button>
              ))}
            </div>
          </Field>

          <Field
            label="Difficulty bias"
            hint="Advisory — shifts the informative band the planner aims for."
          >
            <div className="flex items-center gap-3">
              <span className="text-ink-muted text-xs">easier</span>
              <input
                type="range"
                min={-1}
                max={1}
                step={0.5}
                value={bias}
                onChange={(event) => setBias(Number(event.target.value))}
                className="accent-[var(--accent)]"
                aria-label="Difficulty bias"
              />
              <span className="text-ink-muted text-xs">harder</span>
              <span className="tabular text-ink-secondary text-xs">{bias.toFixed(1)}</span>
            </div>
            {bias !== 0 ? (
              // Honest about a real limitation rather than showing a preview that
              // silently disagrees with what the button will produce.
              <p className="text-ink-muted mt-1.5 text-xs">
                The preview below does not include this: <code>GET /plan/next</code> takes a
                mode and a budget only, so the bias is applied when the session is created.
              </p>
            ) : null}
          </Field>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="The plan" hint={`${MODE_LABEL[mode]} · ${budget} minutes`} />
        <CardBody>
          {plan.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-6 w-64" />
              <Skeleton className="h-16" />
              <Skeleton className="h-16" />
            </div>
          ) : plan.error ? (
            <ApiErrorNotice error={plan.error} />
          ) : plan.data ? (
            <PlanPreview plan={plan.data} />
          ) : null}
        </CardBody>
      </Card>

      {create.error ? <ApiErrorNotice error={create.error} /> : null}

      <div className="flex items-center gap-3">
        <Button
          size="lg"
          disabled={create.isPending || plan.isLoading || !plan.data?.items.length}
          onClick={() => create.mutate()}
        >
          {create.isPending ? "Starting…" : "Start this session"}
        </Button>
        {!plan.isLoading && !plan.data?.items.length ? (
          <span className="text-ink-muted text-sm">Nothing to serve in this mode.</span>
        ) : null}
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5">
        <span className="text-ink text-sm font-medium">{label}</span>
        {hint ? <span className="text-ink-muted ml-2 text-xs">{hint}</span> : null}
      </div>
      {children}
    </div>
  );
}
