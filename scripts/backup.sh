#!/usr/bin/env bash
# ============================================================================
# NetPulse nightly backup: database + config + vendor profiles.
#
# [MANUAL ACTION] Choose ONE destination:
#   A) local directory (default)  ->  BACKUP_DIR=/opt/netpulse/backups
#   B) Oracle Object Storage      ->  set OCI_BUCKET and install `oci` CLI
#
# Install as a cron job (as root):
#   sudo crontab -e
#   0 2 * * * /opt/netpulse/scripts/backup.sh >> /var/log/netpulse-backup.log 2>&1
# ============================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/netpulse}"
BACKUP_DIR="${BACKUP_DIR:-${APP_DIR}/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
ARCHIVE="${BACKUP_DIR}/netpulse-${STAMP}.tar.gz"

mkdir -p "${BACKUP_DIR}"

# SQLite: use the online backup command for a consistent copy
if [[ -f "${APP_DIR}/netpulse.db" ]]; then
    if command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 "${APP_DIR}/netpulse.db" ".backup '${WORK}/netpulse.db'"
    else
        cp "${APP_DIR}/netpulse.db" "${WORK}/netpulse.db"
    fi
fi

# config + vendor profiles
[[ -f "${APP_DIR}/.env" ]] && cp "${APP_DIR}/.env" "${WORK}/env.backup"
mkdir -p "${WORK}/profiles"
cp -r "${APP_DIR}/app/vendors/profiles/." "${WORK}/profiles/" 2>/dev/null || true

tar -czf "${ARCHIVE}" -C "${WORK}" .
rm -rf "${WORK}"

echo "[backup] created ${ARCHIVE}"

# [MANUAL ACTION] Optional off-site copy to Oracle Object Storage:
# if [[ -n "${OCI_BUCKET:-}" ]] && command -v oci >/dev/null 2>&1; then
#     oci os object put --bucket-name "${OCI_BUCKET}" --file "${ARCHIVE}" --name "backups/$(basename "${ARCHIVE}")"
#     echo "[backup] uploaded to OCI bucket ${OCI_BUCKET}"
# fi

# prune old archives
find "${BACKUP_DIR}" -name 'netpulse-*.tar.gz' -mtime "+${KEEP_DAYS}" -delete 2>/dev/null || true
echo "[backup] done"
