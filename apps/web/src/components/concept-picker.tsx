"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { useTaxonomy } from "@/lib/queries";

/**
 * Pick a concept out of the 186-concept taxonomy.
 *
 * A plain `<select>` of 186 options is unusable, and this is the control that
 * matters most when the classifier cannot run: below the confidence gate — or
 * when the provider is unreachable at all — a problem sits
 * `pending_classification`, feeding nothing, until a human names the concept.
 * So the correction path has to be quick rather than merely possible.
 *
 * The search covers a concept's aliases (`tags`) as well as its name and id,
 * because what a person has in mind is the problem they just solved — "meeting
 * rooms", "group anagrams" — and not the taxonomy's word for it. A match on an
 * alias shows the alias, so the reason the concept appeared is visible.
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
    if (!needle) return concepts.slice(0, 12).map((concept) => ({ concept, via: null }));
    const hits: { concept: (typeof concepts)[number]; via: string | null }[] = [];
    for (const concept of concepts) {
      if (
        concept.name.toLowerCase().includes(needle) ||
        concept.id.toLowerCase().includes(needle)
      ) {
        hits.push({ concept, via: null });
        continue;
      }
      const alias = concept.tags.find((tag) => tag.toLowerCase().includes(needle));
      if (alias) hits.push({ concept, via: alias });
    }
    // Name and id matches first: an alias hit is a weaker claim than the concept's own name.
    hits.sort((a, b) => Number(a.via !== null) - Number(b.via !== null));
    return hits.slice(0, 12);
  }, [concepts, query]);

  const selected = concepts.find((concept) => concept.id === value);

  if (value && selected) {
    return (
      <div className="flex items-center gap-2">
        <span className="border-hairline bg-sunken inline-flex items-center gap-2 rounded-md border px-2 py-1 text-sm">
          {selected.name}
          <span className="text-ink-muted font-mono text-xs">{selected.id}</span>
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
          {matches.map(({ concept, via }) => (
            <li key={concept.id}>
              <button
                type="button"
                onClick={() => {
                  onChange(concept.id);
                  setOpen(false);
                }}
                className={cn(
                  "hover:bg-sunken flex w-full items-baseline gap-2 px-2 py-1.5 text-left text-sm",
                )}
              >
                <span className="min-w-0 flex-1 truncate">
                  {concept.name}
                  {via ? <span className="text-ink-muted text-xs"> · {via}</span> : null}
                </span>
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
