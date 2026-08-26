"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { ApiErrorNotice } from "@/components/api-error";
import { Badge, Button, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { api, idempotencyKey } from "@/lib/api";
import { titleCase, usd } from "@/lib/format";
import type { CreateJobBody, ImportJobsResult, JobCatalog, Stage } from "@/lib/types";

/**
 * The two ways applications get in: paste a list, or type one.
 *
 * The paste box is the slow path and says so before you use it. It always makes
 * one structured call to parse and tag what you pasted, and above the configured
 * threshold a second one that searches the web for the postings — which reaches
 * the network and can take a while. A spinner with no explanation would read as
 * a hang.
 *
 * Afterwards the result reports **whether the research pass ran, and why not
 * when it did not**. Rows from a plain parse and rows from a researched parse
 * look identical on the board and are not equally trustworthy, so hiding the
 * difference would be hiding the only thing that distinguishes them.
 */

const PLACEHOLDER = `Paste anything — a spreadsheet column, an email, a numbered list:

Aurora Labs — Backend Engineer — applied 2026-07-04
Northwind Systems, Quantitative Trader, passed the OA
Helio Robotics / ML Engineer / rejected`;

export function ImportForm({ onImported }: { onImported: () => void }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState<ImportJobsResult | null>(null);

  const importing = useMutation({
    mutationFn: () => api.importJobs(text, idempotencyKey()),
    onSuccess: (data) => {
      setResult(data);
      setText("");
      onImported();
    },
  });

  return (
    <Card>
      <CardHeader
        title="Paste a list"
        hint="One call parses and tags it. Long lists get a second pass that searches the web for the postings."
      />
      <CardBody className="space-y-3">
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={PLACEHOLDER}
          rows={7}
          maxLength={100_000}
          aria-label="Applications to import"
          className="border-hairline bg-page text-ink placeholder:text-ink-muted w-full rounded-md border px-3 py-2 font-mono text-xs"
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={() => importing.mutate()}
            disabled={!text.trim() || importing.isPending}
          >
            {importing.isPending ? "Reading the list…" : "Import"}
          </Button>
          {importing.isPending ? (
            <span className="text-ink-muted text-xs">
              This can take a minute if the research pass runs — it makes real web searches.
            </span>
          ) : null}
        </div>

        {importing.error ? <ApiErrorNotice error={importing.error} /> : null}

        {result ? (
          <div className="border-hairline bg-sunken space-y-1 rounded-md border px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={result.created ? "good" : "neutral"}>{result.created} added</Badge>
              {result.duplicates ? (
                <Badge tone="neutral">{result.duplicates} already tracked</Badge>
              ) : null}
              {result.researched ? (
                <Badge tone="accent">
                  researched · {result.web_searches} search
                  {result.web_searches === 1 ? "" : "es"}
                </Badge>
              ) : null}
              <span className="text-ink-muted text-xs">{usd(result.cost_usd)}</span>
            </div>
            {!result.researched && result.research_skipped ? (
              <p className="text-ink-muted text-xs">
                No web research: {result.research_skipped}.
              </p>
            ) : null}
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

/** One application, typed. No model call — you know what the role is. */
export function ManualForm({
  catalog,
  onCreated,
}: {
  catalog: JobCatalog | undefined;
  onCreated: () => void;
}) {
  const [form, setForm] = useState<CreateJobBody>({ company: "", role: "" });

  const create = useMutation({
    mutationFn: () =>
      api.createJob({
        ...form,
        location: form.location || null,
        url: form.url || null,
        subcategory: form.subcategory || null,
        notes: form.notes || null,
      }),
    onSuccess: () => {
      setForm({ company: "", role: "" });
      onCreated();
    },
  });

  const field =
    "border-hairline bg-page text-ink placeholder:text-ink-muted w-full rounded-md border px-3 py-1.5 text-sm";
  const subcategories = catalog
    ? Object.entries(catalog.categories).flatMap(([category, subs]) =>
        subs.map((sub) => ({ category, sub })),
      )
    : [];

  return (
    <Card>
      <CardHeader title="Add one by hand" hint="No model call — nothing here needs classifying." />
      <CardBody>
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate();
          }}
        >
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              className={field}
              placeholder="Company"
              required
              maxLength={200}
              value={form.company}
              onChange={(event) => setForm({ ...form, company: event.target.value })}
            />
            <input
              className={field}
              placeholder="Role"
              required
              maxLength={200}
              value={form.role}
              onChange={(event) => setForm({ ...form, role: event.target.value })}
            />
            <input
              className={field}
              placeholder="Location (optional)"
              maxLength={200}
              value={form.location ?? ""}
              onChange={(event) => setForm({ ...form, location: event.target.value })}
            />
            <input
              className={field}
              placeholder="Posting URL (optional)"
              maxLength={2000}
              value={form.url ?? ""}
              onChange={(event) => setForm({ ...form, url: event.target.value })}
            />
            <select
              className={field}
              value={form.subcategory ?? ""}
              aria-label="Sub-category"
              onChange={(event) => setForm({ ...form, subcategory: event.target.value })}
            >
              {/* Empty is a real choice: the row lands in review, which is the
                  same state a low-confidence parse produces. One queue, not two. */}
              <option value="">Tag it later</option>
              {subcategories.map(({ category, sub }) => (
                <option key={sub} value={sub}>
                  {titleCase(category)} · {titleCase(sub)}
                </option>
              ))}
            </select>
            <select
              className={field}
              value={form.stage ?? "applied"}
              aria-label="Stage"
              onChange={(event) => setForm({ ...form, stage: event.target.value as Stage })}
            >
              {catalog
                ? [...catalog.ladder, ...catalog.terminal].map((stage) => (
                    <option key={stage} value={stage}>
                      {catalog.stage_labels[stage] ?? titleCase(stage)}
                    </option>
                  ))
                : null}
            </select>
          </div>
          {create.error ? <ApiErrorNotice error={create.error} /> : null}
          <Button type="submit" size="sm" disabled={create.isPending}>
            {create.isPending ? "Adding…" : "Add application"}
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
