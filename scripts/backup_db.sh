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
# dangerous thing should be visible in the command that does it. Since 2026-08-29 restore
# also dumps the database it is about to overwrite first — the situation that calls for a
# restore is exactly the one where you are least sure which state is the good one.
#
# `dump` is also what the launchd job installed by `make backup-schedule` runs nightly,
# and it prunes: the newest $BACKUP_KEEP dumps (default 60) survive, older ones go. The
# prune matches interview_helper-*.sql.gz only — anything else in backups/ (a raw volume
# tarball, a dump renamed to keep forever) is not its business.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# Follow the machine's daemon pin when invoked directly. Via `make` this is already
# exported; launchd knows nothing about make, so the script reads the pin itself.
# Otherwise a nightly backup can faithfully archive the wrong daemon's empty database —
# which on 2026-08-29 is exactly what `make backup` would have done (docs/INFRA.md).
if [[ -z ${DOCKER_CONTEXT:-} && -f .docker-context ]]; then
  DOCKER_CONTEXT="$(tr -d '[:space:]' < .docker-context)"
  export DOCKER_CONTEXT
fi

CONTAINER=compose-postgres-1
DB_USER=interview
DB_NAME=interview_helper
BACKUP_DIR=backups
BACKUP_KEEP="${BACKUP_KEEP:-60}"

running() {
  docker ps --filter "name=^${CONTAINER}$" --format '{{.Names}}' | grep -q "$CONTAINER"
}

if ! running; then
  echo "backup_db: $CONTAINER is not running — start it with 'make dev'" >&2
  exit 1
fi

dump_to() {
  # --clean --if-exists so the dump can be replayed over a populated database without
  # a manual drop first; a restore that only works into an empty database is a restore
  # nobody can perform in the situation they actually need it.
  docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists \
    | gzip > "$1"
  echo "backup_db: wrote $1 ($(du -h "$1" | cut -f1))"
}

prune() {
  # Newest $BACKUP_KEEP survive. ls -t + tail is safe here because the names are the
  # script's own: no spaces, no newlines.
  ls -1t "$BACKUP_DIR"/${DB_NAME}-*.sql.gz 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))" \
    | while read -r old; do
        rm -f "$old"
        echo "backup_db: pruned $old (keeping newest $BACKUP_KEEP)"
      done
}

case "${1:-}" in
  dump)
    mkdir -p "$BACKUP_DIR"
    # `date` at call time, not baked in: one file per run is the point.
    dump_to "$BACKUP_DIR/${DB_NAME}-$(date +%Y%m%d-%H%M%S).sql.gz"
    prune
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
    # The state being overwritten gets its own dump first. If the restore was the wrong
    # call, the mistake is now a second restore rather than a loss.
    dump_to "$BACKUP_DIR/${DB_NAME}-$(date +%Y%m%d-%H%M%S)-pre-restore.sql.gz"
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
