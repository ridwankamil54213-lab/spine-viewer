#!/bin/bash
# Backup model spine-viewer yang BELUM ada di Google Drive.
# Tujuan: shared drive "saf:" folder 1zRly3eeewcrgdIe3bOUQUmyWUXXIwnzo
# (library model; berisi root per-game seperti azurlane/, bd2/, crosscore/, ...).
set -u
ID=1zRly3eeewcrgdIe3bOUQUmyWUXXIwnzo
SRC=/opt/spine-viewer/assets
LOG=/opt/spine-viewer/backup-gdrive.log
OPTS=(--drive-root-folder-id "$ID" --ignore-existing
      --transfers 8 --checkers 16 --drive-chunk-size 64M
      --retries 5 --low-level-retries 20 --stats 60s --stats-one-line)

roots="alcherystars angelica azurlane-l2d blissful everlusting girlwars
girlwars-l2d ivntight juezhan kink lostsword-video mecharashi mengqi mitao-utopia
shenlan tenkei throne wuhua xingjie ysjh"

echo "=== BACKUP START $(date -Is) ===" | tee -a "$LOG"
for r in $roots; do
  [ -d "$SRC/$r" ] || { echo "SKIP (tidak ada): $r" | tee -a "$LOG"; continue; }
  sz=$(du -sh "$SRC/$r" | cut -f1)
  echo "--- $r ($sz) $(date -Is) ---" | tee -a "$LOG"
  rclone copy "$SRC/$r" "saf:$r" "${OPTS[@]}" 2>&1 | tail -2 | tee -a "$LOG"
  echo "    exit=$? $r" | tee -a "$LOG"
done
echo "=== BACKUP SELESAI $(date -Is) ===" | tee -a "$LOG"
