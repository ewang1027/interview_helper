/**
 * The one place this app talks to the API.
 *
 * Three rules from docs/WEB.md, all enforced here rather than at call sites:
 *
 * - **`credentials: "include"` on every request.** The session cookie is
 *   `HttpOnly`, so JavaScript cannot read it and must not try; it travels
 *   because the browser sends it, and requests go through the same-origin
 *   proxy in `next.config.ts` so `SameSite=Lax` does not withhold it.
 * - **A 401 sends the browser to `/auth/login`, it does not render an error.**
 *   There is no useful message to show — the cookie expired or was never there,
 *   and both are fixed by logging in.
 * - **Errors branch on the RFC 9457 `type` slug, never on prose.** Matching on
 *   a title is how error handling rots the first time somebody rewords one.
 */

import type {
  BudgetStatus,
  ConceptDetail,
  CorpusStatus,
  CostRollup,
  CreateSessionBody,
  CreatedSession,
  MasteryView,
  Mode,
  Plan,
  Principal,
  Report,
  ReviewQueue,
  SessionDetail,
  SessionList,
  SubmissionAccepted,
  SubmissionBody,
  TurnResult,
  WeaknessView,
} from "./types";

const BASE = "/api/v1";

/** The slug tail of an RFC 9457 `type` URI — `.../errors/budget-exceeded` → `budget-exceeded`. */
export type ProblemSlug = string;

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  [key: string]: unknown;
}

/**
 * A failed request, carrying the problem document so a caller can branch on
 * `slug` without re-parsing anything.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly slug: ProblemSlug;
  readonly problem: Problem | null;

  constructor(status: number, problem: Problem | null, fallback: string) {
    super(problem?.detail || problem?.title || fallback);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
    this.slug = problem?.type ? problem.type.split("/").pop()! : `http-${status}`;
  }

  /** The server is missing configuration this request needed — not a login problem. */
  get isNotConfigured(): boolean {
    return this.status === 503 && this.slug === "not-configured";
  }

  /** A hard refusal, never a silent downgrade (docs/COST.md#hard-budgets). */
  get isBudgetExceeded(): boolean {
    return this.slug === "budget-exceeded";
  }

  /** Wrong state for what was asked — e.g. a report before the session is complete. */
  get isWrongState(): boolean {
    return this.status === 409;
  }
}

function loginRedirect(): never {
  // Server components have no window; there the 401 propagates and the route's
  // error boundary handles it. In the browser this replaces the history entry
  // so Back does not bounce off a page that will only 401 again.
  if (typeof window !== "undefined") {
    window.location.replace("/auth/login");
  }
  throw new ApiError(401, null, "Not signed in");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path.startsWith("/api") || path.startsWith("/auth") ? path : BASE + path, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });

  if (response.status === 401) loginRedirect();

  if (!response.ok) {
    let problem: Problem | null = null;
    // A problem document is the contract, but a proxy or a crash can answer
    // with something else entirely, and a JSON parse failure must not become
    // the error the user sees instead of the status that caused it.
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "type" in body) problem = body as Problem;
    } catch {
      /* not JSON — fall through to the status-only error */
    }
    throw new ApiError(response.status, problem, `${response.status} ${response.statusText}`);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/**
 * A key that would make a retried POST safe to send twice.
 *
 * docs/API.md lists `Idempotency-Key` on `POST /sessions` and `/submissions` as
 * owed *before* this app, precisely because a browser on a flaky network
 * retries — and **the server does not honour it yet**. The header is sent
 * anyway so the client half is in place and the server half is a server change
 * alone, but until it lands a retried `POST /sessions` creates two sessions.
 *
 * What is already protected is the harmful half: one item cannot write two sets
 * of evidence into one session, because a second submission for it is refused
 * `409`. Retries are also disabled for mutations in `providers.tsx`, so nothing
 * here retries a POST on its own — but a user pressing a button twice, or a
 * browser replaying a request, is not covered.
 */
export function idempotencyKey(): string {
  return crypto.randomUUID();
}

function post<T>(path: string, body: unknown, key?: string): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: key ? { "Idempotency-Key": key } : {},
  });
}

export const api = {
  // Auth
  me: () => request<Principal>("/auth/me"),
  logout: () => request<void>("/auth/logout", { method: "POST" }),

  // Planning
  planNext: (mode: Mode, budgetMinutes: number) =>
    request<Plan>(`/plan/next?mode=${mode}&budget_minutes=${budgetMinutes}`),

  // Sessions
  createSession: (body: CreateSessionBody, key: string) =>
    post<CreatedSession>("/sessions", body, key),
  listSessions: (params: { cursor?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.cursor) query.set("cursor", params.cursor);
    query.set("limit", String(params.limit ?? 20));
    return request<SessionList>(`/sessions?${query}`);
  },
  session: (id: string) => request<SessionDetail>(`/sessions/${id}`),
  turn: (id: string, content: string) => post<TurnResult>(`/sessions/${id}/turns`, { content }),
  submit: (id: string, body: SubmissionBody, key: string) =>
    post<SubmissionAccepted>(`/sessions/${id}/submissions`, body, key),
  endSession: (id: string) => post<{ id: string; state: string; ended_at: string }>(`/sessions/${id}/end`, {}),
  report: (id: string) => request<Report>(`/sessions/${id}/report`),

  // Mastery
  mastery: () => request<MasteryView>("/mastery"),
  concept: (conceptId: string) => request<ConceptDetail>(`/mastery/${conceptId}`),
  weaknesses: (params: { mode?: Mode; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.mode) query.set("mode", params.mode);
    query.set("limit", String(params.limit ?? 20));
    return request<WeaknessView>(`/mastery/weaknesses?${query}`);
  },
  recompute: () => post<Record<string, unknown>>("/mastery/recompute", {}),

  // Corpus and cost
  corpusStatus: () => request<CorpusStatus>("/corpus/status"),
  costs: (days = 7) => request<CostRollup>(`/costs?days=${days}`),
  budget: (sessionId?: string) =>
    request<BudgetStatus>(`/costs/budget${sessionId ? `?session_id=${sessionId}` : ""}`),

  // Practice log
  reviewQueue: () => request<ReviewQueue>("/practice/review-queue"),
};
