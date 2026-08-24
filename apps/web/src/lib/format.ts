/** Presentation helpers. Nothing here decides anything — see docs/WEB.md. */

export function score(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toFixed(2);
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`;
}

export function elo(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : Math.round(value).toString();
}

export function usd(value: number): string {
  return value < 0.01 && value > 0 ? `<$0.01` : `$${value.toFixed(2)}`;
}

export function compactNumber(value: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact" }).format(value);
}

export function duration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d`;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "3 days overdue" / "due in 2 days" / "due now". */
export function relativeDue(iso: string | null): string {
  if (!iso) return "not scheduled";
  const days = Math.round((new Date(iso).getTime() - Date.now()) / 86_400_000);
  if (days === 0) return "due today";
  return days < 0 ? `${Math.abs(days)}d overdue` : `due in ${days}d`;
}

export function titleCase(value: string): string {
  return value.replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
