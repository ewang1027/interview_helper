#!/usr/bin/env bash
# Install, remove, or inspect the launchd job that dumps the database nightly.
#
# The buildlog's 2026-08-26 entry closed with "the development database still has no
# scheduled backup" — and by 2026-08-29 that had mattered twice more (a wrong-daemon
# incident, and the discovery that the freshest dump was three days behind the volume).
# This is the smallest thing that ends the pattern: launchd runs
# `scripts/backup_db.sh dump` at 21:00 every night. macOS coalesces a missed
# StartCalendarInterval to the next wake, so a laptop asleep at 21:00 dumps when the
# lid opens instead of silently skipping the night.
#
#   scripts/backup_schedule.sh install   -> writes and loads ~/Library/LaunchAgents/<label>.plist
#   scripts/backup_schedule.sh remove    -> unloads and deletes it
#   scripts/backup_schedule.sh status    -> is it loaded, when did it last run, exit code
#
# The plist is generated, not committed: it hard-codes this checkout's absolute path and
# a PATH that can find docker (launchd jobs do not get a login shell's PATH — without
# /opt/homebrew/bin the job fails with `docker: command not found` at 21:00, invisibly).
# Output lands in backups/backup.log, which /backups/ already keeps out of the repo.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

LABEL=com.interview-helper.backup
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(pwd)"
UID_N="$(id -u)"

case "${1:-}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents" backups
    cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>cd "$REPO" &amp;&amp; bash scripts/backup_db.sh dump</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$REPO/backups/backup.log</string>
  <key>StandardErrorPath</key><string>$REPO/backups/backup.log</string>
</dict>
</plist>
PLIST
    # bootout first so install is also re-install; ignore "not loaded".
    launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$UID_N" "$PLIST"
    echo "backup_schedule: loaded $LABEL — nightly at 21:00, log in backups/backup.log"
    echo "backup_schedule: run it once now to prove it:  launchctl kickstart gui/$UID_N/$LABEL"
    ;;

  remove)
    launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "backup_schedule: removed $LABEL — nothing schedules backups now"
    ;;

  status)
    if launchctl print "gui/$UID_N/$LABEL" >/dev/null 2>&1; then
      launchctl print "gui/$UID_N/$LABEL" | grep -E "state|last exit code|runs" | sed 's/^/backup_schedule: /'
      echo "backup_schedule: newest dump: $(ls -1t backups/interview_helper-*.sql.gz 2>/dev/null | head -1 || echo none)"
    else
      echo "backup_schedule: $LABEL is not loaded — make backup-schedule installs it"
      exit 1
    fi
    ;;

  *)
    echo "usage: $0 install | remove | status" >&2
    exit 1
    ;;
esac
