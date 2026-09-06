#!/bin/bash
set -euo pipefail

SRC="/home/yurii/docker/homeControll/configuration/backups/"
DEST_HOST="raspberrypi5"
DEST_PATH="/home/yurii/work/raspberrypi4/backups"
LOG_TAG="ha-backup-sync"

rsync -az --timeout=300 -e "ssh -o BatchMode=yes -o ConnectTimeout=10" \
    "$SRC" "${DEST_HOST}:${DEST_PATH}/" \
    && logger -t "$LOG_TAG" "synced HA backups to ${DEST_HOST}:${DEST_PATH}" \
    || logger -t "$LOG_TAG" "FAILED to sync HA backups to ${DEST_HOST}:${DEST_PATH}"
