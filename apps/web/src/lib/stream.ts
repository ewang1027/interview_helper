/**
 * The SSE event contract (docs/API.md#sse-event-stream).
 *
 * Two properties of the wire format shape every client that reads it:
 *
 * - **Every frame is named.** The server writes `event: <type>`, so the browser
 *   dispatches to a listener registered for that name and `onmessage` — which
 *   only ever sees unnamed frames — receives nothing at all. A client must
 *   subscribe to each type by name; there is no wildcard in `EventSource`.
 * - **Every frame carries `id: <seq>`.** That is what comes back as
 *   `Last-Event-ID` on an automatic reconnect, which is what makes reconnection
 *   lossless and gaps detectable.
 */

import type { SessionState } from "./types";

export interface BaseEvent {
  type: string;
  seq: number;
  at: string;
}

export interface SessionStateEvent extends BaseEvent {
  type: "session.state";
  state: SessionState;
  reason?: string;
}

export interface ItemPresentedEvent extends BaseEvent {
  type: "item.presented";
  item_id: string;
  title: string;
  statement_md: string;
  expected_minutes: number | null;
}

export interface MessageDeltaEvent extends BaseEvent {
  type: "agent.message.delta";
  text: string;
}

export interface MessageDoneEvent extends BaseEvent {
  type: "agent.message.done";
  message_id: string;
  text: string;
}

export interface ToolUseEvent extends BaseEvent {
  type: "agent.tool_use";
  tool: string;
  input: Record<string, unknown>;
  tool_use_id: string;
}

export interface ToolResultEvent extends BaseEvent {
  type: "tool.result";
  tool_use_id: string;
  output: unknown;
  is_error: boolean;
}

export interface HintRevealedEvent extends BaseEvent {
  type: "hint.revealed";
  item_id: string;
  level: number;
  text: string;
  /** A fraction of the score still on the table, not absolute points. */
  score_penalty: number;
}

export interface ObservationEvent extends BaseEvent {
  type: "observation.recorded";
  concept_id: string;
  signal: "strong" | "shaky" | "wrong";
}

export interface GradingStartedEvent extends BaseEvent {
  type: "grading.started";
  item_id: string;
}

export interface GradingResultEvent extends BaseEvent {
  type: "grading.result";
  item_id: string;
  score: number;
  criteria: { name: string; score: number; note?: string; span?: string }[];
  evidence_written: string[];
}

export interface BudgetWarningEvent extends BaseEvent {
  type: "budget.warning";
  consumed: number;
  limit: number;
  scope: "session" | "day";
}

export interface SessionErrorEvent extends BaseEvent {
  type: "session.error";
  code: string;
  message: string;
  recoverable: boolean;
}

/** Sent when a client resumes from before the buffer starts. Loss, made visible. */
export interface StreamGapEvent extends BaseEvent {
  type: "stream.gap";
  requested_after: number;
  oldest_available: number;
  detail: string;
}

/** The server's 30-minute ceiling on one connection. Reconnecting is lossless. */
export interface StreamTimeoutEvent extends BaseEvent {
  type: "stream.timeout";
  after: number;
  detail: string;
}

export type StreamEvent =
  | SessionStateEvent
  | ItemPresentedEvent
  | MessageDeltaEvent
  | MessageDoneEvent
  | ToolUseEvent
  | ToolResultEvent
  | HintRevealedEvent
  | ObservationEvent
  | GradingStartedEvent
  | GradingResultEvent
  | BudgetWarningEvent
  | SessionErrorEvent
  | StreamGapEvent
  | StreamTimeoutEvent;

/**
 * Every type the server can emit. `EventSource` has no wildcard, so this list
 * is what gets subscribed — a type missing from it is a type silently dropped,
 * which is why it lives next to the definitions above rather than in the hook.
 */
export const EVENT_TYPES = [
  "session.state",
  "item.presented",
  "agent.message.delta",
  "agent.message.done",
  "agent.tool_use",
  "tool.result",
  "hint.revealed",
  "observation.recorded",
  "grading.started",
  "grading.result",
  "budget.warning",
  "session.error",
  "stream.gap",
  "stream.timeout",
] as const satisfies readonly StreamEvent["type"][];
