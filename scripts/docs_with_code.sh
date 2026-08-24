#!/usr/bin/env bash
# Documentation travels with the code that changed it, or the push is refused.
#
# CLAUDE.md's standing rule is that a unit of work is not done until its documentation
# is, and that the doc change belongs in the *same commit* as the code rather than in a
# follow-up that may never come. Discipline held for 22 of the first 25 commits; the three
# that slipped are why this exists. It is a backstop for the rule, not the rule.
#
# Usage:
#   scripts/docs_with_code.sh [--warn] [<rev-range>...]
#
# With no range, checks whatever is not yet on the upstream branch. `--warn` reports and
# exits 0, which is how `make hygiene` uses it. Exempt, deliberately:
#   - `wip:` commits — a checkpoint is not a unit of work (CLAUDE.md, cadence)
#   - merge commits — they introduce no content of their own
#   - a bot's dependency bump touching nothing but manifests — see BOT_* below
#   - ALLOW_UNDOCUMENTED=1 — the deliberate exception, typed out where it is visible
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

warn=0
if [[ ${1:-} == "--warn" ]]; then
  warn=1
  shift
fi

if [[ ${ALLOW_UNDOCUMENTED:-0} == "1" ]]; then
  echo "docs_with_code: skipped (ALLOW_UNDOCUMENTED=1)"
  exit 0
fi

ranges=("$@")
if [[ ${#ranges[@]} -eq 0 ]]; then
  upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)
  if [[ -z $upstream ]]; then
    echo "docs_with_code: no upstream branch, nothing to compare against"
    exit 0
  fi
  ranges=("$upstream..HEAD")
fi

# Behaviour lives in all of these. The gates count too — `scripts/`, `hooks/`, `.github/`,
# the Makefile — because every commit in this repo's history that changed code and no
# document was a change to a gate, and a gate that changes silently is precisely the thing
# a reader of the docs has no other way to learn about.
CODE_RE='^(apps|packages|scripts|infra|hooks|\.github)/|^(Makefile|pyproject\.toml)$'
DOC_RE='\.md$'

# A dependency bump opened by a bot cannot satisfy this gate: it changes a manifest and a
# lockfile, both under `apps/`, and a bot has no document to write. Before this exemption
# every Dependabot pull request was red on arrival — and a gate that is always red for a
# whole class of change is one people learn to merge past, which costs more than it saves.
#
# Kept as narrow as it can be: the author must be a bot *and* every file in the commit
# must be a manifest or a lockfile. A bot commit touching one line of source is still
# refused, and a human bumping a dependency still owes the doc — as the 15.5.20 → 15.5.23
# bump did, which is recorded in docs/SECURITY.md precisely because it was not routine.
BOT_AUTHOR_RE='^(dependabot|renovate|github-actions)(\[bot\])?$'
BOT_FILES_RE='(^|/)(package\.json|package-lock\.json|pnpm-lock\.yaml|pnpm-workspace\.yaml|yarn\.lock|uv\.lock|poetry\.lock)$'

undocumented=()
inspected=0
for range in "${ranges[@]}"; do
  # Unquoted on purpose: the pre-push hook passes `<sha> --not --remotes=<remote>` for a
  # branch the remote has never seen, which is several words. The words come from git.
  # shellcheck disable=SC2086
  if ! commits=$(git rev-list --no-merges $range 2>&1); then
    # Not swallowed. A range this cannot resolve listed no commits, found no violations
    # and reported itself clean — which is how a gate passes vacuously and stops being
    # one. The first draft of this script did exactly that, and a test caught it.
    echo "docs_with_code: cannot resolve range '$range': $commits" >&2
    exit 1
  fi
  for sha in $commits; do
    if [[ $(git log -1 --format=%s "$sha") == wip:* ]]; then
      continue
    fi
    # `-c core.quotepath=false` for the same reason it is set below.
    sha_files=$(git -c core.quotepath=false diff-tree --no-commit-id --name-only -r "$sha")
    if [[ $(git log -1 --format=%an "$sha") =~ $BOT_AUTHOR_RE ]] &&
      ! grep -qvE "$BOT_FILES_RE" <<<"$sha_files"; then
      echo "docs_with_code: exempt (bot dependency bump) $(git log -1 --format='%h %s' "$sha")"
      continue
    fi
    inspected=$((inspected + 1))
    # `-c core.quotepath=false` (set where `sha_files` is built): with the default, git
    # wraps any path containing a non-ASCII byte in double quotes and C-escapes it, so
    # `CODE_RE`'s `^` anchor never matched and a code-only commit touching such a path
    # passed the gate.
    files=$sha_files
    if grep -qE "$CODE_RE" <<<"$files" && ! grep -qE "$DOC_RE" <<<"$files"; then
      undocumented+=("$(git log -1 --format='%h %s' "$sha")")
    fi
  done
done

if [[ ${#undocumented[@]} -eq 0 ]]; then
  echo "docs_with_code: clean ($inspected commit(s) inspected)"
  exit 0
fi

{
  echo "docs_with_code: ${#undocumented[@]} commit(s) change code and no documentation:"
  printf '  %s\n' "${undocumented[@]}"
  echo
  echo "Docs land in the same commit as the code (CLAUDE.md). Either amend the commit"
  echo "with the doc change — docs/BUILDLOG.md is owed one for any behaviour change —"
  echo "or, if this genuinely needs none:"
  echo
  echo "    ALLOW_UNDOCUMENTED=1 git push"
} >&2

[[ $warn -eq 1 ]] && exit 0
exit 1
