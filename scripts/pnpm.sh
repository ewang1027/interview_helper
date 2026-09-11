#!/usr/bin/env bash
# Run the pnpm this repo pins, whatever `pnpm` happens to mean on this machine.
#
# `apps/web/package.json` pins `packageManager: pnpm@<version>` and CI installs that same
# major through `pnpm/action-setup`. A machine whose `pnpm` resolves to anything else does
# not just run a different version — pnpm refuses outright, with ERR_PNPM_BAD_PM_VERSION,
# and every web target fails before it starts.
#
# That is not hypothetical: on this machine `pnpm` is a shim that runs `corepack
# pnpm@latest`, so `make check` had been dying at `check-web` for weeks. The buildlog
# records it as a known local quirk, the web tools were run by hand instead, and the cost
# only became visible on 2026-09-11 — `make check` never reaches `make hygiene`, so it
# never reached the CI-status line either, and the web job was the one that had been red
# for three days.
#
# Usage: scripts/pnpm.sh <args…>   — run from anywhere; always operates in apps/web.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)/apps/web"

pin=$(sed -n 's/.*"packageManager"[[:space:]]*:[[:space:]]*"pnpm@\([0-9][^"]*\)".*/\1/p' package.json)
if [[ -z $pin ]]; then
  echo "pnpm: no packageManager pin in apps/web/package.json — using pnpm from PATH" >&2
  exec pnpm "$@"
fi

# corepack first: it caches the version, so this is a download once and a spawn after.
# npx is the fallback for a machine with no corepack, and costs a registry check.
if command -v corepack >/dev/null 2>&1; then
  export COREPACK_HOME="${COREPACK_HOME:-$HOME/.cache/corepack}"
  exec corepack "pnpm@$pin" "$@"
elif command -v npx >/dev/null 2>&1; then
  exec npx --yes "pnpm@$pin" "$@"
else
  echo "pnpm: neither corepack nor npx found; falling back to pnpm from PATH" >&2
  exec pnpm "$@"
fi
