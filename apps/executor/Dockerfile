# The executor service. docs/INFRA.md step 1.
#
# **This image contains the Docker CLI and its container is given the host's Docker
# socket, which is root-equivalent control of the host.** That is not an oversight; it is
# the local model docs/ARCHITECTURE.md ("Where the sandbox actually lives") settled on,
# and the reasoning is worth repeating where somebody editing this file will see it:
#
#   - The executor is a **launcher**. It never evaluates candidate code in its own
#     process — it starts a throwaway container and reads the result over a pipe.
#   - It holds the socket **and no other credential**. No database URL, no model key, no
#     AWS role. Compromising it buys the host, which is bad, but buys nothing else here.
#   - It does not survive to production. Fargate supports neither host bind mounts nor
#     `devices`, and every task has its own kernel — so there is no socket to mount and
#     nothing to launch. There the task *itself* is the boundary and this whole path is
#     replaced, not adapted. `sandbox.run_sandboxed` is the seam.
#
# What makes socket-sharing work at all here: the sandbox passes source on **stdin** and
# mounts only `--tmpfs`. A sibling container started through the host daemon therefore
# needs no path from *this* container's filesystem — which is exactly what would break if
# the source were bind-mounted instead.

FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY apps/executor/pyproject.toml apps/executor/
COPY packages/corpus/pyproject.toml packages/corpus/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace

COPY apps/api apps/api
COPY apps/executor apps/executor
COPY packages/corpus packages/corpus

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

# The Docker *CLI* only — not the daemon. `sandbox.py` shells out to `docker run`,
# `kill`, `rm` and `inspect`, and talks to the host's daemon over the mounted socket.
#
# Copied from the official CLI image rather than installed with apt, and pinned. Debian's
# packaging of this moves: on trixie, `apt-get install docker.io` succeeds and installs
# **only `docker-init`** — no `/usr/bin/docker` at all — so every execution came back
# `harness_error: could not launch docker: [Errno 2] No such file or directory`. A build
# that succeeds while omitting the one binary the service exists to call is exactly the
# failure a pinned copy avoids.
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app

COPY --from=build /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Runs as root, and only because the mounted socket is owned by root on the host and its
# gid differs between Linux and Colima — so a fixed `--group-add` would work on one and
# not the other. It is the one service where that trade is acceptable: it holds no
# credential, and anything with the socket already has root on the host whatever uid it
# runs as. Under Fargate this image loses the socket and the CLI entirely.
EXPOSE 8081

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8081/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "executor.main:app", "--host", "0.0.0.0", "--port", "8081"]
