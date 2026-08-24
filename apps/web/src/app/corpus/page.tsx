"use client";

import { useQuery } from "@tanstack/react-query";
import { ApiErrorNotice } from "@/components/api-error";
import { Card, CardBody, CardHeader, Skeleton, Stat } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { keys } from "@/lib/queries";

const DOMAIN_LABEL: Record<string, string> = {
  coding: "Coding",
  quant: "Quant",
  system_design: "System design",
  behavioral: "Behavioral",
};

/**
 * What is in the corpus.
 *
 * docs/WEB.md specifies a browser here — "statements of unseen items stay
 * redacted". That needs `GET /corpus/items/{id}`, and an endpoint listing item
 * ids to reach it with; docs/API.md specifies the first and neither is built.
 * So this shows what `GET /corpus/status` actually reports and says plainly
 * what is missing, rather than rendering an empty browser that looks broken.
 */
export default function Corpus() {
  const status = useQuery({ queryKey: keys.corpus, queryFn: api.corpusStatus });

  if (status.error) return <ApiErrorNotice error={status.error} />;

  const data = status.data;
  const domains = Object.entries(data?.concepts_by_domain ?? {});
  const maxConcepts = Math.max(...domains.map(([, count]) => count), 1);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-ink text-xl font-semibold tracking-tight">Corpus</h1>
        <p className="text-ink-muted mt-0.5 text-sm">
          Authored at build time and committed as versioned JSON, so sessions are
          reproducible and graders are deterministic.
        </p>
      </div>

      <Card>
        <CardBody className="grid grid-cols-2 gap-6 pt-4 md:grid-cols-4">
          <Stat label="Items" value={status.isLoading ? "—" : (data?.items ?? 0)} />
          <Stat
            label="Archetypes"
            value={status.isLoading ? "—" : (data?.archetypes ?? 0)}
            note="a question shape"
          />
          <Stat
            label="Instances"
            value={status.isLoading ? "—" : (data?.instances ?? 0)}
            note="a concrete statement of one"
          />
          <Stat label="Concepts" value={status.isLoading ? "—" : (data?.concepts ?? 0)} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Concepts by domain" />
        <CardBody>
          {status.isLoading ? (
            <Skeleton className="h-32" />
          ) : (
            <ul className="space-y-2">
              {domains.map(([domain, count]) => (
                <li key={domain}>
                  <div className="mb-1 flex items-baseline justify-between text-xs">
                    <span className="text-ink-secondary">{DOMAIN_LABEL[domain] ?? domain}</span>
                    <span className="tabular text-ink-muted">{count}</span>
                  </div>
                  <div className="bg-sunken h-2 overflow-hidden rounded">
                    <div
                      className="bg-ability-3 h-full rounded"
                      style={{ width: `${(count / maxConcepts) * 100}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Browsing items is not built" />
        <CardBody>
          <p className="text-ink-secondary text-sm">
            Reading an item you have not been served defeats the measurement, so
            docs/API.md specifies <code>GET /corpus/items/&#123;id&#125;</code> with the
            statement redacted until you have seen it. That endpoint does not exist yet,
            and neither does one listing item ids to reach it with — so there is nothing
            to browse here rather than a browser with nothing in it.
          </p>
        </CardBody>
      </Card>
    </div>
  );
}
