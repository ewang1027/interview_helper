"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { ApiErrorNotice } from "@/components/api-error";
import { Badge, Button, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { api, idempotencyKey } from "@/lib/api";

/**
 * Import from LeetCode by pasting links, or from a public profile.
 *
 * **Metadata only.** This asks LeetCode for a title, a difficulty and the topic tags —
 * the same fields you would type by hand. No problem statement is requested or stored,
 * which is what keeps it inside the practice log's manual-entry-only rule rather than
 * an exception to it.
 *
 * **Everything lands awaiting confirmation, and that is deliberate.** A resolved
 * classification cannot be re-tagged — its evidence is written, and evidence is
 * immutable — so a wrong auto-accept would be permanent. What the import removes is
 * searching 159 concepts per problem, not the confirmation.
 */
export function LeetCodeImport({ onImported }: { onImported: () => void }) {
  const [pasted, setPasted] = useState("");
  const [username, setUsername] = useState("");

  const run = useMutation({
    mutationFn: () => {
      const slugs = pasted
        .split(/[\s,]+/)
        .map((line) => line.trim())
        .filter(Boolean);
      return api.importLeetCode(
        { slugs, username: username.trim() || undefined },
        idempotencyKey(),
      );
    },
    onSuccess: () => {
      setPasted("");
      onImported();
    },
  });

  const result = run.data;

  return (
    <Card>
      <CardHeader
        title="Import from LeetCode"
        hint="Titles, difficulty and topic tags only — never the problem text."
      />
      <CardBody className="space-y-3">
        <div>
          <label
            htmlFor="lc-paste"
            className="text-ink-muted mb-1 block text-xs font-medium tracking-wide uppercase"
          >
            Paste links or slugs
            <span className="ml-2 normal-case">one per line, or comma separated</span>
          </label>
          <textarea
            id="lc-paste"
            rows={5}
            value={pasted}
            onChange={(event) => setPasted(event.target.value)}
            spellCheck={false}
            placeholder={"https://leetcode.com/problems/two-sum/\nlongest-substring-without-repeating-characters\nmerge-k-sorted-lists"}
            className="border-hairline bg-surface text-ink w-full resize-y rounded-md border p-2 font-mono text-xs"
          />
        </div>

        <div>
          <label
            htmlFor="lc-user"
            className="text-ink-muted mb-1 block text-xs font-medium tracking-wide uppercase"
          >
            …or your LeetCode username
            <span className="ml-2 normal-case">pulls your recent accepted solves</span>
          </label>
          <input
            id="lc-user"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="your-handle"
            className="border-hairline bg-surface text-ink w-full rounded-md border px-2 py-1.5 text-sm"
          />
        </div>

        {run.error ? <ApiErrorNotice error={run.error} /> : null}

        <Button
          disabled={run.isPending || (!pasted.trim() && !username.trim())}
          onClick={() => run.mutate()}
        >
          {run.isPending ? "Fetching from LeetCode…" : "Import"}
        </Button>

        {result ? (
          <div className="space-y-2 pt-1">
            <p className="text-ink-secondary text-sm">
              Imported <strong>{result.imported.length}</strong>,{" "}
              <strong>{result.with_a_suggestion}</strong> with a concept already suggested.
              None counts until confirmed.
            </p>

            {result.imported.length ? (
              <ul className="divide-hairline max-h-56 divide-y overflow-y-auto text-xs">
                {result.imported.map((row) => (
                  <li key={row.id} className="flex flex-wrap items-baseline gap-2 py-1.5">
                    <Link
                      href={`/practice/${row.id}`}
                      className="min-w-0 flex-1 truncate hover:underline"
                    >
                      {row.title}
                    </Link>
                    {row.suggested_concept_id ? (
                      <Badge tone="good">{row.suggested_concept_id}</Badge>
                    ) : (
                      <Badge tone="warning" title={row.why}>
                        no suggestion
                      </Badge>
                    )}
                  </li>
                ))}
              </ul>
            ) : null}

            {result.skipped.length ? (
              <details>
                <summary className="text-ink-secondary cursor-pointer text-xs underline">
                  {result.skipped.length} skipped
                </summary>
                <ul className="text-ink-muted mt-1 space-y-0.5 text-xs">
                  {result.skipped.map((row, index) => (
                    <li key={index}>
                      <span className="font-mono">{row.slug ?? row.input}</span> — {row.reason}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        ) : null}

        <p className="text-ink-muted text-xs">
          A tag that names a family this taxonomy splits several ways —{" "}
          <code>dynamic-programming</code> covers five concepts, <code>design</code> three —
          suggests nothing and waits for you. LeetCode co-tags DP problems with the other
          solutions people post, and trusting that once imported <code>coin-change</code> as
          a graph problem.
        </p>
      </CardBody>
    </Card>
  );
}
