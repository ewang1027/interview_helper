#!/usr/bin/env bash
# Dump the local database to a file, or restore one over it.
#
# docs/OPERATIONS.md's backup plan is RDS snapshots and a weekly `pg_dump` to S3 — both
# Phase 6 or later, both about a deployment that does not exist. Meanwhile everything this
# project knows about one person's mastery lives in a single Docker volume with nothing
# copying it anywhere, and the commands that destroy that volume (`docker compose down -v`,
# `colima delete`, a Docker Desktop reset) look a lot like the ones that do not.
#
# So this is the local half, early. It is not the Phase 8 plan and does not replace it.
#
#   scripts/backup_db.sh dump                     -> backups/interview_helper-<stamp>.sql.gz
#   CONFIRM=1 scripts/backup_db.sh restore <file> -> overwrites the database with that file
#
# `restore` needs CONFIRM=1 typed out, for the same reason `ALLOW_UNDOCUMENTED=1` is: the
# dangerous thing should be visible in the command that does it.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

CONTAINER=compose-postgres-1
DB_USER=interview
DB_NAME=interview_helper
BACKUP_DIR=backups

running() {
  docker ps --filter "name=^${CONTAINER}$" --format '{{.Names}}' | grep -q "$CONTAINER"
}

if ! running; then
  echo "backup_db: $CONTAINER is not running — start it with 'make dev'" >&2
  exit 1
fi

case "${1:-}" in
  dump)
    mkdir -p "$BACKUP_DIR"
    # `date` at call time, not baked in: one file per run is the point.
    target="$BACKUP_DIR/${DB_NAME}-$(date +%Y%m%d-%H%M%S).sql.gz"
    # --clean --if-exists so the dump can be replayed over a populated database without
    # a manual drop first; a restore that only works into an empty database is a restore
    # nobody can perform in the situation they actually need it.
    docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists \
      | gzip > "$target"
    echo "backup_db: wrote $target ($(du -h "$target" | cut -f1))"
    ;;

  restore)
    file="${2:-}"
    if [[ -z $file ]]; then
      echo "backup_db: restore needs a file — scripts/backup_db.sh restore <file>" >&2
      exit 1
    fi
    if [[ ! -f $file ]]; then
      echo "backup_db: no such file: $file" >&2
      exit 1
    fi
    if [[ ${CONFIRM:-0} != "1" ]]; then
      echo "backup_db: this REPLACES everything in '$DB_NAME' with $file." >&2
      echo "           Re-run it as:  CONFIRM=1 $0 restore $file" >&2
      exit 1
    fi
    gunzip -c "$file" | docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -q
    echo "backup_db: restored from $file"
    echo "backup_db: mastery is a projection — run POST /api/v1/mastery/recompute if the"
    echo "           dump predates a grader fix (docs/ADAPTIVE.md)."
    ;;

  *)
    echo "usage: $0 dump | restore <file>" >&2
    exit 1
    ;;
esac
