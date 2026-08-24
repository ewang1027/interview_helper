"use client";

import Link from "next/link";
import { MasteryHeatmap, toHeatmapConcepts } from "@/components/mastery-heatmap";
import { Badge, Card, CardBody, CardHeader, Empty, Skeleton, Stat } from "@/components/ui/primitives";
import { WeaknessList } from "@/components/weakness-list";
import { compactNumber, relativeDue, usd, when } from "@/lib/format";
import {
  useCorpusStatus,
  useCosts,
  useMastery,
  useReviewQueue,
  useSessions,
  useTaxonomy,
  useWeaknesses,
} from "@/lib/queries";

export default function Dashboard() {
  const mastery = useMastery();
  const taxonomy = useTaxonomy();
  const corpus = useCorpusStatus();
  const costs = useCosts(7);
  const queue = useReviewQueue();
  const sessions = useSessions();
  const weaknesses = useWeaknesses(undefined, 8);

  const concepts =
    taxonomy.concepts.length && mastery.data
      ? toHeatmapConcepts(taxonomy.concepts, mastery.data.concepts)
      : [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-ink text-xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-ink-muted mt-0.5 text-sm">
            What the engine believes, and the evidence behind it.
          </p>
        </div>
        <Link
          href="/session/new"
          className="bg-accent text-accent-ink inline-flex h-9 items-center rounded-md px-4 text-sm font-medium hover:opacity-90"
        >
          Start a session
        </Link>
      </div>

      <Card>
        <CardBody className="grid grid-cols-2 gap-6 pt-4 md:grid-cols-4">
          <Stat
            label="Concepts measured"
            value={mastery.isLoading ? "—" : mastery.data?.measured ?? 0}
            note={
              corpus.data
                ? `of ${corpus.data.concepts} in the taxonomy`
                : "of the taxonomy"
            }
            tone={mastery.data?.measured ? "default" : "muted"}
          />
          <Stat
            label="Still calibrating"
            value={mastery.isLoading ? "—" : mastery.data?.calibrating ?? 0}
            note="too few observations to trust"
          />
          <Stat
            label="Corpus"
            value={corpus.isLoading ? "—" : corpus.data?.items ?? 0}
            note={
              corpus.data
                ? `${corpus.data.archetypes} archetypes · ${corpus.data.instances} instances`
                : undefined
            }
          />
          <Stat
            label="Spend, 7 days"
            value={costs.isLoading ? "—" : usd(costs.data?.cost_usd ?? 0)}
            note={
              costs.data
                ? `${costs.data.calls} calls · ${compactNumber(
                    costs.data.input_tokens + costs.data.output_tokens,
                  )} tokens`
                : undefined
            }
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Mastery"
          hint="Ability per concept, grouped by domain. Overdue is a ring and a wedge, never a hue."
        />
        <CardBody>
          {mastery.isLoading || taxonomy.isLoading ? (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(84px,1fr))] gap-1">
              {Array.from({ length: 24 }).map((_, index) => (
                <Skeleton key={index} className="h-11" />
              ))}
            </div>
          ) : concepts.length === 0 ? (
            <Empty
              title="No concepts to show"
              detail="The taxonomy could not be loaded from the weakness ranking."
            />
          ) : (
            <MasteryHeatmap concepts={concepts} />
          )}
        </CardBody>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Weakest concepts"
            hint="Ranked by priority. Expand a row for the five terms behind it."
          />
          <CardBody>
            {weaknesses.isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, index) => (
                  <Skeleton key={index} className="h-6" />
                ))}
              </div>
            ) : weaknesses.data?.concepts.length ? (
              <WeaknessList
                concepts={weaknesses.data.concepts}
                weights={weaknesses.data.weights}
              />
            ) : (
              <Empty title="Nothing ranked yet" />
            )}
          </CardBody>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Due for review"
              hint="Problems logged elsewhere, scheduled back by the practice log."
              action={
                <Link href="/practice" className="text-ink-secondary text-xs hover:underline">
                  All
                </Link>
              }
            />
            <CardBody>
              {queue.isLoading ? (
                <Skeleton className="h-16" />
              ) : queue.data?.due.length ? (
                <ul className="divide-hairline divide-y text-sm">
                  {queue.data.due.slice(0, 6).map((entry) => (
                    <li key={entry.id} className="flex items-baseline gap-2 py-1.5">
                      <Link
                        href={`/practice/${entry.id}`}
                        className="min-w-0 flex-1 truncate hover:underline"
                      >
                        {entry.title}
                      </Link>
                      <Badge tone={entry.days_overdue > 0 ? "critical" : "neutral"}>
                        {relativeDue(entry.due_at)}
                      </Badge>
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty
                  title="Nothing due"
                  detail={
                    <>
                      Nothing scheduled to re-solve.{" "}
                      <Link href="/practice" className="underline">
                        Log a problem you solved elsewhere
                      </Link>
                      .
                    </>
                  }
                />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Recent sessions"
              action={
                <Link href="/history" className="text-ink-secondary text-xs hover:underline">
                  All
                </Link>
              }
            />
            <CardBody>
              {sessions.isLoading ? (
                <Skeleton className="h-16" />
              ) : sessions.data?.sessions.length ? (
                <ul className="divide-hairline divide-y text-sm">
                  {sessions.data.sessions.slice(0, 6).map((session) => (
                    <li key={session.id} className="flex items-baseline gap-2 py-1.5">
                      <Link
                        href={`/session/${session.id}`}
                        className="min-w-0 flex-1 truncate hover:underline"
                      >
                        {session.mode}
                      </Link>
                      <span className="text-ink-muted text-xs">{when(session.started_at)}</span>
                      <Badge
                        tone={
                          session.state === "complete"
                            ? "good"
                            : session.state === "failed"
                              ? "critical"
                              : "neutral"
                        }
                      >
                        {session.state}
                      </Badge>
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty title="No sessions yet" detail="Start one to produce some evidence." />
              )}
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}
