#!/usr/bin/env bash
# Refuse to touch Docker while it is ambiguous which daemon "docker" means.
#
# This machine runs two: colima (where this project's data volume lives) and Docker
# Desktop (installed 2026-08-27, which quietly took over the active context). On
# 2026-08-29 `make up-stack` followed the ambient context to Desktop's daemon, Postgres
# initialised a brand-new empty volume there, and the jobs page answered 500 with
# `relation "job_applications" does not exist` — while 47 applications sat intact in the
# colima volume, looking deleted. Third incident that presented as data loss; first one
# where nothing was actually lost. The other two were test teardowns (see
# docs/BUILDLOG.md), and each fix guards a different door.
#
# The rule this script enforces:
#
#   - `.docker-context` (gitignored, machine-local) names the daemon this repo's data
#     lives on. The Makefile exports it as DOCKER_CONTEXT, so every docker/compose
#     invocation follows the pin no matter what `docker context use` last said.
#   - With a pin: the pinned context must exist and its daemon must answer.
#   - Without a pin: at most one *distinct* daemon may be reachable. Two contexts often
#     alias one daemon (Desktop's `default` and `desktop-linux`), so daemons are counted
#     by ID, not by context name. One reachable daemon: fine, a fresh machine needs no
#     ceremony. Two: stop and make the choice explicit, because whichever one wins by
#     default is the one that makes the data in the other look deleted.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

pin="$(cat .docker-context 2>/dev/null | tr -d '[:space:]' || true)"

if [[ -n $pin ]]; then
  if ! docker context inspect "$pin" >/dev/null 2>&1; then
    echo "daemon_guard: .docker-context pins '$pin', but no such Docker context exists." >&2
    echo "              docker context ls   — then fix or delete .docker-context" >&2
    exit 1
  fi
  if ! docker --context "$pin" info >/dev/null 2>&1; then
    echo "daemon_guard: the pinned daemon '$pin' is not answering." >&2
    case "$pin" in
      colima*) echo "              start it:  colima start" >&2 ;;
      desktop-linux) echo "              start it:  open -a Docker" >&2 ;;
      *) echo "              start that daemon, or repoint .docker-context" >&2 ;;
    esac
    exit 1
  fi
  exit 0
fi

# No pin. Count distinct reachable daemons across every context.
declare -a reachable=()
declare -a ids=()
for ctx in $(docker context ls -q 2>/dev/null); do
  id="$(docker --context "$ctx" info --format '{{.ID}}' 2>/dev/null || true)"
  if [[ -n $id ]]; then
    reachable+=("$ctx")
    ids+=("$id")
  fi
done

distinct=$(printf '%s\n' "${ids[@]:-}" | sed '/^$/d' | sort -u | wc -l | tr -d ' ')

if (( distinct > 1 )); then
  echo "daemon_guard: ${#reachable[@]} Docker contexts are answering (${reachable[*]})," >&2
  echo "              and they are $distinct different daemons with $distinct different sets of volumes." >&2
  echo "              One of them holds compose_postgres_data — every session and the job list." >&2
  echo "              Whichever the ambient context picks, the other's data looks deleted." >&2
  echo >&2
  echo "              Pin the one this machine's data lives on, e.g.:" >&2
  echo "                  echo colima > .docker-context" >&2
  echo >&2
  echo "              (2026-08-29: the unpinned default cost an afternoon — docs/INFRA.md#one-daemon-per-machine)" >&2
  exit 1
fi
