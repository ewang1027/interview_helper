"use client";

import { Badge } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";

/**
 * A failed request, rendered from its problem document.
 *
 * Branches on the RFC 9457 `type` slug, never on the prose — docs/API.md calls
 * matching on a title "how error handling rots", and it is right: a reworded
 * message should not change what a client does.
 */
export function ApiErrorNotice({ error }: { error: unknown }) {
  if (!(error instanceof ApiError)) {
    return (
      <p className="text-sm text-[var(--status-critical)]">Something went wrong loading this.</p>
    );
  }

  return (
    <div className="rounded-md border border-[var(--status-critical)] px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="critical">{error.slug}</Badge>
        <span className="text-ink text-sm font-medium">
          {error.problem?.title ?? `HTTP ${error.status}`}
        </span>
      </div>
      {error.problem?.detail ? (
        <p className="text-ink-secondary mt-1 text-sm">{error.problem.detail}</p>
      ) : null}
      {error.isNotConfigured ? (
        <p className="text-ink-muted mt-1 text-xs">
          The server is missing configuration this request needed — not a login problem.
        </p>
      ) : null}
      {error.isBudgetExceeded ? (
        <p className="text-ink-muted mt-1 text-xs">
          Refused rather than downgraded to a cheaper model: bad evidence corrupts mastery
          permanently.
        </p>
      ) : null}
      {error.isWrongState ? (
        <p className="text-ink-muted mt-1 text-xs">
          The session is not in a state where this is possible yet.
        </p>
      ) : null}
    </div>
  );
}
