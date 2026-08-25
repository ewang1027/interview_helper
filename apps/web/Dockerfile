# The web app. docs/INFRA.md step 1.
#
# Built from the **repository root** like the other two, so one compose file can use one
# context and `.dockerignore` is written once.
#
# The runtime stage carries `.next/standalone` — a server with only the dependencies it
# imports — plus `public/` and the static assets. No `node_modules`, no toolchain.

FROM node:22-slim AS build

RUN corepack enable

WORKDIR /app

# Manifests first, for the same layer-caching reason as the Python images.
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/pnpm-store \
    pnpm config set store-dir /pnpm-store && pnpm install --frozen-lockfile

COPY apps/web/ ./

# `prebuild` vendors Monaco into `public/monaco` — the editor is served from this app
# rather than a CDN, so the image has to contain it (docs/WEB.md). Runs as part of
# `pnpm build`; named here because it is the reason `public/` is ~27MB.
RUN pnpm build


FROM node:22-slim AS runtime

# Non-root. The web app holds no secret at all — the session cookie is `HttpOnly` and it
# never reads it — but it is the process facing the browser, so it gets the least it can.
RUN useradd --create-home --uid 10001 app

WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# The three things standalone output needs, and nothing else. `public/` and
# `.next/static` are *not* included in `.next/standalone` and must be copied beside it,
# which is the step whose absence produces a site that renders with no CSS and no editor.
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
COPY --from=build --chown=app:app /app/public ./public

USER app
EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD node -e "require('http').get('http://localhost:3000/',r=>process.exit(r.statusCode<500?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "server.js"]
