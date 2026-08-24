import { api } from "./api";

/**
 * Which of three states this deployment's sign-in is in.
 *
 * `/login` needs this because sending an unauthenticated browser straight to
 * `/auth/login` — what docs/WEB.md literally asks for — dead-ends whenever
 * OAuth is unconfigured: that route answers `503 not-configured` and the user
 * is handed raw `application/problem+json`. Correct of the server, useless to
 * a person.
 */
export type AuthState = "signed-in" | "ready" | "not-configured" | "unknown";

export async function probeAuth(): Promise<AuthState> {
  try {
    await api.me();
    return "signed-in";
  } catch {
    /* not signed in — work out whether signing in is even possible */
  }

  try {
    // `redirect: "manual"` is what makes this readable. A configured server
    // answers a 3xx toward GitHub, which surfaces as an opaque response rather
    // than a cross-origin fetch that would throw; an unconfigured one answers a
    // 503 this can actually read.
    const response = await fetch("/auth/login", { redirect: "manual", credentials: "include" });
    if (response.type === "opaqueredirect" || response.status === 0) return "ready";
    if (response.status === 503) return "not-configured";
    if (response.ok) return "ready";
    return "unknown";
  } catch {
    return "unknown";
  }
}
