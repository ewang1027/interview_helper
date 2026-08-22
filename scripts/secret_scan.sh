#!/usr/bin/env bash
# Greps for common secret shapes before they ever leave a machine. Backstop for GitHub's
# own secret scanning (which only sees a push after it lands), not a replacement for it —
# see docs/SECURITY.md.
#
# Two modes, and the second one is the reason this file was rewritten:
#
#   secret_scan.sh                 scan the working tree (tracked files)
#   secret_scan.sh <range>...      scan every line ADDED by the commits in those ranges
#
# The working-tree scan alone is close to useless against the most common accident there
# is: paste a key, commit, notice, `git rm`, commit the fix, push. The tree is clean at
# push time and both commits reach a public remote. The pre-push hook passes its ranges,
# so what is being published is what gets read.
set -euo pipefail

# Two groups, because the placeholder allowlist must not apply to both.
#
# HARD: shapes that are a credential or nothing. A real one of these is never a
# placeholder, so no allowlist is consulted — otherwise the literal string "example"
# anywhere on the line would disarm the check.
HARD_PATTERNS=(
  '(AKIA|ASIA)[0-9A-Z]{16}'                              # AWS access key id
  'sk-ant-[A-Za-z0-9_-]{20,}'                            # Anthropic
  'sk-(proj-)?[A-Za-z0-9_-]{40,}'                        # OpenAI
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'                   # RSA/EC/OPENSSH/DSA/ENCRYPTED
  '(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}'                # GitHub tokens
  'github_pat_[A-Za-z0-9_]{22,}'                         # GitHub fine-grained PAT
  'xox[baprs]-[A-Za-z0-9-]{10,}'                         # Slack
  '[sr]k_(live|test)_[A-Za-z0-9]{20,}'                   # Stripe
  'AIza[A-Za-z0-9_-]{35}'                                # Google API key
  'eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.'       # JWT with a real payload
)

# SOFT: a name assigned a value. These legitimately appear with inert values in
# .env.example, in tests, and in docs, so the allowlist below applies to them.
# The value class refuses a `${VAR}` reference and a trailing comment, so a name with no
# value — `# SESSION_SECRET=` — is documentation and does not fire. A gate that cries
# wolf on its own example file gets disabled within a week.
SOFT_PATTERNS=(
  'aws_secret_access_key[[:space:]]*[=:][[:space:]]*.?[A-Za-z0-9/+=]{40}'
  '(SESSION_SECRET|GITHUB_CLIENT_SECRET|ANTHROPIC_API_KEY|VAPI_API_KEY|VAPI_WEBHOOK_SECRET)[[:space:]]*[=:][[:space:]]*.?[^'"'"'"[:space:]$#]{12,}'
  '(postgres|postgresql|mysql|mongodb|redis|amqp)(\+[a-z0-9]+)?://[^:@/[:space:]]+:[^@/[:space:]]+@'
)

# ERE via the platform regcomp, so **no GNU extensions**: `\s` and `\b` are both absent on
# BSD/macOS. The previous version used `\s`, which degraded to a literal `s` locally while
# matching whitespace on CI — the gate that runs *before* publication was the weaker one.
# Rewriting it, an adversarial test showed `\b` failing exactly the same way and silently
# disarming six of the ten HARD patterns. Word boundaries are simply omitted: matching a
# key embedded in a longer token is a false positive worth having.
hard_re=$(IFS='|'; echo "${HARD_PATTERNS[*]}")
soft_re=$(IFS='|'; echo "${SOFT_PATTERNS[*]}")

# Known-safe literals. This list is where a real leak would hide, so each entry is a
# *shape that announces itself as inert*, never a path and never a specific file:
#   - a connection string pointing at a local/compose host (the dev DATABASE_URL's
#     password is the string "interview" on localhost)
#   - a value that says in its own text that it is a placeholder or a test fixture
ALLOW_RE='@(localhost|127\.0\.0\.1|postgres|db):|(tests?-only|example|placeholder|changeme|dummy|fake|redacted|your-|xxxx)'

# Paths excluded by exact name, never by wildcard. `:!*.example` matched any depth, which
# exempted .env.example — the one tracked file that enumerates every secret this service
# has by name, and the file CLAUDE.md requires you to edit for each new Settings field.
# Filled in with real values it scanned clean.
EXCLUDES=(':!scripts/secret_scan.sh' ':!uv.lock' ':!pnpm-lock.yaml')

report() {
  echo "secret_scan: possible secret matched — review before committing/pushing:" >&2
  echo "$1" >&2
  exit 1
}

# HARD hits stand on their own; SOFT hits are filtered through the allowlist.
scan() {
  local corpus="$1" label="$2" hard soft
  hard=$(printf '%s\n' "$corpus" | grep -inE "$hard_re" || true)
  soft=$(printf '%s\n' "$corpus" | grep -inE "$soft_re" | grep -vEi "$ALLOW_RE" || true)
  local hits
  hits=$(printf '%s\n%s\n' "$hard" "$soft" | grep -v '^$' || true)
  [[ -n "$hits" ]] && report "$label"$'\n'"$hits"
  return 0
}

# No `2>/dev/null || true` around git anywhere below. It turned every git failure —
# running outside a repo, a broken git — into "clean", and `secret_scan: clean` is quoted
# in this repo's build log as evidence. That line has to mean the scan ran.
tree=$(git grep -In '' -- "${EXCLUDES[@]}")
scan "$tree" "in the working tree:"

if [[ $# -eq 0 ]]; then
  echo "secret_scan: clean (working tree)"
  exit 0
fi

# `git log -p` shows each commit's own diff, so a file added in one commit and deleted in
# the next still presents its addition here. Added lines only: a line being *removed* is
# the fix, not the leak, and flagging it would make every cleanup commit unpushable.
added=$(git log -p --no-merges --no-color --unified=0 "$@" -- "${EXCLUDES[@]}" \
  | grep -E '^\+' | grep -vE '^\+\+\+' || true)
scan "$added" "in a commit being pushed (the working tree may already be clean):"

commits=$(git rev-list --no-merges "$@" | wc -l | tr -d ' ')
echo "secret_scan: clean (working tree + $commits commit(s) being pushed)"
