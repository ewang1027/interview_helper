#!/usr/bin/env bash
# What is finished but not committed, and what is committed but not pushed.
#
# This is the half of CLAUDE.md's cadence rule that no hook can enforce: a commit that was
# never made fires no trigger, and a branch that is never pushed fails nothing. So it
# reports instead, at the moment the report is worth reading — the end of `make check`,
# which is what gets run when a unit of work has just been declared good.
#
# Never fails, and never in CI. A nudge that can break a build gets deleted, and the
# failure it warns about (work living only in one working tree) cannot happen there.
set -uo pipefail

if [[ -n ${CI:-} ]]; then
  exit 0
fi
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0
cd "$(git rev-parse --show-toplevel)"

dirty=$(git status --porcelain | wc -l | tr -d ' ')
branch=$(git rev-parse --abbrev-ref HEAD)
upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)

if [[ -z $upstream ]]; then
  echo "hygiene: $dirty uncommitted file(s); '$branch' has no upstream —"
  echo "         git push -u origin $branch"
  exit 0
fi

unpushed=$(git rev-list --count "$upstream..HEAD" 2>/dev/null || echo 0)
if [[ $dirty -eq 0 && $unpushed -eq 0 ]]; then
  echo "hygiene: working tree clean, nothing unpushed"
  exit 0
fi

oldest=$(git log --format=%cr "$upstream..HEAD" 2>/dev/null | tail -1)
echo "hygiene: $dirty uncommitted file(s) · $unpushed commit(s) not on $upstream${oldest:+ (oldest $oldest)}"
echo "         CLAUDE.md: commit at every checkpoint, push after every commit."
if [[ $unpushed -gt 0 ]]; then
  bash scripts/docs_with_code.sh --warn "$upstream..HEAD" || true
fi
exit 0
