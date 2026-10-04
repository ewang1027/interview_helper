import { readFileSync } from "node:fs";
import { join } from "node:path";
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

/**
 * The Monaco version `scripts/vendor-monaco.mjs` vendors under, read the same way it
 * reads it — by path, because monaco-editor's `exports` map does not expose its
 * package.json. Inlined into the client as `MONACO_VERSION` so `coding.tsx` can point
 * the loader at `/monaco/<version>/vs`.
 */
const MONACO_VERSION: string = JSON.parse(
  readFileSync(join(process.cwd(), "node_modules", "monaco-editor", "package.json"), "utf8"),
).version;

const nextConfig: NextConfig = {
  // Emits `.next/standalone` — a self-contained server with only the dependencies it
  // actually imports, so the runtime image carries neither `node_modules` nor the
  // toolchain. docs/INFRA.md step 1.
  output: "standalone",

  env: { MONACO_VERSION },

  /**
   * Monaco cached for a year, not revalidated on every visit. Next serves `public/` with
   * `max-age=0`, which cost every coding session 18 conditional requests for files that
   * cannot change. `immutable` is safe only because the path carries the version:
   * `loader.js` and `editor.js` have no content hash, so an upgrade has to be a new URL.
   */
  async headers() {
    return [
      {
        source: "/monaco/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
    ];
  },

  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` },
      { source: "/auth/:path*", destination: `${API_ORIGIN}/auth/:path*` },
      { source: "/health", destination: `${API_ORIGIN}/health` },
    ];
  },
};

export default nextConfig;
