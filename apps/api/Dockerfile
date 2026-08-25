# The API service. docs/INFRA.md step 1.
#
# Multi-stage so the runtime image carries the virtualenv and the source, and none of the
# toolchain that built it. `uv` is a build-time dependency, not a runtime one.
#
# Built from the **repository root**, not from this directory: `api` is one member of a uv
# workspace (`pyproject.toml`'s `[tool.uv.workspace]`) and resolving it needs the root
# lockfile and its sibling `packages/corpus`. The compose file sets `context: ../..` for
# that reason.

FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Manifests before source. Docker caches per layer, so a source edit that leaves the
# dependency set alone reuses the resolved environment instead of rebuilding it — the
# difference between a ~2s rebuild and a ~60s one on every iteration.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY apps/executor/pyproject.toml apps/executor/
COPY packages/corpus/pyproject.toml packages/corpus/

# `--no-install-workspace` resolves and installs third-party dependencies only. The
# workspace's own packages are installed in the second pass below, after their source
# arrives, so editing a source file does not invalidate this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace

COPY apps/api apps/api
COPY apps/executor apps/executor
COPY packages/corpus packages/corpus

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

# Non-root. The API holds the database credentials and the session secret; nothing it does
# needs root, and a container that runs as root for no reason is one that hands root to
# whoever finds a way in.
RUN useradd --create-home --uid 10001 app

WORKDIR /app

COPY --from=build --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app
EXPOSE 8000

# `/health` is deliberately outside the `/api/v1` prefix and does no I/O, so it answers
# even when the database is down — which is what a health check must do, or a transient
# database fault becomes an infinite restart loop (docs/API.md).
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
