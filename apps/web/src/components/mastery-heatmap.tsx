"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { elo, relativeDue } from "@/lib/format";
import type { MasteryRow, RankedConcept } from "@/lib/types";

/**
 * The mastery heatmap — concepts as cells, grouped by domain.
 *
 * docs/WEB.md sets two rules for it, and both are structural here rather than
 * matters of taste:
 *
 * - **Ability is never on a red-to-green scale, and overdue is not a hue.**
 *   Weak and overdue are different states, so they use different channels:
 *   ability is a single-hue sequential ramp (validated for these surfaces —
 *   see globals.css), and overdue is a ring plus a corner wedge. A reader who
 *   cannot separate hues at all still sees which cells are due, because the
 *   wedge is a shape.
 * - **Evidence counts are shown, not just scores.** An ability of 0.4 from two
 *   observations is a different situation from 0.4 from thirty, and a heatmap
 *   that hides the denominator misleads. The count is printed in the cell.
 *
 * A concept that has never been measured is not a low score — it is drawn in a
 * neutral outside the ramp, so absence never reads as weakness.
 */

const DOMAIN_LABEL: Record<string, string> = {
  coding: "Coding",
  quant: "Quant",
  system_design: "System design",
  behavioral: "Behavioral",
};

/**
 * Cells are banded on **ability in Elo**, not on the server's
 * `normalized_ability`, and that is a legibility decision with a measurement
 * behind it. `normalized_ability` divides by the full rating scale — floor 600,
 * ceiling 2800 — so the 1550 every concept starts at normalises to 0.43, and a
 * concept moved a full 200 points by real evidence still lands between 0.34 and
 * 0.52. Banded on that scale in equal widths, sixteen measured concepts spanning
 * 1501 to 1560 all fell in one step and the heatmap came out a single colour.
 *
 * The cutoffs are centred on the 1550 start instead, and the legend prints them,
 * so what a shade means is inspectable rather than implied.
 */
const BANDS = [
  { max: 1425, cls: "bg-ability-1", label: "under 1425" },
  { max: 1500, cls: "bg-ability-2", label: "1425–1500" },
  { max: 1600, cls: "bg-ability-3", label: "1500–1600" },
  { max: 1675, cls: "bg-ability-4", label: "1600–1675" },
  { max: Infinity, cls: "bg-ability-5", label: "1675 and up" },
] as const;

/** The lower two ramp steps are light; ink on them has to be dark to stay legible. */
function bandFor(ability: number) {
  return BANDS.find((band) => ability < band.max) ?? BANDS[BANDS.length - 1];
}

export interface HeatmapConcept {
  concept_id: string;
  name: string;
  domain: string;
  observations: number;
  /** 0–1, or null when the concept has never been measured. */
  normalized: number | null;
  ability: number;
  due_at: string | null;
  calibrating: boolean;
}

/** Join the ranked taxonomy to whatever mastery rows exist for it. */
export function toHeatmapConcepts(
  taxonomy: RankedConcept[],
  mastery: MasteryRow[],
): HeatmapConcept[] {
  const measured = new Map(mastery.map((row) => [row.concept_id, row]));
  return taxonomy.map((concept) => {
    const row = measured.get(concept.concept_id);
    return {
      concept_id: concept.concept_id,
      name: concept.name,
      domain: concept.domain,
      observations: row?.observations ?? concept.observations,
      normalized: row ? row.normalized_ability : null,
      ability: row?.ability ?? concept.ability,
      due_at: row?.due_at ?? null,
      calibrating: row ? row.calibrating : concept.calibrating,
    };
  });
}

function isOverdue(due: string | null): boolean {
  return due !== null && new Date(due).getTime() <= Date.now();
}

function Cell({ concept }: { concept: HeatmapConcept }) {
  const overdue = isOverdue(concept.due_at);
  const unmeasured = concept.normalized === null;
  const band = unmeasured ? null : bandFor(concept.ability);
  // Ink has to survive both ends of the ramp: the two lightest steps are pale
  // in light mode, and the two darkest are near-black in dark mode.
  const darkInk = unmeasured || BANDS.indexOf(band!) < 2;

  return (
    <Link
      href={`/concepts/${concept.concept_id}`}
      title={[
        concept.name,
        unmeasured ? "never measured" : `ability ${elo(concept.ability)}`,
        `${concept.observations} observation${concept.observations === 1 ? "" : "s"}`,
        concept.due_at ? relativeDue(concept.due_at) : "not scheduled",
        concept.calibrating && !unmeasured ? "still calibrating" : null,
      ]
        .filter(Boolean)
        .join(" · ")}
      className={cn(
        "group relative flex h-11 flex-col justify-between overflow-hidden rounded p-1 transition-transform hover:z-10 hover:scale-105",
        unmeasured ? "bg-ability-none border-hairline border border-dashed" : band!.cls,
        overdue && "ring-2 ring-[var(--status-critical)]",
      )}
    >
      {/* The overdue wedge. A shape, so the state survives any colour vision. */}
      {overdue ? (
        <span
          aria-hidden
          className="absolute top-0 right-0 h-0 w-0 border-t-[9px] border-l-[9px] border-t-[var(--status-critical)] border-l-transparent"
        />
      ) : null}
      <span
        className={cn(
          "truncate text-[10px] leading-tight font-medium",
          darkInk ? "text-[#0b0b0b]" : "text-white",
        )}
      >
        {concept.concept_id}
      </span>
      <span
        className={cn(
          "tabular text-[10px] leading-none",
          darkInk ? "text-[#0b0b0b]/70" : "text-white/80",
        )}
      >
        {concept.observations}
      </span>
    </Link>
  );
}

