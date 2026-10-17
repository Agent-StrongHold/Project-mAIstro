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

# ── 1. PostgreSQL full dump + snapshot-bound verification evidence (#1881) ──
# The authoritative custom-format archive and the semantic verification
# evidence are taken from the SAME exported snapshot, so concurrent writes
# cannot make them describe different states (the previous script hashed a
# second, unconstrained plain-text dump; PostgreSQL >= 17 also embeds a
# random psql restrict key in plain output, so raw dump bytes are not a
# stable restore oracle — see pg-semantic-oracle.sh).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/pg-semantic-oracle.sh"
oracle_psql() { compose exec -T "${PG_SERVICE}" psql -X -U "${PG_USER}" -d "${PG_DB}" "$@"; }
# Line buffering must be applied inside the container: psql block-buffers when
# its stdout is a pipe, and the snapshot-export session is read mid-flight.
oracle_psql_coproc() { compose exec -T "${PG_SERVICE}" stdbuf -oL psql -X -U "${PG_USER}" -d "${PG_DB}" "$@"; }

SNAPSHOT_ID=""
oracle_begin_snapshot                 # sets ORACLE_SNAPSHOT; must run in the main shell
SNAPSHOT_ID="${ORACLE_SNAPSHOT}"

# Artifact provenance: which state, which server, which tools produced it.
{
  echo "snapshot=${SNAPSHOT_ID}"
  echo "backup_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  oracle_psql -X -Atq -v ON_ERROR_STOP=1 -c "SELECT 'server_version=' || current_setting('server_version');"
  compose exec -T "${PG_SERVICE}" pg_dump -V
  compose exec -T "${PG_SERVICE}" psql -V
} > "${DEST}/postgres-${PG_DB}.provenance"

# Custom-format dump (restorable via pg_restore, supports parallel restore),
# taken from the exported snapshot while oracle_begin_snapshot's transaction
# is still open.
compose exec -T "${PG_SERVICE}" pg_dump -U "${PG_USER}" -d "${PG_DB}" -Fc --snapshot="${SNAPSHOT_ID}" \
  > "${DEST}/postgres-${PG_DB}.dump"

# Semantic evidence from the same snapshot: schema inventory + exact row counts.
oracle_collect_evidence \
  "${DEST}/postgres-${PG_DB}.schema" \
  "${DEST}/postgres-${PG_DB}.rowcounts" \
  "${SNAPSHOT_ID}"

oracle_end_snapshot

# At-rest integrity hashes for the archive and its evidence. These pin the
# artifacts against bit-rot in the backup store; they are NOT the restore
# oracle — verify-restore.sh compares semantic evidence, not dump bytes.
sha256sum "${DEST}/postgres-${PG_DB}.dump" > "${DEST}/postgres-${PG_DB}.dump.sha256"
sha256sum "${DEST}/postgres-${PG_DB}.schema" > "${DEST}/postgres-${PG_DB}.schema.sha256"
sha256sum "${DEST}/postgres-${PG_DB}.rowcounts" > "${DEST}/postgres-${PG_DB}.rowcounts.sha256"

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
