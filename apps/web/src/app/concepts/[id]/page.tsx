"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ApiErrorNotice } from "@/components/api-error";
import { Badge, Card, CardBody, CardHeader, Empty, Skeleton, Stat } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { elo, percent, relativeDue, when } from "@/lib/format";
import { keys } from "@/lib/queries";

/**
 * One concept, and the evidence behind its number.
 *
 * docs/API.md calls this the feature that makes the adaptive engine auditable:
 * every number here traces to graded artifacts you can re-read. So the evidence
 * table is the page, and the ability is the summary of it — not the other way
 * round.
 */
export default function ConceptDetail() {
  const { id } = useParams<{ id: string }>();
  const concept = useQuery({ queryKey: keys.concept(id), queryFn: () => api.concept(id) });

  if (concept.isLoading) return <Skeleton className="h-96" />;
  if (concept.error) return <ApiErrorNotice error={concept.error} />;
  if (!concept.data) return null;

  const { mastery, evidence } = concept.data;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-ink font-mono text-xl font-semibold tracking-tight">{id}</h1>
        {mastery?.calibrating ? <Badge tone="warning">calibrating</Badge> : null}
        <Link
          href="/concepts"
          className="text-ink-secondary ml-auto text-sm underline underline-offset-2"
        >
          All concepts
        </Link>
      </div>

      <Card>
        <CardBody className="grid grid-cols-2 gap-6 pt-4 md:grid-cols-4">
          <Stat
            label="Ability"
            value={mastery ? elo(mastery.ability) : "—"}
            note={mastery ? "Elo, against item difficulty" : "never measured"}
            tone={mastery ? "default" : "muted"}
          />
          <Stat
            label="Observations"
            value={mastery?.observations ?? 0}
            note={mastery?.calibrating ? "too few to trust yet" : undefined}
          />
          <Stat
            label="Stability"
            value={mastery?.stability_days ? `${mastery.stability_days.toFixed(1)}d` : "—"}
            note="FSRS, fuzzing off"
          />
          <Stat
            label="Due"
            value={mastery?.due_at ? relativeDue(mastery.due_at) : "—"}
            note={mastery?.last_seen ? `last seen ${when(mastery.last_seen)}` : undefined}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Evidence"
          hint="Immutable rows. The ability above is derived from exactly these, and can be rebuilt from them."
        />
        <CardBody>
          {evidence.length === 0 ? (
            <Empty
              title="No evidence yet"
              detail="Nothing has been graded against this concept, so nothing is claimed about it."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-ink-secondary border-hairline border-b">
                  <tr>
                    <th className="py-1.5 pr-3 font-medium">When</th>
                    <th className="py-1.5 pr-3 font-medium">Source</th>
                    <th className="py-1.5 pr-3 text-right font-medium">Score</th>
                    <th className="py-1.5 pr-3 text-right font-medium">Confidence</th>
                    <th className="py-1.5 pr-3 font-medium">Grader</th>
                    <th className="py-1.5 font-medium">From</th>
                  </tr>
                </thead>
                <tbody>
                  {evidence.map((row) => (
                    <tr key={row.id} className="border-hairline border-b last:border-0">
                      <td className="text-ink-muted py-1.5 pr-3 whitespace-nowrap">
                        {when(row.ts)}
                      </td>
                      <td className="py-1.5 pr-3">{row.source.replace(/_/g, " ")}</td>
                      <td className="tabular py-1.5 pr-3 text-right">{percent(row.score)}</td>
                      <td className="tabular text-ink-muted py-1.5 pr-3 text-right">
                        {row.confidence.toFixed(2)}
                      </td>
                      <td className="text-ink-muted py-1.5 pr-3 font-mono">
                        {row.grader_version}
                      </td>
                      <td className="py-1.5">
                        {row.session_id ? (
                          <Link
                            href={`/session/${row.session_id}/report`}
                            className="hover:underline"
                          >
                            session
                          </Link>
                        ) : row.practice_problem_id ? (
                          <span className="text-ink-muted">practice log</span>
                        ) : (
                          <span className="text-ink-muted">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
