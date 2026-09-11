#!/usr/bin/env bash
# What the remote gate said about work that has already left this machine.
#
# `make check` is the gate that gets read here, and it is not the gate that runs. On
# 2026-09-11 that difference cost three days: CI had been red since 2026-09-09 on an
# advisory the local checks do not look at, three waves were written in that window, and
# every one of them recorded its local gates honestly. Nothing in the repo knew.
#
# So this reports, at the end of `make check`, what the last run on this branch concluded
# — beside `commit_hygiene.sh`, which reports the work that has not got that far yet.
#
# Report mode never fails. It is a nudge, and a nudge that can break a build gets deleted;
# it also cannot tell a broken build from an expired `gh` token, and the second must not
# look like the first. `--watch` is the opposite case — it is asked for explicitly, about
# a run whose verdict is the answer — so it exits with the run's own conclusion.
#
# Usage:
#   ci_status.sh                 the newest CI run on the current branch
#   ci_status.sh <commit-ish>    the newest run for that exact commit, if there is one
#   ci_status.sh --watch         wait for HEAD's run to finish; exit with its conclusion
set -uo pipefail

WORKFLOW="CI"
POLL_SECONDS=10       # how long any single gh call may take before it is abandoned
APPEAR_TIMEOUT=180    # --watch: how long to wait for a pushed commit's run to be created

watch=0
target=""
for arg in "$@"; do
  case "$arg" in
    --watch) watch=1 ;;
    -*) echo "ci: unknown option $arg" >&2; exit 2 ;;
    *) target="$arg" ;;
  esac
done

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0
cd "$(git rev-parse --show-toplevel)"

# Skipped in CI: the run asking how the run went is a loop, and the answer is "it is
# running". The same reason commit_hygiene.sh bows out there.
if [[ -n ${CI:-} && $watch -eq 0 ]]; then
  exit 0
fi

skip() {  # a reason this cannot answer, which is not the same as a red build
  echo "ci: $1"
  [[ $watch -eq 1 ]] && exit 2
  exit 0
}

command -v gh >/dev/null 2>&1 || skip "gh not installed — remote gate unread"

# Every gh call is wrapped: a hung network call inside `make check` is exactly the failure
# this script is not allowed to be. Backgrounded with a deadline rather than `timeout`,
# which macOS does not ship.
gh_out=""
gh_try() {
  local secs=$1; shift
  local tmp waited pid rc
  tmp=$(mktemp -t ci_status)
  ( "$@" >"$tmp" 2>/dev/null ) &
  pid=$!
  waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if (( waited >= secs )); then
      kill -TERM "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      rm -f "$tmp"
      gh_out=""
      return 124
    fi
    sleep 1
    waited=$((waited + 1))
  done
  wait "$pid"
  rc=$?
  gh_out=$(cat "$tmp")
  rm -f "$tmp"
  return $rc
}

gh_try 5 gh auth status || skip "gh is not signed in (gh auth login) — remote gate unread"

branch=$(git rev-parse --abbrev-ref HEAD)
head_sha=$(git rev-parse HEAD)

# --watch resolves its own target: the commit in the working tree, whose run is the one
# the person who just pushed is waiting on.
if [[ $watch -eq 1 ]]; then
  target=$head_sha
elif [[ -n $target ]]; then
  target=$(git rev-parse "$target" 2>/dev/null) || skip "no such commit: $target"
fi

fields="databaseId,headSha,status,conclusion,displayTitle,url,createdAt"

find_run() {  # newest run on the branch, narrowed to $target when one was named
  local args=(gh run list --workflow "$WORKFLOW" --branch "$branch" --limit 1 --json "$fields")
  # `--commit` asks the API for that sha rather than filtering a page of recent runs,
  # so naming an old commit answers about that commit instead of answering "no run".
  [[ -n $target ]] && args+=(--commit "$target")
  gh_try "$POLL_SECONDS" "${args[@]}" || return 1
  if [[ -z $gh_out || $gh_out == "[]" ]]; then
    return 1
  fi
  printf '%s' "$gh_out" | python3 -c '
import json, sys
runs = json.load(sys.stdin)
print(json.dumps(runs[0]) if runs else "")
'
}

field() { printf '%s' "$1" | python3 -c '
import json, sys
run = json.load(sys.stdin)
print(run.get(sys.argv[1], "") or "")
' "$2"; }

# ── watch ────────────────────────────────────────────────────────────────────────────
if [[ $watch -eq 1 ]]; then
  short=$(git rev-parse --short HEAD)
  waited=0
  run=""
  while :; do
    run=$(find_run) || run=""
    [[ -n $run ]] && break
    if (( waited >= APPEAR_TIMEOUT )); then
      echo "ci: no run for $short after ${APPEAR_TIMEOUT}s — pushed? (events do get dropped:"
      echo "    the workflow has a workflow_dispatch trigger for exactly that)"
      exit 2
    fi
    sleep 5
    waited=$((waited + 5))
  done
  id=$(field "$run" databaseId)
  echo "ci: watching run $id for $short on $branch"
  gh run watch "$id" --exit-status --interval 15
  exit $?
fi

# ── report ───────────────────────────────────────────────────────────────────────────
run=$(find_run) || run=""
if [[ -z $run ]]; then
  if [[ -n $target ]]; then
    echo "ci: no $WORKFLOW run for $(git rev-parse --short "$target") on $branch"
  else
    echo "ci: no $WORKFLOW run on $branch yet"
  fi
  exit 0
fi

id=$(field "$run" databaseId)
sha=$(field "$run" headSha)
status=$(field "$run" status)
conclusion=$(field "$run" conclusion)
short=${sha:0:7}

# How far back the run's commit is from what is in the working tree now — the difference
# between "the gate passed on this" and "the gate passed on something older".
behind=$(git rev-list --count "$sha..$head_sha" 2>/dev/null || echo "")
if [[ $sha == "$head_sha" ]]; then
  where="HEAD"
elif [[ -n $behind && $behind != 0 ]]; then
  where="$behind commit(s) behind HEAD"
else
  where="not an ancestor of HEAD"
fi

case "$status" in
  completed)
    case "$conclusion" in
      success)
        echo "ci: $branch green at $short ($where)"
        ;;
      *)
        echo "ci: $branch ${conclusion:-failed} at $short ($where)"
        if gh_try "$POLL_SECONDS" gh run view "$id" --json jobs; then
          printf '%s' "$gh_out" | python3 -c '
import json, sys
done = ("success", "skipped", None)
for job in json.load(sys.stdin).get("jobs", []):
    if job.get("conclusion") in done:
        continue
    steps = [s.get("name", "?") for s in job.get("steps", [])
             if s.get("conclusion") not in done]
    detail = " — " + steps[0] if steps else ""
    print("    " + job.get("name", "?") + detail)
'
        fi
        echo "    gh run view $id --log-failed"
        ;;
    esac
    ;;
  *)
    echo "ci: $branch ${status:-running} at $short ($where)"
    echo "    gh run watch $id     (or make ci-watch)"
    ;;
esac
exit 0
