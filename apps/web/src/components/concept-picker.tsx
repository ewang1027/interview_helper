"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { useTaxonomy } from "@/lib/queries";

/**
 * Pick a concept out of the 159-concept taxonomy.
 *
 * A plain `<select>` of 159 options is unusable, and this is the control that
 * matters most when the classifier cannot run: below the confidence gate — or
 * when the provider is unreachable at all — a problem sits
 * `pending_classification`, feeding nothing, until a human names the concept.
 * So the correction path has to be quick rather than merely possible.
 */
export function ConceptPicker({
  value,
  onChange,
  placeholder = "Search concepts…",
  id,
}: {
  value: string | null;
  onChange: (conceptId: string | null) => void;
  placeholder?: string;
  id?: string;
}) {
  const { concepts, isLoading } = useTaxonomy();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return concepts.slice(0, 12);
    return concepts
      .filter(
        (concept) =>
          concept.name.toLowerCase().includes(needle) ||
          concept.concept_id.toLowerCase().includes(needle),
      )
      .slice(0, 12);
  }, [concepts, query]);

  const selected = concepts.find((concept) => concept.concept_id === value);

  if (value && selected) {
    return (
      <div className="flex items-center gap-2">
        <span className="border-hairline bg-sunken inline-flex items-center gap-2 rounded-md border px-2 py-1 text-sm">
          {selected.name}
          <span className="text-ink-muted font-mono text-xs">{selected.concept_id}</span>
        </span>
        <button
          type="button"
          onClick={() => {
            onChange(null);
            setQuery("");
          }}
          className="text-ink-muted hover:text-ink text-xs underline"
        >
          change
        </button>
      </div>
    );
  }

  return (
    <div className="relative">
      <input
        id={id}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        // A click on an option would otherwise be lost to the blur that precedes it.
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        placeholder={isLoading ? "Loading the taxonomy…" : placeholder}
        disabled={isLoading}
        className="border-hairline bg-surface text-ink w-full rounded-md border px-2 py-1.5 text-sm"
      />
      {open && matches.length > 0 ? (
        <ul className="border-hairline bg-surface absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-md border shadow-lg">
          {matches.map((concept) => (
            <li key={concept.concept_id}>
              <button
                type="button"
                onClick={() => {
                  onChange(concept.concept_id);
                  setOpen(false);
                }}
                className={cn(
                  "hover:bg-sunken flex w-full items-baseline gap-2 px-2 py-1.5 text-left text-sm",
                )}
              >
                <span className="min-w-0 flex-1 truncate">{concept.name}</span>
                <span className="text-ink-muted shrink-0 font-mono text-[11px]">
                  {concept.domain}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
