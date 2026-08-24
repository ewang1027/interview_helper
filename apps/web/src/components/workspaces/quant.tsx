"use client";

import { useEffect, useState } from "react";
import type { WorkspaceProps } from "./types";

/**
 * Derivation above, the answer stated below.
 *
 * The split is not cosmetic — it matches how the grader reads a submission.
 * `closing_statement` looks for a declaration ("Answer: 39") and grades the
 * number after it, falling back to the last line carrying arithmetic; a
 * derivation mentions numbers that are not the answer, and the marker is what
 * stops a sanity bound being graded as the conclusion. So the answer field is
 * appended as a declared final line rather than being left for a heuristic to
 * find, and a candidate who states nothing has *not answered* — which scores
 * differently from answering wrongly.
 */
export function QuantWorkspace({ onChange, disabled }: WorkspaceProps) {
  const [derivation, setDerivation] = useState("");
  const [answer, setAnswer] = useState("");

  useEffect(() => {
    const content = answer.trim()
      ? `${derivation.trim()}\n\nAnswer: ${answer.trim()}`
      : derivation.trim();
    onChange({ kind: "answer", content });
  }, [derivation, answer, onChange]);

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 p-3">
        <label
          htmlFor="derivation"
          className="text-ink-muted mb-1 block text-xs font-medium tracking-wide uppercase"
        >
          Derivation
        </label>
        <textarea
          id="derivation"
          value={derivation}
          onChange={(event) => setDerivation(event.target.value)}
          disabled={disabled}
          spellCheck={false}
          placeholder="Work it through — the reasoning is graded against the item's rubric, separately from the number."
          className="border-hairline bg-surface text-ink h-full w-full resize-none rounded-md border p-2 font-mono text-sm"
        />
      </div>
      <div className="border-hairline border-t p-3">
        <label
          htmlFor="answer"
          className="text-ink-muted mb-1 block text-xs font-medium tracking-wide uppercase"
        >
          Final answer
        </label>
        <input
          id="answer"
          value={answer}
          onChange={(event) => setAnswer(event.target.value)}
          disabled={disabled}
          spellCheck={false}
          placeholder="e.g. 39, or 3/8, or n(n-1)/2"
          className="border-hairline bg-surface text-ink w-full rounded-md border p-2 font-mono text-sm"
        />
        <p className="text-ink-muted mt-1 text-xs">
          Submitted as a declared last line. Stating nothing is not the same as being
          wrong, and is graded differently.
        </p>
      </div>
    </div>
  );
}
