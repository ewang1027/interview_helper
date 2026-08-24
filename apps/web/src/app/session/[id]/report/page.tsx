"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ApiErrorNotice } from "@/components/api-error";
import { Badge, Card, CardBody, CardHeader, Empty, Skeleton, Stat } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { percent, when } from "@/lib/format";
import { keys } from "@/lib/queries";
import type { ItemOutcome } from "@/lib/types";

export default function Report() {
  const { id } = useParams<{ id: string }>();
  const report = useQuery({ queryKey: keys.report(id), queryFn: () => api.report(id) });

  if (report.isLoading) return <Skeleton className="h-96" />;
  if (report.error) {
    return (
      <div className="space-y-3">
        <ApiErrorNotice error={report.error} />
        <Link href={`/session/${id}`} className="text-ink-secondary text-sm underline">
          Back to the session
        </Link>
      </div>
    );
  }
  if (!report.data) return null;

  const data = report.data;
  // An evidence row per concept can come from more than one item.
  const byConcept = new Map<string, typeof data.evidence>();
  for (const row of data.evidence) {
    byConcept.set(row.concept_id, [...(byConcept.get(row.concept_id) ?? []), row]);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-ink text-xl font-semibold tracking-tight">Report</h1>
        <Badge tone={data.state === "complete" ? "good" : "warning"}>{data.state}</Badge>
        <span className="text-ink-muted text-sm">
          {data.mode} · {when(data.started_at)}
        </span>
        <Link
          href={`/session/${id}`}
          className="text-ink-secondary ml-auto text-sm underline underline-offset-2"
        >
          Back to the session
        </Link>
      </div>

      {/* Read off this session, not stated as a constant — the server builds
          these from what actually happened, so they are rendered verbatim. */}
      {data.notes.map((note) => (
        <p
          key={note}
          className="border-hairline text-ink-secondary rounded-md border border-dashed px-3 py-2 text-sm"
        >
          {note}
        </p>
      ))}

      <Card>
        <CardBody className="grid grid-cols-2 gap-6 pt-4 md:grid-cols-4">
          <Stat
            label="Mean score"
            value={data.mean_score === null ? "—" : percent(data.mean_score)}
            note={data.mean_score === null ? "nothing graded" : `over ${data.graded} graded`}
            tone={data.mean_score === null ? "muted" : "default"}
          />
          <Stat label="Graded" value={data.graded} />
          <Stat
            label="Failed"
            value={data.failed}
            note={data.failed ? "no evidence written for these" : undefined}
            tone={data.failed ? "default" : "muted"}
          />
          <Stat label="Not attempted" value={data.not_attempted} tone="muted" />
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Items" hint="What was submitted for each planned item, and how it scored." />
        <CardBody className="space-y-2">
          {data.items.map((item) => (
            <ItemRow key={item.item_id} item={item} />
          ))}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Evidence written"
          hint="Every row is immutable. Mastery is derived from these, never hand-written."
        />
        <CardBody>
          {byConcept.size === 0 ? (
            <Empty
              title="No evidence"
              detail="A failed grading writes none — a missing grade is visible, a wrong one corrupts mastery."
            />
          ) : (
            <ul className="divide-hairline divide-y">
              {[...byConcept.entries()].map(([conceptId, rows]) => (
                <li key={conceptId} className="flex flex-wrap items-baseline gap-2 py-2">
                  <Link
                    href={`/concepts/${conceptId}`}
                    className="text-ink min-w-0 flex-1 text-sm hover:underline"
                  >
                    {conceptId}
                  </Link>
                  {rows.map((row, index) => (
                    <span key={index} className="flex items-center gap-1.5">
                      <span className="tabular text-ink-secondary text-xs">
                        {percent(row.score)}
                      </span>
                      {/* Confidence is the load-bearing number: a hidden-test
                          pass and a model's read of a rubric are not the same
                          claim, and both scale the rating move. */}
                      <Badge tone={row.confidence >= 0.8 ? "good" : "neutral"}>
                        conf {row.confidence.toFixed(2)}
                      </Badge>
                      <span className="text-ink-muted text-xs">{row.grader_version}</span>
                    </span>
                  ))}
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function ItemRow({ item }: { item: ItemOutcome }) {
  const detail = item.detail as { criteria?: { name: string; score: number; note?: string }[] } | null;

  return (
    <details className="border-hairline rounded-md border px-3 py-2">
      <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-2">
        <span className="text-ink min-w-0 flex-1 text-sm">{item.title ?? item.item_id}</span>
        {item.status === "graded" ? (
          <Badge tone="good">{percent(item.score)}</Badge>
        ) : item.status === "failed" ? (
          <Badge tone="critical">failed</Badge>
        ) : (
          <Badge>{item.status.replace("_", " ")}</Badge>
        )}
      </summary>
      {detail?.criteria?.length ? (
        <ul className="mt-2 space-y-1">
          {detail.criteria.map((criterion) => (
            <li key={criterion.name} className="flex items-baseline gap-2 text-xs">
              <span className="text-ink-secondary min-w-0 flex-1">{criterion.name}</span>
              <span className="tabular text-ink-muted">{percent(criterion.score)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <pre className="text-ink-muted mt-2 max-h-48 overflow-auto text-[11px] whitespace-pre-wrap">
          {item.detail ? JSON.stringify(item.detail, null, 2) : "No detail recorded."}
        </pre>
      )}
    </details>
  );
}
