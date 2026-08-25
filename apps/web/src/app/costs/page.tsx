"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApiErrorNotice } from "@/components/api-error";
import { Badge, Card, CardBody, CardHeader, Empty, Stat } from "@/components/ui/primitives";
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
          <CardHeader
            title="Budget remaining"
            hint="Hard ceilings. A breach is refused with a 429, never downgraded to a cheaper model."
          />
          <CardBody className="space-y-4">
            <div className="space-y-3">
              <div className="text-ink-muted text-xs font-medium tracking-wide uppercase">
                Dollars — checked first
              </div>
              <BudgetBar
                label="This month"
                spent={budget.data.month.spent_usd}
                limit={budget.data.month.limit_usd}
                money
              />
              <BudgetBar
                label="Today"
                spent={budget.data.day.spent_usd}
                limit={budget.data.day.limit_usd}
                money
              />
              <BudgetBar
                label="Per session"
                spent={budget.data.session.spent_usd}
                limit={budget.data.session.limit_usd}
                money
              />
            </div>
            <div className="border-hairline space-y-3 border-t pt-3">
              <div className="text-ink-muted text-xs font-medium tracking-wide uppercase">
                Tokens
              </div>
              <BudgetBar label="Today" spent={budget.data.day.spent} limit={budget.data.day.limit} />
              <BudgetBar
                label="Per session"
                spent={budget.data.session.spent}
                limit={budget.data.session.limit}
              />
            </div>
            <p className="text-ink-muted text-xs">
              Both are enforced; the dollar ones are checked first, because a token limit
              stopped being a proxy for money once the routing table held more than one
              model. An in-flight call counts against these at its reservation, so two
              concurrent calls cannot each read the other&apos;s spend as zero.
            </p>
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

function BudgetBar({
  label,
  spent,
  limit,
  money = false,
}: {
  label: string;
  spent: number;
  limit: number;
  money?: boolean;
}) {
  const fraction = limit === 0 ? 0 : Math.min(1, spent / limit);
  const near = fraction >= 0.8;
  // One hue for magnitude. The near-ceiling state is carried by a label, not by
  // switching the bar to a status colour — the bar is still showing magnitude, and
  // recolouring it would make two different things share one channel.
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-xs">
        <span className="text-ink-secondary">{label}</span>
        <span className="flex items-baseline gap-2">
          {near ? <Badge tone="warning">near the ceiling</Badge> : null}
          <span className="tabular text-ink-muted">
            {money
              ? `${usd(spent)} / ${usd(limit)}`
              : `${compactNumber(spent)} / ${compactNumber(limit)} tokens`}
          </span>
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
