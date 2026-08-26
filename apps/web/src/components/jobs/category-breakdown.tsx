"use client";

import { Empty } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";
import { percent, titleCase } from "@/lib/format";
import type { JobCategory, JobStats } from "@/lib/types";

/**
 * Where the applications went, by category — and how each one is doing.
 *
 * Unlike the funnel next door this palette is **categorical**: four fixed hues
 * encoding *identity*, assigned per category and never cycled or reordered, so
 * filtering one out cannot repaint the others. The four were validated rather
 * than picked (docs/JOBS.md): worst adjacent CVD ΔE 9.1 light / 8.4 dark.
 *
 * Two of the light-mode hues sit below 3:1 against the page, so **every mark
 * here carries a visible label** — the category name and both numbers are text,
 * and the colour only reinforces them. That is the relief rule, and it is also
 * why there is no separate legend box: at four series, direct labels are the
 * better of the two options.
 *
 * The response rate is shown beside the total because the totals alone answer
 * the wrong question. Applying to thirty of something and hearing back from none
 * of it is the finding, and a bar chart of raw counts hides it completely.
 */

export const CATEGORY_COLOR: Record<JobCategory, string> = {
  swe: "var(--series-swe)",
  ai: "var(--series-ai)",
  quant: "var(--series-quant)",
  other: "var(--series-other)",
};

export const CATEGORY_LABEL: Record<JobCategory, string> = {
  swe: "Software",
  ai: "AI / ML",
  quant: "Quant",
  other: "Other",
};

const ORDER: JobCategory[] = ["swe", "ai", "quant", "other"];

export function CategoryDot({ category, className }: { category: JobCategory; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2 shrink-0 rounded-full", className)}
      style={{ background: CATEGORY_COLOR[category] }}
    />
  );
}

export function CategoryBreakdown({ stats }: { stats: JobStats }) {
  const rows = ORDER.filter((category) => stats.by_category[category]);
  if (!rows.length) {
    return <Empty title="Nothing tagged yet" detail="Categories appear once applications are tagged." />;
  }
  const widest = Math.max(...rows.map((category) => stats.by_category[category]!.total));

  return (
    <div className="space-y-3">
      {rows.map((category) => {
        const row = stats.by_category[category]!;
        const subs = Object.entries(row.subcategories).slice(0, 4);
        return (
          <div key={category}>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-ink flex items-center gap-2 text-sm font-medium">
                <CategoryDot category={category} />
                {CATEGORY_LABEL[category]}
              </span>
              <span className="text-ink-muted text-xs tabular-nums">
                {percent(row.total ? row.responded / row.total : 0)} heard back
                {row.offers > 0 ? ` · ${row.offers} offer${row.offers > 1 ? "s" : ""}` : null}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-3">
              <div className="bg-sunken h-5 min-w-0 flex-1 overflow-hidden rounded">
                <div
                  className="h-full rounded transition-[width] duration-300"
                  style={{
                    width: `${widest ? Math.max((row.total / widest) * 100, 2) : 0}%`,
                    background: CATEGORY_COLOR[category],
                  }}
                />
              </div>
              <span className="text-ink w-10 shrink-0 text-right text-sm font-semibold tabular-nums">
                {row.total}
              </span>
            </div>
            {subs.length ? (
              <p className="text-ink-muted mt-1 text-xs">
                {subs.map(([name, count]) => `${titleCase(name)} ${count}`).join(" · ")}
                {Object.keys(row.subcategories).length > subs.length ? " · …" : null}
              </p>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
