#!/usr/bin/env bash
# Greps tracked files for common secret shapes before they ever leave a
# machine. Backstop for GitHub's own secret scanning (which only sees a
# push after it lands), not a replacement for it — see docs/SECURITY.md.
set -euo pipefail

PATTERNS=(
  'AKIA[0-9A-Z]{16}'                    # AWS access key id
  'ASIA[0-9A-Z]{16}'                    # AWS temporary access key id
  'aws_secret_access_key\s*=\s*[^$]'    # AWS secret key assigned a literal
  'sk-ant-[A-Za-z0-9_-]{20,}'           # Anthropic API key
  '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'
  'ghp_[A-Za-z0-9]{36}'                 # GitHub personal access token
  'gho_[A-Za-z0-9]{36}'                 # GitHub OAuth token
)

pattern_re=$(IFS='|'; echo "${PATTERNS[*]}")

hits=$(git grep -InE "$pattern_re" -- \
  ':!*.example' ':!scripts/secret_scan.sh' ':!*.lock' 2>/dev/null || true)

if [[ -n "$hits" ]]; then
  echo "secret_scan: possible secret matched — review before committing/pushing:" >&2
  echo "$hits" >&2
  exit 1
fi

echo "secret_scan: clean"
