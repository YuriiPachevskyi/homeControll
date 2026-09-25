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

# Synced documents - ENERA acts and Oselya receipts, one subdir each (not in
# git: they hold personal data). Copied as-is, no --delete and no pruning, so
# a file removed locally stays on the remote.
ACTS_SRC="/home/yurii/docker/homeControll/configuration/statistics/documents/"
ACTS_DEST_PATH="/home/yurii/work/raspberrypi4/documents"

rsync -az --timeout=300 -e "ssh -o BatchMode=yes -o ConnectTimeout=10" \
    "$ACTS_SRC" "${DEST_HOST}:${ACTS_DEST_PATH}/" \
    && logger -t "$LOG_TAG" "synced documents to ${DEST_HOST}:${ACTS_DEST_PATH}" \
    || logger -t "$LOG_TAG" "FAILED to sync documents to ${DEST_HOST}:${ACTS_DEST_PATH}"

# Keep only the newest $KEEP *.tar backups on the remote; delete the rest.
# Only touches *.tar (leaves key.txt and anything else in the dir alone).
# Host-only credentials (~/.secrets: HA token, mail/cabinet logins, ...) -
# never in git, so this is their only copy off this machine. Plain copy, no
# extra encryption (user's choice: no second password to keep); the folder
# on raspberrypi5 is 700 and the files 600. No --delete, so a file removed
# here by mistake survives there.
SECRETS_SRC="/home/yurii/.secrets/"
SECRETS_DEST_PATH="/home/yurii/work/raspberrypi4/secrets"
rsync -az --timeout=300 --chmod=D700,F600 -e "ssh -o BatchMode=yes -o ConnectTimeout=10" \
    "$SECRETS_SRC" "${DEST_HOST}:${SECRETS_DEST_PATH}/" \
    && logger -t "$LOG_TAG" "synced secrets to ${DEST_HOST}:${SECRETS_DEST_PATH}" \
    || logger -t "$LOG_TAG" "FAILED to sync secrets to ${DEST_HOST}:${SECRETS_DEST_PATH}"

SKIP=$((KEEP + 1))
PRUNE_CMD="cd \"$DEST_PATH\" && ls -1t -- *.tar 2>/dev/null | tail -n +${SKIP} | xargs -r rm -f --"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$DEST_HOST" "$PRUNE_CMD" \
    && logger -t "$LOG_TAG" "pruned old backups on ${DEST_HOST}, keeping newest ${KEEP}" \
    || logger -t "$LOG_TAG" "FAILED to prune old backups on ${DEST_HOST}"
