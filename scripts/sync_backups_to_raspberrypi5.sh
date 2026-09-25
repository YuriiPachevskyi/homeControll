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
SKIP=$((KEEP + 1))
PRUNE_CMD="cd \"$DEST_PATH\" && ls -1t -- *.tar 2>/dev/null | tail -n +${SKIP} | xargs -r rm -f --"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$DEST_HOST" "$PRUNE_CMD" \
    && logger -t "$LOG_TAG" "pruned old backups on ${DEST_HOST}, keeping newest ${KEEP}" \
    || logger -t "$LOG_TAG" "FAILED to prune old backups on ${DEST_HOST}"

# Host-only secrets (~/.secrets: HA token, mail/cabinet logins, ...) - never
# in git, so this is their only copy off this machine. Encrypted with gpg
# (AES-256) using ~/.secrets/backup_passphrase, which the user keeps outside
# this server too; the passphrase itself is left out of the archive. The HA
# backup encryption password (only in .storage/backup) is refreshed into
# ~/.secrets/ha_backup_password first, so the HA backups above can be opened
# after losing this machine. One dated file per day, newest $KEEP kept.
# Restore: gpg -d secrets-<date>.tar.gpg | tar -x -C ~
SECRETS_DIR="/home/yurii/.secrets"
SECRETS_DEST_PATH="/home/yurii/work/raspberrypi4/secrets"
(
    umask 077
    python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["data"]["config"]["create_backup"]["password"], end="")' \
        /home/yurii/docker/homeControll/configuration/.storage/backup > "$SECRETS_DIR/ha_backup_password"
    tar -C /home/yurii --exclude=.secrets/backup_passphrase -cf - .secrets \
        | gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-file "$SECRETS_DIR/backup_passphrase" \
              --symmetric --cipher-algo AES256 -o - \
        | ssh -o BatchMode=yes -o ConnectTimeout=10 "$DEST_HOST" \
              "umask 077; mkdir -p '$SECRETS_DEST_PATH' && cat > '$SECRETS_DEST_PATH/secrets-$(date +%F).tar.gpg' \
               && cd '$SECRETS_DEST_PATH' && ls -1t -- secrets-*.tar.gpg | tail -n +$((KEEP + 1)) | xargs -r rm -f --"
) && logger -t "$LOG_TAG" "synced encrypted secrets to ${DEST_HOST}:${SECRETS_DEST_PATH}" \
  || logger -t "$LOG_TAG" "FAILED to sync encrypted secrets to ${DEST_HOST}:${SECRETS_DEST_PATH}"
