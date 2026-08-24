/**
 * A recorded coding session's event stream.
 *
 * Shaped exactly as the server writes it (`Event.payload()` in
 * `apps/api/src/api/events.py`): a `type`, a monotonic `seq`, an `at`, and the
 * event's own fields flattened alongside them. docs/WEB.md asks for component
 * tests driven by recorded SSE fixtures so no live backend is needed; this is
 * that recording.
 */

import type { StreamEvent } from "../stream";

export const codingSession: StreamEvent[] = [
  { type: "session.state", seq: 1, at: "2026-08-24T15:00:00Z", state: "briefing" },
  {
    type: "item.presented",
    seq: 2,
    at: "2026-08-24T15:00:01Z",
    item_id: "i.code.0004",
    title: "Longest certifiable stretch of a bottling run",
    statement_md: "Given a run of bottle readings…",
    expected_minutes: 15,
  },
  { type: "agent.message.delta", seq: 3, at: "2026-08-24T15:00:02Z", text: "Take a " },
  { type: "agent.message.delta", seq: 4, at: "2026-08-24T15:00:02Z", text: "look at " },
  { type: "agent.message.delta", seq: 5, at: "2026-08-24T15:00:03Z", text: "this one." },
  {
    type: "agent.message.done",
    seq: 6,
    at: "2026-08-24T15:00:03Z",
    message_id: "m1",
    text: "Take a look at this one.",
  },
  { type: "session.state", seq: 7, at: "2026-08-24T15:00:10Z", state: "interviewing" },
  {
    type: "agent.tool_use",
    seq: 8,
    at: "2026-08-24T15:02:00Z",
    tool: "run_code",
    input: { language: "python", source: "def solve(): ..." },
    tool_use_id: "tu1",
  },
  {
    type: "tool.result",
    seq: 9,
    at: "2026-08-24T15:02:04Z",
    tool_use_id: "tu1",
    output: { outcome: "ok", passed: 6, total: 8 },
    is_error: false,
  },
  {
    type: "hint.revealed",
    seq: 10,
    at: "2026-08-24T15:04:00Z",
    item_id: "i.code.0004",
    level: 1,
    text: "What stays true as the window grows?",
    score_penalty: 0.15,
  },
  {
    type: "observation.recorded",
    seq: 11,
    at: "2026-08-24T15:05:00Z",
    concept_id: "sliding-window",
    signal: "shaky",
  },
  { type: "grading.started", seq: 12, at: "2026-08-24T15:08:00Z", item_id: "i.code.0004" },
  {
    type: "grading.result",
    seq: 13,
    at: "2026-08-24T15:08:30Z",
    item_id: "i.code.0004",
    score: 0.75,
    criteria: [{ name: "hidden tests", score: 0.75 }],
    evidence_written: ["sliding-window", "big-o-analysis"],
  },
  { type: "session.state", seq: 14, at: "2026-08-24T15:09:00Z", state: "complete" },
];
