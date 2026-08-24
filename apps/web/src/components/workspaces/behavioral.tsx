"use client";

import { useEffect, useState } from "react";
import type { WorkspaceProps } from "./types";

/**
 * Transcript-driven, with a STAR rail beside it.
 *
 * The rail is four labelled fields rather than a checklist over free text: the
 * rubric grader cites criteria against the artifact, and a submission whose
 * structure is explicit is one it can cite precisely. Empty sections are
 * omitted from the submission rather than sent as headings with nothing under
 * them — a heading with no content reads to a grader as an attempt at that
 * section, which is worse than its absence.
 */

const SECTIONS = [
  { key: "Situation", hint: "The context, briefly. Where and when." },
  { key: "Task", hint: "What was actually yours to do." },
  { key: "Action", hint: "What you did — specifics, first person." },
  { key: "Result", hint: "What changed. Numbers if you have them." },
] as const;

export function BehavioralWorkspace({ onChange, disabled }: WorkspaceProps) {
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    const content = SECTIONS.filter((section) => values[section.key]?.trim())
      .map((section) => `## ${section.key}\n${values[section.key]!.trim()}`)
      .join("\n\n");
    onChange({ kind: "narrative", content });
  }, [values, onChange]);

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3">
      {SECTIONS.map((section) => (
        <div key={section.key}>
          <label
            htmlFor={`star-${section.key}`}
            className="text-ink-muted mb-1 block text-xs font-medium tracking-wide uppercase"
          >
            {section.key}
            <span className="text-ink-muted ml-2 normal-case">{section.hint}</span>
          </label>
          <textarea
            id={`star-${section.key}`}
            rows={4}
            disabled={disabled}
            value={values[section.key] ?? ""}
            onChange={(event) =>
              setValues((current) => ({ ...current, [section.key]: event.target.value }))
            }
            className="border-hairline bg-surface text-ink w-full resize-y rounded-md border p-2 text-sm"
          />
        </div>
      ))}
    </div>
  );
}
