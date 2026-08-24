/**
 * The API contract, in TypeScript.
 *
 * Hand-written rather than generated, because the API returns `dict[str, Any]`
 * from most routes and its OpenAPI document therefore describes only the eight
 * request models. Every type here was checked against a live response from a
 * seeded local stack, not inferred from the handler — the handlers are the
 * authority, and where this file and `docs/API.md` disagreed, the running
 * server settled it.
 *
 * The rule for changing this file: read the response, do not guess the shape.
 */

export type Mode = "coding" | "quant" | "design" | "behavioral";

export const MODES: readonly Mode[] = ["coding", "quant", "design", "behavioral"];

/** docs/API.md#session-state-machine. `grading` is specified but not yet observable. */
export type SessionState =
  | "planning"
  | "briefing"
  | "interviewing"
  | "wrapping"
  | "grading"
  | "complete"
  | "abandoned"
  | "failed";

/** A session is reportable in these two states, and only these two. */
export const REPORTABLE: readonly SessionState[] = ["complete", "abandoned"];

export type ItemStatus = "not_attempted" | "grading" | "graded" | "failed";

export type SubmissionKind = "code" | "answer" | "design" | "narrative";

export type Language = "python" | "cpp";

// ─── Planning ────────────────────────────────────────────────────────────────

/** The five terms behind a concept's weakness priority (docs/ADAPTIVE.md). */
export interface PriorityTerms {
  weakness: number;
  recent_errors: number;
  overdue: number;
  unlocks: number;
  recent_exposure: number;
}

export interface RankedConcept {
  concept_id: string;
  name: string;
  domain: string;
  priority: number;
  ability: number;
  observations: number;
  calibrating: boolean;
  unseen: boolean;
  terms: PriorityTerms;
}

export interface PlanReason {
  targets: string;
  priority: number;
  terms: PriorityTerms;
  expected_score: number;
  in_band: boolean;
  calibrating: boolean;
  prerequisite_note: string | null;
  /** Present only on plans written before the secondary-serving change was reverted. */
  measured_as?: string;
}

export interface PlanItem {
  item_id: string;
  title: string;
  primary_concept: string;
  expected_minutes: number | null;
  elo: number;
  reason: PlanReason;
}

export interface Plan {
  strategy: string;
  adaptive: boolean;
  /** True when no evidence exists yet, so the plan adapted to nothing. */
  calibration: boolean;
  why: string;
  mode: Mode;
  budget_minutes: number;
  /** `[low, high]` — the score band where an outcome is informative. */
  band: [number, number];
  focus_concepts: string[];
  estimated_minutes: number;
  items: PlanItem[];
  /** What it weighed, not only what it served. */
  considered: RankedConcept[];
}

// ─── Sessions ────────────────────────────────────────────────────────────────

export interface ItemOutcome {
  item_id: string;
  title: string | null;
  status: ItemStatus;
  artifact_id: string | null;
  score: number | null;
  detail: unknown;
}

export interface SessionDetail {
  id: string;
  mode: Mode;
  state: SessionState;
  budget_minutes: number;
  started_at: string;
  ended_at: string | null;
  elapsed_seconds: number;
  plan: Plan | null;
  items: ItemOutcome[];
  tokens_consumed: number;
  budget_enforced: boolean;
}

export interface SessionSummary {
  id: string;
  mode: Mode;
  state: SessionState;
  started_at: string;
  ended_at: string | null;
}

export interface SessionList {
  sessions: SessionSummary[];
  next_cursor: string | null;
}

export interface CreatedSession {
  id: string;
  state: SessionState;
  plan: Plan;
}

export interface CreateSessionBody {
  mode: Mode;
  budget_minutes: number;
  focus_concepts?: string[];
  difficulty_bias?: number;
}

export interface ToolCall {
  tool: string;
  input: Record<string, unknown>;
  output?: unknown;
  is_error?: boolean;
}

export interface TurnResult {
  item_id: string | null;
  state: SessionState;
  message: string;
  tool_calls: ToolCall[];
  hints_revealed: number;
  round_ended: boolean;
  end_reason: string | null;
  truncated: boolean;
}

export interface SubmissionBody {
  item_id: string;
  kind: SubmissionKind;
  content: string;
  language?: Language;
  elapsed_seconds?: number;
}

export interface SubmissionAccepted {
  artifact_id: string;
  item_id: string;
  state: "grading";
  poll: string;
}

export interface EvidenceRef {
  concept_id: string;
  score: number;
  confidence: number;
  item_id: string | null;
  grader_version: string;
}

export interface Report {
  session_id: string;
  mode: Mode;
  state: SessionState;
  started_at: string;
  ended_at: string | null;
  items: ItemOutcome[];
  mean_score: number | null;
  graded: number;
  failed: number;
  not_attempted: number;
  evidence: EvidenceRef[];
  /** Read off the session, not stated as a constant — e.g. "some scores are a judgement". */
  notes: string[];
}

// ─── Mastery ─────────────────────────────────────────────────────────────────

/**
 * What `mastery_row_view` projects. Note what is *not* here: a name and a
 * domain. The row is the mastery table alone, so anything needing a readable
 * label joins against the weakness ranking, which carries both.
 */
export interface MasteryRow {
  concept_id: string;
  ability: number;
  /** 0-1, already scaled between the Elo floor and ceiling by the server. */
  normalized_ability: number;
  observations: number;
  calibrating: boolean;
  stability_days: number | null;
  due_at: string | null;
  last_seen: string | null;
}

export interface MasteryView {
  concepts: MasteryRow[];
  /** How many concepts have ever been measured — against a taxonomy of 159. */
  measured: number;
  calibrating: number;
}

export interface EvidenceRow {
  id: string;
  ts: string;
  score: number;
  confidence: number;
  source: string;
  item_id: string | null;
  session_id: string | null;
  practice_problem_id: string | null;
  grader_version: string;
}

export interface ConceptDetail {
  concept_id: string;
  mastery: MasteryRow | null;
  evidence: EvidenceRow[];
}

export interface WeaknessView {
  mode: Mode | null;
  weights: PriorityTerms;
  concepts: RankedConcept[];
}

// ─── Corpus and cost ─────────────────────────────────────────────────────────

export interface CorpusStatus {
  concepts: number;
  concepts_by_domain: Record<string, number>;
  items: number;
  archetypes: number;
  instances: number;
}

export interface CostRollup {
  since: string;
  calls: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  by_job: { job: string; calls: number; cost_usd: number }[];
  by_model: { model: string; calls: number; cost_usd: number }[];
}

export interface BudgetLeg {
  spent: number;
  limit: number;
  remaining: number;
}

export interface BudgetStatus {
  session: BudgetLeg & { id: string | null };
  day: BudgetLeg & { start: string };
}

// ─── Practice log ────────────────────────────────────────────────────────────

export interface ReviewQueue {
  as_of: string;
  due: {
    problem_id: string;
    title: string;
    concept_id: string | null;
    due_at: string;
    overdue_days: number;
  }[];
}

// ─── Auth ────────────────────────────────────────────────────────────────────

export interface Principal {
  user_id: string;
  github_id: number;
  expires_at?: string;
}
