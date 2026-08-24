"use client";

import { useEffect, useRef } from "react";
import { Badge } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";
import type { Gap, TranscriptEntry } from "@/lib/session-reducer";
import type { HintRevealedEvent, ObservationEvent } from "@/lib/stream";
import { percent } from "@/lib/format";

/**
 * The conversation, plus everything the interviewer did while having it.
 *
 * Tool calls are shown rather than hidden, for the reason docs/API.md gives for
 * reporting them at all: you should be able to see that it ran your code before
 * it told you something about your code.
 */
export function Transcript({
  entries,
  streaming,
  hints,
  observations,
  gaps,
}: {
  entries: TranscriptEntry[];
  streaming: string;
  hints: HintRevealedEvent[];
  observations: ObservationEvent[];
  gaps: Gap[];
}) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [entries.length, streaming]);

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3">
      {gaps.map((gap, index) => (
        <div
          key={`${gap.after}-${index}`}
          className="rounded-md border border-[var(--status-serious)] px-3 py-2 text-xs"
        >
          <Badge tone="serious">events lost</Badge>
          <p className="text-ink-secondary mt-1">
            {gap.detail} Reported by the {gap.source}; the transcript above this point is
            incomplete.
          </p>
        </div>
      ))}

      {entries.map((entry) => {
        if (entry.kind === "tool") return <ToolCall key={entry.id} entry={entry} />;
        return (
          <div
            key={entry.id}
            className={cn(
              "max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap",
              entry.kind === "candidate"
                ? "bg-accent text-accent-ink self-end"
                : "bg-sunken text-ink self-start",
            )}
          >
            {entry.text}
          </div>
        );
      })}

      {streaming ? (
        <div className="bg-sunken text-ink max-w-[85%] self-start rounded-lg px-3 py-2 text-sm whitespace-pre-wrap">
          {streaming}
          <span className="bg-ink-muted ml-0.5 inline-block h-3 w-1.5 animate-pulse align-middle" />
        </div>
      ) : null}

      {hints.map((hint) => (
        <div
          key={`${hint.item_id}-${hint.level}`}
          className="self-start rounded-md border border-[var(--status-warning)] px-3 py-2 text-sm"
        >
          <div className="flex items-center gap-2">
            <Badge tone="warning">hint {hint.level}</Badge>
            {/* The cost is shown when it is taken, not discovered in the report. */}
            <span className="text-ink-muted text-xs">
              costs {percent(hint.score_penalty)} of the score still on the table
            </span>
          </div>
          <p className="text-ink-secondary mt-1">{hint.text}</p>
        </div>
      ))}

      {observations.length ? (
        <div className="text-ink-muted self-start text-xs">
          {observations.length} observation{observations.length === 1 ? "" : "s"} recorded:{" "}
          {observations.map((o) => `${o.concept_id} (${o.signal})`).join(", ")}
        </div>
      ) : null}

      <div ref={endRef} />
    </div>
  );
}

function ToolCall({ entry }: { entry: Extract<TranscriptEntry, { kind: "tool" }> }) {
  const pending = entry.output === undefined;

  return (
    <details className="border-hairline self-start rounded-md border px-2 py-1.5 text-xs">
      <summary className="text-ink-secondary cursor-pointer list-none">
        <Badge tone={entry.isError ? "critical" : "neutral"}>{entry.tool}</Badge>
        <span className="text-ink-muted ml-2">
          {pending ? "running…" : entry.isError ? "failed" : "done"}
        </span>
      </summary>
      <pre className="text-ink-muted mt-1.5 max-w-md overflow-x-auto text-[11px] whitespace-pre-wrap">
        {JSON.stringify(entry.input, null, 2)}
      </pre>
      {!pending ? (
        <pre className="text-ink-secondary border-hairline mt-1 max-w-md overflow-x-auto border-t pt-1 text-[11px] whitespace-pre-wrap">
          {JSON.stringify(entry.output, null, 2)}
        </pre>
      ) : null}
    </details>
  );
}
