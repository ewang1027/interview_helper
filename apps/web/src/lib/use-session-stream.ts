"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { EVENT_TYPES, type StreamEvent } from "./stream";
import { initialStreamState, sessionReducer } from "./session-reducer";

export type Connection = "idle" | "connecting" | "open" | "closed" | "error";

/**
 * Subscribe to a session's live channel.
 *
 * Three things this has to get right, all of them consequences of how the
 * server writes the stream (docs/API.md#sse-event-stream):
 *
 * - **Every frame is named**, so a listener is registered per type from
 *   `EVENT_TYPES`. `onmessage` receives only unnamed frames and would sit
 *   silent for the whole session.
 * - **The stream ends when the session does**, and the server simply closes the
 *   connection. `EventSource` treats a close as a fault and reconnects forever,
 *   so a terminal state has to close it from this side — otherwise a finished
 *   session reopens a stream every few seconds for as long as the tab is open.
 * - **Reconnection is the browser's job.** The server sets `id: <seq>` on every
 *   frame, so `Last-Event-ID` goes back automatically and the server replays.
 *   Nothing here needs to track a resume point; what it does track is whether
 *   anything was *lost*, which the reducer decides.
 */
export function useSessionStream(sessionId: string | null, enabled = true) {
  const [state, dispatch] = useReducer(sessionReducer, initialStreamState);
  const [connection, setConnection] = useState<Connection>("idle");
  const sourceRef = useRef<EventSource | null>(null);

  // Read in the effect without making it a dependency: re-running on every
  // state change would tear the stream down and reopen it on each event.
  const finishedRef = useRef(state.finished);
  finishedRef.current = state.finished;

  useEffect(() => {
    if (!sessionId || !enabled) return;

    const source = new EventSource(`/api/v1/sessions/${sessionId}/events`);
    sourceRef.current = source;
    setConnection("connecting");

    source.onopen = () => setConnection("open");

    const handler = (raw: MessageEvent<string>) => {
      let event: StreamEvent;
      try {
        event = JSON.parse(raw.data) as StreamEvent;
      } catch {
        // A frame this client cannot parse is not a reason to lose the stream.
        return;
      }
      dispatch({ kind: "event", event });
      if (event.type === "session.state") {
        // Closing here, not in a later effect: the reducer's `finished` flag
        // lands a render afterwards, and a reconnect can fire in between.
        const terminal = event.state === "complete" || event.state === "abandoned";
        if (terminal) {
          source.close();
          setConnection("closed");
        }
      }
    };

    for (const type of EVENT_TYPES) source.addEventListener(type, handler as EventListener);

    source.onerror = () => {
      // `EventSource` reports both a dropped connection it will retry and a
      // final close the same way; `readyState` is what separates them.
      if (source.readyState === EventSource.CLOSED) {
        setConnection(finishedRef.current ? "closed" : "error");
      } else {
        setConnection("connecting");
      }
    };

    return () => {
      for (const type of EVENT_TYPES) source.removeEventListener(type, handler as EventListener);
      source.close();
      sourceRef.current = null;
      setConnection("idle");
    };
  }, [sessionId, enabled]);

  /** Record what the candidate said — the server publishes no event for it. */
  const said = useCallback((text: string) => {
    dispatch({ kind: "said", id: `local-${Date.now()}-${Math.random()}`, text });
  }, []);

  return { ...state, connection, said };
}
