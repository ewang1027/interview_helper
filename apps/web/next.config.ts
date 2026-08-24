import type { NextConfig } from "next";

/**
 * The web app is served from the same origin as the API, and that is a security
 * decision rather than a convenience.
 *
 * The session cookie is `HttpOnly; SameSite=Lax` and set on the API's origin
 * (docs/API.md#auth). A browser at `localhost:3000` fetching `localhost:8000`
 * is cross-site, so `SameSite=Lax` withholds the cookie — and the API mounts no
 * CORS middleware, so the request never gets that far. The two ways out are
 * relaxing the cookie to `SameSite=None; Secure` plus a CORS allowlist, or
 * putting both behind one origin. This takes the second: the cookie stays
 * first-party and the API keeps no browser-origin allowlist to get wrong.
 *
 * It is also the deployment shape — one ALB routing `/api` and `/auth` to the
 * API service and everything else to this one (docs/INFRA.md), so development
 * and production disagree about hostnames and nothing else.
 */
const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` },
      { source: "/auth/:path*", destination: `${API_ORIGIN}/auth/:path*` },
      { source: "/health", destination: `${API_ORIGIN}/health` },
    ];
  },
};

export default nextConfig;
