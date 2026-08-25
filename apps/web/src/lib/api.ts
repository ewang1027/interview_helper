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
  ImportResult,
  LogProblemBody,
  CorpusItemDetail,
  CorpusItemList,
  CorpusStatus,
  CostRollup,
  CreateSessionBody,
  CreatedSession,
  MasteryView,
  Mode,
  Plan,
  Principal,
  ProblemDetail,
  ProblemList,
  Report,
  ReviewQueue,
  TaxonomyView,
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
  // To this app's own `/login`, not to the API's `/auth/login`. Sending the
  // browser straight at the API route is what docs/WEB.md literally asks for,
  // and it dead-ends the moment OAuth is unconfigured: that route answers
  // `503 not-configured` and the user is left looking at raw problem+json.
  // `/login` works out which state the deployment is in and says so.
  //
  // Server components have no window; there the 401 propagates and the route's
  // error boundary handles it. In the browser this replaces the history entry
  // so Back does not bounce off a page that will only 401 again.
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.replace("/login");
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
 * A key that makes a retried POST safe to send twice.
 *
 * The server honours this on `POST /sessions` and `/submissions` as of
 * 2026-08-24: the same key replays the first response instead of running the
 * handler again, so a retry returns the session that already exists rather than
 * creating another. A key reused with a *different* body is a `422` rather than
 * a wrong answer — see `ApiError.slug` for branching on that.
 *
 * A fresh key per user-initiated action, which is what `crypto.randomUUID()`
 * gives: the point is that one *intent* maps to one key, so the retries of it
 * collapse while a genuine second attempt does not.
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
  concepts: (domain?: string) =>
    request<TaxonomyView>(`/concepts${domain ? `?domain=${domain}` : ""}`),
  corpusItems: (params: { domain?: string; conceptId?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.domain) query.set("domain", params.domain);
    if (params.conceptId) query.set("concept_id", params.conceptId);
    return request<CorpusItemList>(`/corpus/items?${query}`);
  },
  corpusItem: (id: string) => request<CorpusItemDetail>(`/corpus/items/${id}`),
  costs: (days = 7) => request<CostRollup>(`/costs?days=${days}`),
  budget: (sessionId?: string) =>
    request<BudgetStatus>(`/costs/budget${sessionId ? `?session_id=${sessionId}` : ""}`),

  // Practice log
  reviewQueue: () => request<ReviewQueue>("/practice/review-queue"),
  logProblem: (body: LogProblemBody, key: string) =>
    post<ProblemDetail>("/practice/problems", body, key),
  listProblems: (params: { status?: string; conceptId?: string; cursor?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.status) query.set("status", params.status);
    if (params.conceptId) query.set("concept_id", params.conceptId);
    if (params.cursor) query.set("cursor", params.cursor);
    query.set("limit", "50");
    return request<ProblemList>(`/practice/problems?${query}`);
  },
  problem: (id: string) => request<ProblemDetail>(`/practice/problems/${id}`),
  importLeetCode: (body: { slugs?: string[]; username?: string }, key: string) =>
    post<ImportResult>("/practice/import/leetcode", body, key),
  /** Confirming or correcting the tag is what writes the held evidence. */
  setClassification: (id: string, primary: string, secondary: string[] = []) =>
    request<ProblemDetail>(`/practice/problems/${id}/classification`, {
      method: "PATCH",
      body: JSON.stringify({
        primary_concept_id: primary,
        secondary_concept_ids: secondary,
      }),
    }),
  recordReview: (id: string, isSuccess: boolean, notes?: string) =>
    post<ProblemDetail>(`/practice/problems/${id}/reviews`, {
      is_success: isSuccess,
      notes: notes || null,
    }),
};
