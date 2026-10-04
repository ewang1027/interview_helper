"use client";

import Editor, { loader } from "@monaco-editor/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { useIsDark } from "@/lib/theme";
import type { Language } from "@/lib/types";
import type { WorkspaceProps } from "./types";

/**
 * The coding workspace: an editor and a language toggle.
 *
 * **Monaco is served from this app, not from a CDN.** `@monaco-editor/react`
 * otherwise fetches it from `cdn.jsdelivr.net` at runtime, which means a
 * self-hosted deployment with no egress has an editor that never finishes
 * loading, every candidate's session depends on a third party staying up, and
 * the version is whatever the loader package pins rather than what this
 * lockfile does. `scripts/vendor-monaco.mjs` copies the bundle into
 * `public/monaco/<version>/vs` at build time and this points at it — the version comes
 * from `next.config.ts`, which inlines it, and the path carries it so the files can be
 * cached `immutable` (a Monaco upgrade is a new URL, not a stale cache).
 *
 * Configured at module scope rather than in an effect: `loader.config` must run
 * before the first `<Editor>` mounts, and an effect runs after.
 */
loader.config({ paths: { vs: `/monaco/${process.env.MONACO_VERSION}/vs` } });

/**
 * Hoisted, and that matters more than it looks.
 *
 * `@monaco-editor/react` is itself `memo`'d, but it keys two effects on the
 * *identity* of what it is handed: `options` drives `editor.updateOptions()`,
 * and `onChange` drives a `dispose()` + re-`onDidChangeModelContent()`. Built
 * inline they were new objects on every render, so both fired on every render —
 * a full options-validation pass and a listener torn down and rebuilt on each
 * character typed into the editor, and again on each token streamed into the
 * page around it. Defining them outside the render, and merging the one option
 * that varies through a `useMemo`, is what makes that memo mean something.
 */
const EDITOR_OPTIONS = {
  minimap: { enabled: false },
  fontSize: 13,
  scrollBeyondLastLine: false,
  tabSize: 4,
  automaticLayout: true,
} as const;

const STARTERS: Record<Language, string> = {
  python: "def solve():\n    ...\n",
  cpp: "#include <bits/stdc++.h>\n\nint main() {\n    return 0;\n}\n",
};

export function CodingWorkspace({
  onChange,
  disabled,
  languages = ["python", "cpp"],
}: WorkspaceProps & { languages?: Language[] }) {
  const [language, setLanguage] = useState<Language>(languages[0] ?? "python");
  const [source, setSource] = useState(STARTERS[languages[0] ?? "python"]);

  useEffect(() => {
    onChange({ kind: "code", content: source, language });
  }, [source, language, onChange]);

  const options = useMemo(() => ({ ...EDITOR_OPTIONS, readOnly: disabled }), [disabled]);
  // Monaco draws its own colours and knows nothing of the CSS tokens, so without this it
  // stayed a white editor inside a dark page.
  const dark = useIsDark();
  const onEdit = useCallback((value: string | undefined) => setSource(value ?? ""), []);

  return (
    <div className="flex h-full flex-col">
      <div className="border-hairline flex items-center gap-2 border-b px-3 py-2">
        {languages.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => {
              setLanguage(option);
              // Only replace untouched boilerplate — never discard real work.
              if (Object.values(STARTERS).includes(source.trim() + "\n") || !source.trim()) {
                setSource(STARTERS[option]);
              }
            }}
            aria-pressed={language === option}
            className={cn(
              "rounded px-2 py-1 text-xs transition-colors",
              language === option
                ? "bg-accent text-accent-ink"
                : "text-ink-secondary hover:bg-sunken",
            )}
          >
            {option === "cpp" ? "C++" : "Python"}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1">
        <Editor
          height="100%"
          language={language === "cpp" ? "cpp" : "python"}
          theme={dark ? "vs-dark" : "light"}
          value={source}
          onChange={onEdit}
          options={options}
          loading={<div className="text-ink-muted p-3 text-sm">Loading editor…</div>}
        />
      </div>
    </div>
  );
}
