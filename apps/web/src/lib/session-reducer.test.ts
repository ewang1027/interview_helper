import { describe, expect, it } from "vitest";
import { codingSession } from "./fixtures/coding-session";
import { initialStreamState, sessionReducer, type SessionStreamState } from "./session-reducer";
import type { StreamEvent } from "./stream";

function fold(events: StreamEvent[], from: SessionStreamState = initialStreamState) {
  return events.reduce((state, event) => sessionReducer(state, { kind: "event", event }), from);
}

describe("session reducer", () => {
  it("folds a whole recorded session", () => {
    const state = fold(codingSession);

    expect(state.state).toBe("complete");
    expect(state.finished).toBe(true);
    expect(state.item?.item_id).toBe("i.code.0004");
    expect(state.hints).toHaveLength(1);
    expect(state.observations[0]?.concept_id).toBe("sliding-window");
    expect(state.gradings["i.code.0004"]?.score).toBe(0.75);
    expect(state.lastSeq).toBe(14);
    expect(state.gaps).toHaveLength(0);
  });

  it("renders deltas optimistically, then defers to done", () => {
    // Two of the three deltas in, well before `agent.message.done`.
    const midStream = fold(codingSession.slice(0, 4));
    expect(midStream.streaming).toBe("Take a look at ");
    expect(midStream.entries).toHaveLength(0);

    const settled = fold(codingSession.slice(0, 6));
    expect(settled.streaming).toBe("");
    expect(settled.entries).toEqual([
      { kind: "agent", id: "m1", text: "Take a look at this one." },
    ]);
  });

  it("takes the done payload as authoritative when a delta was dropped", () => {
    // The same stream with one delta missing, exactly as a lossy connection
    // would deliver it. The rendered text must still be correct.
    const lossy = codingSession.filter((event) => event.seq !== 4);
    const state = fold(lossy);

    const agentMessages = state.entries.filter((entry) => entry.kind === "agent");
    expect(agentMessages[0]).toMatchObject({ text: "Take a look at this one." });
  });

  it("notices a sequence jump the server never reported", () => {
    // The server only checks for a gap once, at stream open, so events evicted
    // from its 256-slot buffer mid-session arrive as a silent jump.
    const lossy = codingSession.filter((event) => event.seq !== 4);
    const state = fold(lossy);

    expect(state.gaps).toHaveLength(1);
    expect(state.gaps[0]).toMatchObject({ after: 3, resumedAt: 5, source: "client" });
  });

  it("records a server-sent gap without inventing a second one", () => {
    const state = fold([
      { type: "session.state", seq: 1, at: "t", state: "interviewing" },
      {
        type: "stream.gap",
        seq: 40,
        at: "t",
        requested_after: 2,
        oldest_available: 39,
        detail: "Events between those points are gone; refetch the session.",
      },
    ] as StreamEvent[]);

    expect(state.gaps).toHaveLength(1);
    expect(state.gaps[0]?.source).toBe("server");
  });

  it("attaches a tool result to the call it answers", () => {
    const state = fold(codingSession);
    const tool = state.entries.find((entry) => entry.kind === "tool");

    expect(tool).toMatchObject({
      tool: "run_code",
      isError: false,
      output: { outcome: "ok", passed: 6, total: 8 },
    });
  });

  it("does not treat a timeout as loss", () => {
    const state = fold([
      { type: "session.state", seq: 1, at: "t", state: "interviewing" },
      { type: "stream.timeout", seq: 2, at: "t", after: 1, detail: "Reconnect." },
    ] as StreamEvent[]);

    expect(state.gaps).toHaveLength(0);
    expect(state.finished).toBe(false);
  });

  it("does not rewind lastSeq when a reconnect replays events", () => {
    const state = fold(codingSession);
    const replayed = fold(codingSession.slice(8), state);

    expect(replayed.lastSeq).toBe(14);
    expect(replayed.gaps).toHaveLength(0);
  });

  it("keeps a budget warning as standing state", () => {
    const state = fold([
      ...codingSession.slice(0, 3),
      { type: "budget.warning", seq: 99, at: "t", consumed: 380_000, limit: 400_000, scope: "session" },
    ] as StreamEvent[]);

    expect(state.budgetWarning).toMatchObject({ scope: "session", consumed: 380_000 });
  });

  it("clears a half-generated sentence when a new item is presented", () => {
    const mid = fold(codingSession.slice(0, 5));
    const next = sessionReducer(mid, {
      kind: "event",
      event: {
        type: "item.presented",
        seq: 6,
        at: "t",
        item_id: "i.code.0007",
        title: "Another",
        statement_md: "…",
        expected_minutes: 15,
      },
    });

    expect(next.streaming).toBe("");
    expect(next.item?.item_id).toBe("i.code.0007");
  });

  it("records what the candidate said, which the server never publishes", () => {
    const state = sessionReducer(initialStreamState, {
      kind: "said",
      id: "local-1",
      text: "I'd use a sliding window.",
    });

    expect(state.entries).toEqual([
      { kind: "candidate", id: "local-1", text: "I'd use a sliding window." },
    ]);
  });
});
