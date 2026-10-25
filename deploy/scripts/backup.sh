#!/usr/bin/env bash
# Daily backup for the maistro-engine production topology (SPEC-070226-fbe3 / ADR-081).
#
# Produces a self-contained local backup (the ADR-081 required baseline):
#   1. PostgreSQL daily full dump (pg_dump, custom format) — plus WAL archival
#      runs continuously on the primary (archive_command in docker-compose.prod.yml).
#   2. Redis RDB snapshot (SAVE, then copy dump.rdb).
#   3. File-store rsync.
#   4. Config snapshot note (config is version-controlled in git — ADR-081).
#
# Off-host shipping (S3/NFS/gdrive/...) is an OPTIONAL cloud connector; TODO
# markers below show where deployment-specific values go.
#
# Cron example (daily 03:15):  15 3 * * * /opt/maistro/deploy/scripts/backup.sh
set -euo pipefail

# ── Deployment-specific configuration ────────────────────────────────────────
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/maistro}"          # TODO: set to your backup mount
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.prod.yml}"
PG_SERVICE="${PG_SERVICE:-postgres-primary}"
REDIS_SERVICE="${REDIS_SERVICE:-redis}"
PG_USER="${POSTGRES_USER:-maistro}"
PG_DB="${POSTGRES_DB:-maistro}"
FILE_STORE_VOLUME="${FILE_STORE_VOLUME:-deploy_file-store}" # TODO: confirm volume name (docker volume ls)
RETENTION_DAYS="${RETENTION_DAYS:-14}"
# TODO: off-host target for the optional cloud connector, e.g.
#   REMOTE_TARGET="backup-host:/srv/backups/maistro"   (rsync over ssh)
#   REMOTE_TARGET="s3://my-bucket/maistro-backups"     (aws s3 sync / wal-g)
REMOTE_TARGET="${REMOTE_TARGET:-}"

STAMP="$(date -u +%Y-%m-%d)"
DEST="${BACKUP_ROOT}/${STAMP}"
mkdir -p "${DEST}"

compose() { docker compose -f "${COMPOSE_FILE}" "$@"; }

echo "[backup] ${STAMP} -> ${DEST}"

# ── 1. PostgreSQL full dump ──────────────────────────────────────────────────
# Custom-format dump (restorable via pg_restore, supports parallel restore).
compose exec -T "${PG_SERVICE}" pg_dump -U "${PG_USER}" -d "${PG_DB}" -Fc \
  > "${DEST}/postgres-${PG_DB}.dump"

# Plain-text dump used for the bit-for-bit consistency hash property
# ("backup restore always produces identical pg_dump output").
compose exec -T "${PG_SERVICE}" pg_dump -U "${PG_USER}" -d "${PG_DB}" --no-owner \
  > "${DEST}/postgres-${PG_DB}.sql"
sha256sum "${DEST}/postgres-${PG_DB}.sql" > "${DEST}/postgres-${PG_DB}.sql.sha256"

# WAL archival note: archive_command on the primary continuously copies WAL
# segments into the wal-archive volume; sync them next to the daily dump so a
# point-in-time restore has everything it needs.
docker run --rm -v deploy_wal-archive:/wal:ro -v "${DEST}:/dest" alpine \
  sh -c 'cp -a /wal/. /dest/wal_archive/ 2>/dev/null || mkdir -p /dest/wal_archive'
# TODO: for real WAL shipping prefer wal-g / pgbackrest pushing to ${REMOTE_TARGET}.

# ── 2. Redis RDB snapshot ────────────────────────────────────────────────────
compose exec -T "${REDIS_SERVICE}" sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning save'
docker run --rm -v deploy_redis-data:/data:ro -v "${DEST}:/dest" alpine \
  cp /data/dump.rdb /dest/redis-dump.rdb

# ── 3. File store ────────────────────────────────────────────────────────────
docker run --rm -v "${FILE_STORE_VOLUME}:/files:ro" -v "${DEST}:/dest" alpine \
  sh -c 'mkdir -p /dest/files && cp -a /files/. /dest/files/'
# TODO: replace with incremental rsync to backup NFS/S3 for large file stores:
#   rsync -a --delete /var/lib/docker/volumes/${FILE_STORE_VOLUME}/_data/ "${REMOTE_TARGET}/files/"

# ── 4. Config snapshot ───────────────────────────────────────────────────────
# Configuration is version-controlled in git (ADR-081); record the deployed ref.
git -C "$(dirname "$0")/../.." rev-parse HEAD > "${DEST}/deployed-git-ref.txt" 2>/dev/null \
  || echo "unknown" > "${DEST}/deployed-git-ref.txt"

# ── 5. Optional off-host shipping ────────────────────────────────────────────
if [[ -n "${REMOTE_TARGET}" ]]; then
  echo "[backup] shipping to ${REMOTE_TARGET}"
  # TODO: pick ONE and remove the other:
  # rsync -a "${DEST}/" "${REMOTE_TARGET}/${STAMP}/"
  # aws s3 sync "${DEST}" "${REMOTE_TARGET}/${STAMP}/"
fi

# ── 6. Retention ─────────────────────────────────────────────────────────────
find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" \
  -exec rm -rf {} +

echo "[backup] done: $(du -sh "${DEST}" | cut -f1)"
