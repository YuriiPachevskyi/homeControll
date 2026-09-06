#!/bin/bash
set -euo pipefail

SRC="/home/yurii/docker/homeControll/configuration/backups/"
DEST_HOST="raspberrypi5"
DEST_PATH="/home/yurii/work/raspberrypi4/backups"
LOG_TAG="ha-backup-sync"
KEEP=10

rsync -az --timeout=300 -e "ssh -o BatchMode=yes -o ConnectTimeout=10" \
    "$SRC" "${DEST_HOST}:${DEST_PATH}/" \
    && logger -t "$LOG_TAG" "synced HA backups to ${DEST_HOST}:${DEST_PATH}" \
    || logger -t "$LOG_TAG" "FAILED to sync HA backups to ${DEST_HOST}:${DEST_PATH}"

# Keep only the newest $KEEP *.tar backups on the remote; delete the rest.
# Only touches *.tar (leaves key.txt and anything else in the dir alone).
SKIP=$((KEEP + 1))
PRUNE_CMD="cd \"$DEST_PATH\" && ls -1t -- *.tar 2>/dev/null | tail -n +${SKIP} | xargs -r rm -f --"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$DEST_HOST" "$PRUNE_CMD" \
    && logger -t "$LOG_TAG" "pruned old backups on ${DEST_HOST}, keeping newest ${KEEP}" \
    || logger -t "$LOG_TAG" "FAILED to prune old backups on ${DEST_HOST}"
