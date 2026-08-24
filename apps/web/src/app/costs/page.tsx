"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApiErrorNotice } from "@/components/api-error";
import { Card, CardBody, CardHeader, Empty, Stat } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { compactNumber, usd, when } from "@/lib/format";
import { keys } from "@/lib/queries";

const RANGES = [1, 7, 30, 90] as const;

export default function Costs() {
  const [days, setDays] = useState<number>(7);
  const costs = useQuery({ queryKey: keys.costs(days), queryFn: () => api.costs(days) });
  const budget = useQuery({ queryKey: keys.budget(), queryFn: () => api.budget() });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-ink text-xl font-semibold tracking-tight">Costs</h1>
          <p className="text-ink-muted mt-0.5 text-sm">
            From the <code>llm_calls</code> ledger. A budget is a refusal, never a
            downgrade to a cheaper model.
          </p>
        </div>
        <div className="flex gap-1">
          {RANGES.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setDays(option)}
              aria-pressed={days === option}
              className={cn(
                "tabular rounded px-2 py-1 text-xs transition-colors",
                days === option ? "bg-accent text-accent-ink" : "text-ink-secondary hover:bg-sunken",
              )}
            >
              {option}d
            </button>
          ))}
        </div>
      </div>

      {costs.error ? <ApiErrorNotice error={costs.error} /> : null}

      <Card>
        <CardBody className="grid grid-cols-2 gap-6 pt-4 md:grid-cols-4">
          <Stat
            label="Spend"
            value={costs.isLoading ? "—" : usd(costs.data?.cost_usd ?? 0)}
            note={costs.data ? `since ${when(costs.data.since)}` : undefined}
          />
          <Stat label="Calls" value={costs.isLoading ? "—" : (costs.data?.calls ?? 0)} />
          <Stat
            label="Input tokens"
            value={costs.isLoading ? "—" : compactNumber(costs.data?.input_tokens ?? 0)}
            note={
              costs.data?.cache_read_tokens
                ? `${compactNumber(costs.data.cache_read_tokens)} from cache`
                : undefined
            }
          />
          <Stat
            label="Output tokens"
            value={costs.isLoading ? "—" : compactNumber(costs.data?.output_tokens ?? 0)}
          />
        </CardBody>
      </Card>

      {budget.data ? (
        <Card>
          <CardHeader title="Budget remaining" hint="Hard ceilings from docs/COST.md." />
          <CardBody className="space-y-3">
            <BudgetBar
              label="Today"
              spent={budget.data.day.spent}
              limit={budget.data.day.limit}
            />
            <BudgetBar
              label="Per session"
              spent={budget.data.session.spent}
              limit={budget.data.session.limit}
            />
          </CardBody>
        </Card>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="By job" hint="What is expensive to do." />
          <CardBody>
            <Rollup rows={costs.data?.by_job.map((r) => ({ key: r.job, ...r })) ?? []} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="By model" hint="What the routing table is actually costing." />
          <CardBody>
            <Rollup rows={costs.data?.by_model.map((r) => ({ key: r.model, ...r })) ?? []} />
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function BudgetBar({ label, spent, limit }: { label: string; spent: number; limit: number }) {
  const fraction = limit === 0 ? 0 : Math.min(1, spent / limit);
  // One hue for magnitude; the warning state is carried by the label, not by
  // switching the bar to a status colour.
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-ink-secondary">{label}</span>
        <span className="tabular text-ink-muted">
          {compactNumber(spent)} / {compactNumber(limit)} tokens
        </span>
      </div>
      <div className="bg-sunken h-2 overflow-hidden rounded">
        <div className="bg-ability-4 h-full rounded" style={{ width: `${fraction * 100}%` }} />
      </div>
    </div>
  );
}

function Rollup({ rows }: { rows: { key: string; calls: number; cost_usd: number }[] }) {
  if (!rows.length) return <Empty title="Nothing on the ledger for this range" />;
  const max = Math.max(...rows.map((row) => row.cost_usd), 0.0001);

  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li key={row.key}>
          <div className="mb-1 flex items-baseline justify-between gap-2 text-xs">
            <span className="text-ink-secondary min-w-0 truncate font-mono">{row.key}</span>
            <span className="tabular text-ink-muted shrink-0">
              {usd(row.cost_usd)} · {row.calls} calls
            </span>
          </div>
          <div className="bg-sunken h-2 overflow-hidden rounded">
            <div
              className="bg-ability-3 h-full rounded"
              style={{ width: `${(row.cost_usd / max) * 100}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