export function MasteryHeatmap({ concepts }: { concepts: HeatmapConcept[] }) {
  const [asTable, setAsTable] = useState(false);

  const groups = useMemo(() => {
    const byDomain = new Map<string, HeatmapConcept[]>();
    for (const concept of concepts) {
      const list = byDomain.get(concept.domain) ?? [];
      list.push(concept);
      byDomain.set(concept.domain, list);
    }
    // Measured first within a domain, then weakest first — the cells worth
    // looking at should not be scattered among 140 that have never been seen.
    for (const list of byDomain.values()) {
      list.sort((a, b) => {
        if ((a.normalized === null) !== (b.normalized === null)) return a.normalized === null ? 1 : -1;
        return (a.normalized ?? 0) - (b.normalized ?? 0);
      });
    }
    return [...byDomain.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [concepts]);

  const measured = concepts.filter((concept) => concept.normalized !== null).length;
  const overdue = concepts.filter((concept) => isOverdue(concept.due_at)).length;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <Legend />
        <button
          type="button"
          onClick={() => setAsTable((value) => !value)}
          className="text-ink-secondary hover:text-ink text-xs underline underline-offset-2"
        >
          {asTable ? "Show heatmap" : "Show as table"}
        </button>
      </div>

      {asTable ? (
        <Table concepts={concepts} />
      ) : (
        <div className="space-y-4">
          {groups.map(([domain, list]) => (
            <section key={domain}>
              <h3 className="text-ink-secondary mb-1.5 text-xs font-semibold">
                {DOMAIN_LABEL[domain] ?? domain}
                <span className="text-ink-muted ml-2 font-normal">
                  {list.filter((c) => c.normalized !== null).length} of {list.length} measured
                </span>
              </h3>
              <div className="grid grid-cols-[repeat(auto-fill,minmax(84px,1fr))] gap-1">
                {list.map((concept) => (
                  <Cell key={concept.concept_id} concept={concept} />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      <p className="text-ink-muted mt-3 text-xs">
        {measured} of {concepts.length} concepts measured
        {overdue > 0 ? ` · ${overdue} overdue` : ""}. A cell shows its concept id and how many
        observations stand behind it.
      </p>
    </div>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="flex items-center gap-1.5">
        <span className="text-ink-muted text-xs">ability</span>
        {BANDS.map((band) => (
          <span
            key={band.label}
            title={`${band.label} Elo`}
            className={cn("h-3 w-5 rounded-[2px]", band.cls)}
          />
        ))}
        <span className="text-ink-muted text-xs">&lt;1425 → 1675+ Elo</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="bg-ability-none border-hairline h-3 w-5 rounded-[2px] border border-dashed" />
        <span className="text-ink-muted text-xs">never measured</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="relative inline-block h-3 w-5 rounded-[2px] ring-2 ring-[var(--status-critical)]">
          <span
            aria-hidden
            className="absolute top-0 right-0 h-0 w-0 border-t-[6px] border-l-[6px] border-t-[var(--status-critical)] border-l-transparent"
          />
        </span>
        <span className="text-ink-muted text-xs">overdue</span>
      </div>
    </div>
  );
}

function Table({ concepts }: { concepts: HeatmapConcept[] }) {
  const rows = [...concepts].sort((a, b) => {
    if ((a.normalized === null) !== (b.normalized === null)) return a.normalized === null ? 1 : -1;
    return (a.normalized ?? 0) - (b.normalized ?? 0);
  });

  return (
    <div className="border-hairline max-h-96 overflow-auto rounded border">
      <table className="w-full text-left text-xs">
        <thead className="bg-sunken text-ink-secondary sticky top-0">
          <tr>
            <th className="px-2 py-1.5 font-medium">Concept</th>
            <th className="px-2 py-1.5 font-medium">Domain</th>
            <th className="px-2 py-1.5 text-right font-medium">Ability</th>
            <th className="px-2 py-1.5 text-right font-medium">Observations</th>
            <th className="px-2 py-1.5 font-medium">Due</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((concept) => (
            <tr key={concept.concept_id} className="border-hairline border-t">
              <td className="px-2 py-1.5">
                <Link href={`/concepts/${concept.concept_id}`} className="hover:underline">
                  {concept.name}
                </Link>
              </td>
              <td className="text-ink-muted px-2 py-1.5">
                {DOMAIN_LABEL[concept.domain] ?? concept.domain}
              </td>
              <td className="tabular px-2 py-1.5 text-right">
                {concept.normalized === null ? "—" : elo(concept.ability)}
              </td>
              <td className="tabular px-2 py-1.5 text-right">{concept.observations}</td>
              <td className="text-ink-muted px-2 py-1.5">
                {concept.due_at ? relativeDue(concept.due_at) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
