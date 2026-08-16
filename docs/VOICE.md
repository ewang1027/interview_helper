# Voice interviews via Vapi

> **Status:** Specification — not started. Lands in **Phase 7**.
> Related: [API](API.md) (the agent core this reuses) · [ARCHITECTURE](ARCHITECTURE.md#the-three-decisions-that-shape-everything-else) (why this is an adapter, not a rewrite)

Voice is where interview prep stops being comfortable. Talking while solving is the skill
most people fail on, and it cannot be trained in a text box. It is nonetheless **Phase 7**,
because everything it needs — the agent core, grading, mastery — must work first.

## Why this is cheap

Vapi accepts **any OpenAI-compatible `/chat/completions` endpoint** as a "custom LLM".
Vapi owns speech-to-text, text-to-speech, turn-taking, barge-in, and telephony; our
backend keeps the interviewer logic.

So the work is an adapter plus an ID mapping — not a second interviewer:

```
  phone / mic
       │
       ▼
   ┌────────┐   POST /v1/chat/completions (stream: true)   ┌──────────────┐
   │  Vapi  │ ──────────────────────────────────────────▶  │  our shim    │
   │ STT/TTS│ ◀──────────── SSE chat.completion.chunk ───── │  → agent core│
   └────────┘                                               └──────────────┘
                                                                   │
                                                        same sessions, grading,
                                                        mastery as the text path
```

This is the payoff from the third architectural decision: the agent core is a function
over `(session state, corpus item, tools) → turn`, and HTTP+SSE and Vapi are both just
adapters over it.

## The shim

`POST /v1/chat/completions` — deliberately outside `/api/v1`, because it is not our API
shape. It exists to look like OpenAI to one caller.

Responsibilities, in order:

1. **Authenticate** the caller (below).
2. **Resolve the session.** Map Vapi's call id to an `interview_helper` session id,
   creating one on first contact for a configured mode and budget.
3. **Translate inbound.** OpenAI `messages[]` → a candidate turn. Vapi resends
   conversation history each request; we trust our own stored transcript over the
   replayed one, and use the inbound only for the newest user message.
4. **Run one agent turn** through the same core the text path uses.
5. **Translate outbound.** Agent text → `chat.completion.chunk` SSE frames, then
   `[DONE]`. Vapi sends `{stream: true}` and accepts SSE or a plain JSON completion;
   we stream, because time-to-first-token is what makes the conversation feel real.

### What changes for voice

The transport is the same; the *interviewing* is not. A voice session sets a distinct
system-prompt profile:

| Text | Voice |
|---|---|
| Code blocks, markdown, long structured answers | Spoken prose, no markdown, no code read aloud |
| Candidate types a solution | Candidate **describes** the approach; code is optional |
| Hints as text | Hints as a spoken nudge, same penalty accounting |
| Response length calibrated to reading | Short turns — a long monologue is unbearable to listen to and blocks barge-in |

**Coding mode over voice grades the explanation, not the code.** The concepts it writes
evidence against are the communication ones — `complexity-communication`,
`clarifying-requirements`, `edge-case-enumeration` — rather than implementation concepts.
That is honest: a phone screen measures whether you can talk about an algorithm, and
pretending otherwise would write misleading evidence.

Quant and behavioral modes translate to voice almost unchanged, and behavioral is
arguably better spoken than typed. Design mode over voice loses the diagram, so its rubric
drops the criteria that depend on the artifact.

## Authentication

Vapi is a server calling us, not a browser, so the OAuth cookie from
[API.md](API.md#auth) does not apply. The shim uses a shared secret:

- A long random token in Secrets Manager, sent by Vapi as a header.
- Verified with a constant-time comparison.
- Rate-limited independently of the browser API.
- The shim route is the **only** unauthenticated-by-cookie path, so it gets its own
  security-group and WAF consideration in [INFRA.md](INFRA.md).

Vapi supports registering credentials for a custom-LLM provider so the token is stored on
their side rather than embedded in a URL. Use that; never put a secret in a query string,
where it lands in access logs.

## Latency budget

The thing that decides whether this feels like a conversation or a bad IVR. Target
**under 1.5s** from end-of-speech to first audio.

| Segment | Owner | Budget |
|---|---|---|
| Endpointing + STT | Vapi | ~300 ms |
| Network to us | — | ~50 ms |
| **Our turn → first token** | **us** | **~700 ms** |
| TTS first audio | Vapi | ~300 ms |

Our 700 ms is the only part we control, and it constrains design:

- **Stream immediately.** No buffering a complete turn before responding.
- **Prompt caching matters more here than anywhere else** — a cache miss on a large
  system prompt is felt as dead air ([COST.md](COST.md#prompt-caching)).
- **No synchronous tool calls on the speaking path.** `run_code` takes seconds; voice
  turns must acknowledge first and report results when they land.

## Gate

A spoken mock interview end to end, in at least quant and behavioral modes, where the
transcript is graded by the same graders as the text path and writes the same evidence
shape. Plus a measured p50 and p95 for our 700 ms segment, recorded in
[BUILDLOG.md](BUILDLOG.md) — a latency claim without numbers is not a gate.

## Open questions for Phase 7

- Whether a voice session should allow a parallel text channel for code, or stay
  voice-only. Real phone screens usually pair voice with a shared editor.
- Whether Vapi's transcript is good enough to grade directly, or whether we re-transcribe
  for the record. Grading on a lossy transcript writes lossy evidence.
- Whether barge-in should interrupt a hint mid-sentence — realistic, but it complicates
  the penalty accounting for a hint that was only half heard.
