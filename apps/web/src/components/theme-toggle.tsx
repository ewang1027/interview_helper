"use client";

import { useEffect, useState } from "react";
import { readThemeChoice, setThemeChoice, type ThemeChoice } from "@/lib/theme";

const OPTIONS: { value: ThemeChoice; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

/**
 * A native `<select>`: labelled, keyboard-operable and compact at a phone width without
 * any of that having to be built. The stored choice is read after mount — the server
 * cannot see it, and rendering it during hydration would mismatch.
 */
export function ThemeToggle() {
  const [choice, setChoice] = useState<ThemeChoice>("system");

  useEffect(() => {
    setChoice(readThemeChoice());
  }, []);

  return (
    <select
      aria-label="Colour theme"
      value={choice}
      onChange={(event) => {
        const next = event.target.value as ThemeChoice;
        setChoice(next);
        setThemeChoice(next);
      }}
      className="bg-surface text-ink-secondary border-hairline hover:border-axis h-8 shrink-0 cursor-pointer rounded-md border px-2 text-xs"
    >
      {OPTIONS.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
