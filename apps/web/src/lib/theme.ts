"use client";

import { useSyncExternalStore } from "react";
import { THEME_KEY as KEY } from "./theme-bootstrap";

/**
 * The colour theme: follow the OS, or pin light or dark.
 *
 * `globals.css` has carried a dark palette since Phase 5, applied under
 * `prefers-color-scheme: dark` unless `<html data-theme="light">`, and forced by
 * `data-theme="dark"`. Nothing set that attribute, so the only way to see the dark theme
 * was to change the OS. This is the setter, and the one reader for code that has to know
 * the answer in JavaScript — Monaco takes a theme name, not a CSS variable.
 *
 * "system" is stored as the absence of a choice, so clearing it restores the OS default.
 * Storage can throw (private windows, blocked site data); every access is guarded and a
 * failure means "system", which is what the page shows before any script runs anyway.
 *
 * The script that applies a stored choice before first paint is in `theme-bootstrap.ts`,
 * because the server layout has to import it.
 */

export type ThemeChoice = "system" | "light" | "dark";

export function readThemeChoice(): ThemeChoice {
  try {
    const stored = localStorage.getItem(KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system";
  }
}

export function setThemeChoice(choice: ThemeChoice) {
  const root = document.documentElement;
  if (choice === "system") delete root.dataset.theme;
  else root.dataset.theme = choice;
  try {
    if (choice === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, choice);
  } catch {
    // The choice still applies to this page; it just will not survive a reload.
  }
}

// jsdom has no `matchMedia`; a browser always does. Without it, "system" means light.
function darkQuery(): MediaQueryList | null {
  return typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;
}

function isDark(): boolean {
  const pinned = document.documentElement.dataset.theme;
  if (pinned === "dark") return true;
  if (pinned === "light") return false;
  return darkQuery()?.matches ?? false;
}

function subscribe(onChange: () => void) {
  const media = darkQuery();
  media?.addEventListener("change", onChange);
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => {
    media?.removeEventListener("change", onChange);
    observer.disconnect();
  };
}

/** Whether the page is drawn dark right now, whichever of the OS or a pin decided it. */
export function useIsDark(): boolean {
  return useSyncExternalStore(subscribe, isDark, () => false);
}
