"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Badge, Button, Card, CardBody, CardHeader, Skeleton } from "@/components/ui/primitives";
import { probeAuth } from "@/lib/auth-state";

/**
 * The app's own front door.
 *
 * docs/WEB.md says an unauthenticated route "should send the browser to
 * `/auth/login` rather than rendering an error". Doing that literally sends the
 * browser to an *API* route, and when OAuth is not configured that route
 * answers `503 not-configured` — so the user is handed a raw
 * `application/problem+json` document with no way forward. Correct of the
 * server, useless to a person.
 *
 * So the redirect target is this page, and it works out which of three states
 * the deployment is in before showing anything:
 *
 * - **signed in** — go where you were going.
 * - **OAuth configured** — offer the GitHub button, which is the only way in.
 * - **OAuth not configured** — say so, and say what to do about it. Locally
 *   that is `make login`, which is the documented way to get a session without
 *   an OAuth app: it signs a cookie *outside* the server process with the same
 *   secret the server verifies with. There is deliberately no dev-login route
 *   and no `AUTH_MODE` flag ([API.md](../../../docs/API.md)), because a flag is
 *   a thing that can be wrong in production — so this explains the supported
 *   path rather than adding an unsupported one.
 */

export default function Login() {
  const router = useRouter();
  const state = useQuery({ queryKey: ["auth-state"], queryFn: probeAuth, retry: false });

  useEffect(() => {
    if (state.data === "signed-in") router.replace("/");
  }, [state.data, router]);

  return (
    <div className="mx-auto max-w-2xl space-y-6 py-8">
      <div>
        <h1 className="text-ink text-xl font-semibold tracking-tight">Sign in</h1>
        <p className="text-ink-muted mt-0.5 text-sm">
          Every route under <code>/api/v1</code> needs a session cookie.
        </p>
      </div>

      {state.isLoading ? (
        <Skeleton className="h-40" />
      ) : state.data === "not-configured" ? (
        <NotConfigured />
      ) : state.data === "signed-in" ? (
        <Card>
          <CardBody className="pt-4">
            <p className="text-ink-secondary text-sm">Already signed in — taking you back.</p>
          </CardBody>
        </Card>
      ) : (
        <Card>
          <CardBody className="space-y-3 pt-4">
            <p className="text-ink-secondary text-sm">
              This deployment serves one GitHub account.
            </p>
            <Button onClick={() => (window.location.href = "/auth/login")}>
              Sign in with GitHub
            </Button>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

function NotConfigured() {
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Badge tone="warning">not configured</Badge>
            GitHub sign-in is unavailable
          </span>
        }
        hint="The server is refusing to run a weaker version of the login flow, which is correct."
      />
      <CardBody className="space-y-4">
        <p className="text-ink-secondary text-sm">
          <code>GITHUB_CLIENT_ID</code>, <code>GITHUB_CLIENT_SECRET</code> and{" "}
          <code>GITHUB_ALLOWED_ID</code> are unset. An OAuth app without an allowed account
          id would let <em>any</em> GitHub user into a single-user deployment, so{" "}
          <code>/auth/login</code> refuses outright rather than running open.
        </p>

        <div>
          <h3 className="text-ink mb-1.5 text-sm font-medium">Locally: mint a cookie</h3>
          <p className="text-ink-secondary mb-2 text-sm">
            There is no dev-login route and no <code>AUTH_MODE</code> flag on purpose — a
            flag is a thing that can be wrong in production. Instead the cookie is signed{" "}
            <em>outside</em> the server, with the same <code>SESSION_SECRET</code> it
            verifies with:
          </p>
          <pre className="bg-sunken border-hairline overflow-x-auto rounded-md border p-3 text-xs">
            make login
          </pre>
          <p className="text-ink-secondary mt-2 text-sm">
            Then paste the printed value into this page&apos;s console, on this origin:
          </p>
          <pre className="bg-sunken border-hairline overflow-x-auto rounded-md border p-3 text-xs">
            {`document.cookie = "ih_session=<the value make login printed>; path=/";
location.reload();`}
          </pre>
          <p className="text-ink-muted mt-2 text-xs">
            <code>HttpOnly</code> stops JavaScript <em>reading</em> a cookie the server
            set; a cookie you set yourself is still sent, and the server only checks its
            signature.
          </p>
        </div>

        <div>
          <h3 className="text-ink mb-1.5 text-sm font-medium">Properly: configure OAuth</h3>
          <p className="text-ink-secondary text-sm">
            Create a GitHub OAuth app with callback{" "}
            <code>http://localhost:8000/auth/callback</code>, then set the three variables
            above in <code>.env</code> — <code>GITHUB_ALLOWED_ID</code> is your numeric
            GitHub user id, not your username.
          </p>
        </div>
      </CardBody>
    </Card>
  );
}
