#!/usr/bin/env bash
#
# Run the database-backed tests against a database of their own.
#
# They used to run against the development database, and conftest.py's own docstring said
# why that was a loan rather than a decision: "If this database ever holds real practice
# history, these tests want a separate one." On 2026-08-26 it held a real job-application
# list, a fixture's teardown deleted every row of a table instead of the rows it created,
# and the list was gone. No amount of care in a fixture prevents that class of bug; a
# database the tests cannot reach does.
#
# The test database is the configured one with `_test` appended, so it follows whatever
# host, port and credentials `.env` sets — and `conftest.py` refuses to run db-marked tests
# against a database whose name does not end that way, so forgetting this script is a loud
# error rather than a quiet deletion.
#
# Usage:  bash scripts/test_db.sh [extra pytest args]
#         TEST_MARKER=llm bash scripts/test_db.sh -rs
#
# `TEST_MARKER` selects which suite runs (default `db`). Every marker that reaches Postgres
# goes through here, so there is one place that knows which database the tests use.

set -euo pipefail

cd "$(dirname "$0")/.."

# The URL to use, derived from whatever is configured. Printed by the app's own settings so
# a custom DATABASE_URL is honoured rather than second-guessed.
TEST_URL="$(
  uv run python - <<'PY'
from urllib.parse import urlsplit, urlunsplit

from api.settings import get_settings

parts = urlsplit(get_settings().database_url)
name = parts.path.lstrip("/")
if not name:
    raise SystemExit("DATABASE_URL names no database")
suffix = name if name.endswith("_test") else f"{name}_test"
print(urlunsplit(parts._replace(path=f"/{suffix}")))
PY
)"

# Create it if it is not there yet. `CREATE DATABASE` cannot run inside a transaction and
# cannot be addressed at the database being created, so this connects to the server's
# default `postgres` database to ask.
uv run python - "$TEST_URL" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, text

url = sys.argv[1]
parts = urlsplit(url)
name = parts.path.lstrip("/")
admin = create_engine(urlunsplit(parts._replace(path="/postgres")), isolation_level="AUTOCOMMIT")
with admin.connect() as conn:
    exists = conn.execute(
        text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
    ).first()
    if not exists:
        # Identifier, not a parameter — a bound parameter is not legal in CREATE DATABASE.
        # `name` is derived from configuration this process already trusts, not from input.
        conn.execute(text(f'CREATE DATABASE "{name}"'))
        print(f"created {name}")
PY

export DATABASE_URL="$TEST_URL"
echo "test database: ${TEST_URL%%\?*}"

# Migrated and seeded every run: the schema moves, and `items` is a projection of the
# corpus that the planner reads. Twice, authoring corpus items and then running these
# produced a wall of failures whose only cause was a stale table.
uv run alembic -c apps/api/alembic.ini upgrade head
uv run python -m api.seed
uv run pytest apps/api/tests -q -m "${TEST_MARKER:-db}" "$@"
