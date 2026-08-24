/**
 * The live session state, folded from the event stream.
 *
 * Pure and separate from `EventSource` on purpose: docs/WEB.md asks for
 * component tests driven by recorded SSE fixtures, and a reducer that knows
 * nothing about the transport can be handed a recorded array and asserted on
 * without a backend, a network, or a fake timer.
 *
 * Two rules from docs/API.md are kept here rather than in the view:
 *
 * - **`agent.message.done` is authoritative over the deltas.** Deltas are a
 *   rendering convenience; a client that drops one must not be left with
 *   corrupted text. The buffer is *replaced* by the done payload, never
 *   appended to it.
 * - **A gap is visible.** `seq` is monotonic and gap-free, so a jump means the
 *   client lost events. The server sends `stream.gap` when a *resume point* has
 *   fallen out of its buffer — but that check runs once, at stream open, and a
 *   single turn can emit more events than the 256-slot buffer holds. So a jump
 *   is also detected here, mid-stream, where the server cannot see it.
 */

import type {
  BudgetWarningEvent,
  GradingResultEvent,
  HintRevealedEvent,
  ItemPresentedEvent,
  ObservationEvent,
  SessionErrorEvent,
  StreamEvent,
} from "./stream";
import type { SessionState } from "./types";
import { REPORTABLE } from "./types";

export type TranscriptEntry =
  | { kind: "candidate"; id: string; text: string }
  | { kind: "agent"; id: string; text: string }
  | {
      kind: "tool";
      id: string;
      tool: string;
      input: Record<string, unknown>;
      output?: unknown;
      isError?: boolean;
    };

export interface Gap {
  /** Where the client had got to. */
  after: number;
  /** The lowest sequence it was actually given next. */
  resumedAt: number;
  detail: string;
  /** Told by the server at stream open, or noticed here mid-stream. */
  source: "server" | "client";
}

export interface SessionStreamState {
  state: SessionState | null;
  item: ItemPresentedEvent | null;
  entries: TranscriptEntry[];
  /** Text of the turn currently being generated. Empty between turns. */
  streaming: string;
  hints: HintRevealedEvent[];
  observations: ObservationEvent[];
  /** Per item: `null` while grading, the result once it lands. */
  gradings: Record<string, GradingResultEvent | null>;
  /** Persists as a banner, per docs/WEB.md — it is not a toast. */
  budgetWarning: BudgetWarningEvent | null;
  error: SessionErrorEvent | null;
  gaps: Gap[];
  lastSeq: number;
  /** True once no further event can arrive, so the stream should be closed. */
  finished: boolean;
}

export const initialStreamState: SessionStreamState = {
  state: null,
  item: null,
  entries: [],
  streaming: "",
  hints: [],
  observations: [],
  gradings: {},
  budgetWarning: null,
  error: null,
  gaps: [],
  lastSeq: 0,
  finished: false,
};

export type StreamAction =
  | { kind: "event"; event: StreamEvent }
  /** The candidate's own turn. The server publishes no event for it. */
  | { kind: "said"; id: string; text: string }
  | { kind: "reset" };

export function sessionReducer(
  state: SessionStreamState,
  action: StreamAction,
): SessionStreamState {
  if (action.kind === "reset") return initialStreamState;

  if (action.kind === "said") {
    return {
      ...state,
      entries: [...state.entries, { kind: "candidate", id: action.id, text: action.text }],
    };
  }

  const event = action.event;

  // Loss detection, before anything else looks at the event. `seq` is
  // gap-free by contract, so anything but +1 means events went missing —
  // and a replay after a reconnect legitimately starts wherever the server
  // could resume, which `stream.gap` reports separately.
  let gaps = state.gaps;
  const expected = state.lastSeq + 1;
  if (state.lastSeq > 0 && event.seq > expected && event.type !== "stream.gap") {
    gaps = [
      ...gaps,
      {
        after: state.lastSeq,
        resumedAt: event.seq,
        detail: `${event.seq - expected} event(s) were lost before this point.`,
        source: "client",
      },
    ];
  }

  const next: SessionStreamState = {
    ...state,
    gaps,
    // Never move backwards: a replay can re-deliver events already folded in.
    lastSeq: Math.max(state.lastSeq, event.seq),
  };

  switch (event.type) {
    case "session.state":
      return {
        ...next,
        state: event.state,
        finished: (REPORTABLE as readonly string[]).includes(event.state),
      };

    case "item.presented":
      // A new problem ends whatever was mid-generation; keeping a half-rendered
      // sentence from the previous item would attach it to this one.
      return { ...next, item: event, streaming: "" };

    case "agent.message.delta":
      return { ...next, streaming: next.streaming + event.text };

    case "agent.message.done":
      // Authoritative. The buffer is discarded rather than reconciled against,
      // which is the only handling that survives a dropped delta.
      return {
        ...next,
        streaming: "",
        entries: [...next.entries, { kind: "agent", id: event.message_id, text: event.text }],
      };

    case "agent.tool_use":
      return {
        ...next,
        entries: [
          ...next.entries,
          { kind: "tool", id: event.tool_use_id, tool: event.tool, input: event.input },
        ],
      };

    case "tool.result":
      return {
        ...next,
        entries: next.entries.map((entry) =>
          entry.kind === "tool" && entry.id === event.tool_use_id
            ? { ...entry, output: event.output, isError: event.is_error }
            : entry,
        ),
      };

    case "hint.revealed":
      return { ...next, hints: [...next.hints, event] };

    case "observation.recorded":
      return { ...next, observations: [...next.observations, event] };

    case "grading.started":
      return { ...next, gradings: { ...next.gradings, [event.item_id]: null } };

    case "grading.result":
      return { ...next, gradings: { ...next.gradings, [event.item_id]: event } };

    case "budget.warning":
      return { ...next, budgetWarning: event };

    case "session.error":
      return { ...next, error: event };

    case "stream.gap":
      return {
        ...next,
        gaps: [
          ...next.gaps,
          {
            after: event.requested_after,
            resumedAt: event.oldest_available,
            detail: event.detail,
            source: "server",
          },
        ],
      };

    case "stream.timeout":
      // Not loss: the server's connection ceiling. The browser reconnects with
      // `Last-Event-ID` and carries on, so nothing is shown to the user.
      return next;

    default: {
      // Exhaustiveness: a new event type added to the union fails the build here
      // rather than being silently ignored at runtime.
      event satisfies never;
      return state;
    }
  }
}
