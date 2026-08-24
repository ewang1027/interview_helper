"use client";

import Editor from "@monaco-editor/react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";
import type { Language } from "@/lib/types";
import type { WorkspaceProps } from "./types";

/**
 * The coding workspace: an editor and a language toggle.
 *
 * **`@monaco-editor/react` fetches Monaco from a CDN by default**, which is a
 * network dependency a self-hosted deployment should not have. It is left as
 * the default here rather than half-solved: vendoring Monaco locally means
 * bundling its web workers, which is a Phase 6 packaging job alongside the
 * Dockerfiles. Recorded in docs/WEB.md so it is a known debt rather than a
 * surprise the first time this runs somewhere without egress.
 */

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
