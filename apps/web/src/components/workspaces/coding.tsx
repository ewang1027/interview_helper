"use client";

import Editor, { loader } from "@monaco-editor/react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";
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
 * `public/monaco/vs` at build time and this points at it.
 *
 * Configured at module scope rather than in an effect: `loader.config` must run
 * before the first `<Editor>` mounts, and an effect runs after.
 */
loader.config({ paths: { vs: "/monaco/vs" } });


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
          value={source}
          onChange={(value) => setSource(value ?? "")}
          options={{
            readOnly: disabled,
            minimap: { enabled: false },
            fontSize: 13,
            scrollBeyondLastLine: false,
            tabSize: 4,
            automaticLayout: true,
          }}
          loading={<div className="text-ink-muted p-3 text-sm">Loading editor…</div>}
        />
      </div>
    </div>
  );
}
