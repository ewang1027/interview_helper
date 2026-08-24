#!/usr/bin/env bash
# Run the API and the web app together, until Ctrl-C stops both.
#
# `make dev-api` and `make dev-web` each block, so bringing the stack up meant two
# terminals and remembering the order. That is friction on the operation performed most
# often — and the one a person asks about when they wonder whether restarting is safe.
#
# Both children are killed on exit, including on Ctrl-C. Without the trap, interrupting
# this leaves a uvicorn holding :8000 and a next-server holding :3000, and the next
# `make up` fails on a port already in use — which looks like a broken repo rather than a
# stray process.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

api_port=${API_PORT:-8000}
web_port=${WEB_PORT:-3000}

# `sed -l` is BSD's line-buffered flag (GNU spells it `-u`). Without it the prefixed
# output sits in a 4KB block buffer and a dev server appears to have hung on startup.
prefix() { sed -l "s/^/[$1] /"; }

pids=()
cleanup() {
  trap - EXIT INT TERM
  for pid in "${pids[@]:-}"; do
    [[ -n ${pid:-} ]] && kill "$pid" 2>/dev/null
  done
  # The pipelines run children of their own; killing the group catches those too.
  pkill -P $$ 2>/dev/null
  wait 2>/dev/null
  echo
  echo "dev_up: stopped. Postgres is still running — 'make down' stops that too."
}
trap cleanup EXIT INT TERM

echo "dev_up: api on :$api_port, web on :$web_port — Ctrl-C stops both"
echo

{ uv run uvicorn api.main:app --reload --app-dir apps/api/src --port "$api_port" 2>&1 | prefix api; } &
pids+=($!)
{ cd apps/web && pnpm dev --port "$web_port" 2>&1 | prefix web; } &
pids+=($!)

wait
