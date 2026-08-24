"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ApiErrorNotice } from "@/components/api-error";
import { ConceptPicker } from "@/components/concept-picker";
import { Badge, Button, Card, CardBody, CardHeader, Empty, Skeleton, Stat } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { percent, relativeDue, when } from "@/lib/format";
import { keys } from "@/lib/queries";

/** One logged problem: its tag, its solve history, and the evidence it produced. */
export default function PracticeProblemPage() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const problem = useQuery({ queryKey: ["practice-problem", id], queryFn: () => api.problem(id) });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["practice-problem", id] });
    queryClient.invalidateQueries({ queryKey: ["practice-problems"] });
    queryClient.invalidateQueries({ queryKey: keys.reviewQueue });
    queryClient.invalidateQueries({ queryKey: keys.mastery });
  };

  if (problem.isLoading) return <Skeleton className="h-96" />;
  if (problem.error) return <ApiErrorNotice error={problem.error} />;
  if (!problem.data) return null;

  const data = problem.data;
  const needsTag = data.status === "pending_classification";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-ink min-w-0 text-xl font-semibold tracking-tight">{data.title}</h1>
        {needsTag ? (
          <Badge tone="warning">needs a tag</Badge>
        ) : (
          <Badge tone={data.status === "retired" ? "good" : "accent"}>{data.status}</Badge>
        )}
        <Link
          href="/practice"
          className="text-ink-secondary ml-auto text-sm underline underline-offset-2"
        >
          All problems
        </Link>
      </div>

      <Card>
        <CardBody className="grid grid-cols-2 gap-6 pt-4 md:grid-cols-4">
          <Stat label="Solved" value={`${data.solve_count}×`} />
          <Stat
            label="Next review"
            value={data.due_at ? relativeDue(data.due_at) : "—"}
            note={needsTag ? "not scheduled until tagged" : undefined}
            tone={data.due_at ? "default" : "muted"}
          />
          <Stat
            label="Stability"
            value={data.stability_days ? `${data.stability_days.toFixed(1)}d` : "—"}
          />
          <Stat
            label="Source"
            value={data.source_site}
            note={data.difficulty_label ?? undefined}
          />
        </CardBody>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Classification problem={data} onSaved={invalidate} />
        <RecordSolve problemId={id} disabled={needsTag} onSaved={invalidate} />
      </div>

      <Card>
        <CardHeader title="Solve history" />
        <CardBody>
          {data.solves.length === 0 ? (
            <Empty title="No solves recorded" />
          ) : (
            <ul className="divide-hairline divide-y text-sm">
              {data.solves.map((solve) => (
                <li key={solve.review_number} className="flex flex-wrap items-baseline gap-2 py-2">
                  <span className="tabular text-ink-muted w-8 text-xs">
                    #{solve.review_number}
                  </span>
                  <Badge tone={solve.is_success ? "good" : "critical"}>
                    {solve.is_success ? "solved" : "missed"}
                  </Badge>
                  <span className="text-ink-secondary min-w-0 flex-1 truncate text-xs">
                    {solve.notes}
                  </span>
                  <span className="text-ink-muted text-xs">{when(solve.attempted_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Evidence written"
          hint="Immutable, and the same kind a graded session produces — this moves real mastery."
        />
        <CardBody>
          {data.evidence.length === 0 ? (
            <Empty
              title="None yet"
              detail="Nothing is claimed about your mastery until the concept is confirmed."
            />
          ) : (
            <ul className="divide-hairline divide-y text-sm">
              {data.evidence.map((row, index) => (
                <li key={index} className="flex flex-wrap items-baseline gap-2 py-2">
                  <Link
                    href={`/concepts/${row.concept_id}`}
                    className="min-w-0 flex-1 truncate font-mono text-xs hover:underline"
                  >
                    {row.concept_id}
                  </Link>
                  <span className="tabular text-xs">{percent(row.score)}</span>
                  <Badge>conf {row.confidence.toFixed(2)}</Badge>
                  <span className="text-ink-muted text-xs">{when(row.ts)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {data.notes ? (
        <Card>
          <CardHeader title="Your notes" />
          <CardBody>
            <p className="text-ink-secondary text-sm whitespace-pre-wrap">{data.notes}</p>
          </CardBody>
        </Card>
      ) : null}

      <p className="text-ink-muted text-xs">
        <a href={data.url} target="_blank" rel="noreferrer" className="underline">
          {data.url}
        </a>{" "}
        — a pointer, never fetched.
      </p>
    </div>
  );
}

function Classification({
  problem,
  onSaved,
}: {
  problem: { id: string; primary_concept_id: string | null; status: string; classification: { confidence: number | null; model: string | null } };
  onSaved: () => void;
}) {
  const [primary, setPrimary] = useState<string | null>(problem.primary_concept_id);
  const needsTag = problem.status === "pending_classification";

  const save = useMutation({
    mutationFn: () => api.setClassification(problem.id, primary!),
    onSuccess: onSaved,
  });

  return (
    <Card>
      <CardHeader
        title={needsTag ? "Which concept does this measure?" : "Concept"}
        hint={
          needsTag
            ? "Confirming this is what writes the evidence. Nothing counts until then."
            : "Already resolved — evidence is immutable, so this cannot be re-tagged."
        }
      />
      <CardBody className="space-y-3">
        {problem.classification.confidence !== null ? (
          <p className="text-ink-muted text-xs">
            The classifier proposed this at {percent(problem.classification.confidence)}{" "}
            confidence
            {problem.classification.model ? ` (${problem.classification.model})` : ""}. The
            gate is 0.75.
          </p>
        ) : (
          <p className="text-ink-muted text-xs">
            No classification was proposed — the provider was unreachable, which does not
            lose the entry. Naming it yourself costs a confirmation.
          </p>
        )}

        {needsTag ? (
          <>
            <ConceptPicker value={primary} onChange={setPrimary} id="primary-concept" />
            {save.error ? <ApiErrorNotice error={save.error} /> : null}
            <Button disabled={!primary || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? "Saving…" : "Confirm and count it"}
            </Button>
          </>
        ) : (
          <Link
            href={`/concepts/${problem.primary_concept_id}`}
            className="text-ink font-mono text-sm hover:underline"
          >
            {problem.primary_concept_id}
          </Link>
        )}
      </CardBody>
    </Card>
  );
}

function RecordSolve({
  problemId,
  disabled,
  onSaved,
}: {
  problemId: string;
  disabled: boolean;
  onSaved: () => void;
}) {
  const [notes, setNotes] = useState("");

  const record = useMutation({
    mutationFn: (isSuccess: boolean) => api.recordReview(problemId, isSuccess, notes),
    onSuccess: () => {
      setNotes("");
      onSaved();
    },
  });

  return (
    <Card>
      <CardHeader
        title="Record a re-solve"
        hint="A success stretches the interval; a miss shortens it without undoing the original solve."
      />
      <CardBody className="space-y-3">
        {disabled ? (
          <p className="text-ink-muted text-sm">
            Confirm the concept first — a problem with an unresolved tag is refused here,
            because the solve would have nowhere to write its evidence.
          </p>
        ) : (
          <>
            <textarea
              rows={3}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="How did it go this time?"
              aria-label="Re-solve notes"
              className="border-hairline bg-surface text-ink w-full resize-y rounded-md border px-2 py-1.5 text-sm"
            />
            {record.error ? <ApiErrorNotice error={record.error} /> : null}
            <div className="flex gap-2">
              <Button disabled={record.isPending} onClick={() => record.mutate(true)}>
                Solved it
              </Button>
              <Button
                variant="secondary"
                disabled={record.isPending}
                onClick={() => record.mutate(false)}
              >
                Missed it
              </Button>
            </div>
          </>
        )}
      </CardBody>
    </Card>
  );
}
