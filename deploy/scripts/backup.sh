#!/usr/bin/env bash
# Daily backup for the maistro-engine production topology (SPEC-070226-fbe3 / ADR-081).
#
# Produces a self-contained local backup (the ADR-081 required baseline):
#   1. PostgreSQL daily full dump (pg_dump, custom format) — plus WAL archival
#      runs continuously on the primary (archive_command in docker-compose.prod.yml).
#   2. Redis RDB snapshot (SAVE, then copy dump.rdb).
#   3. File-store rsync.
#   3.5. Conductor durable state (state.db, secrets.age, user_credentials.enc)
#        and credential escrow (admin.key, credential_master.key) — the escrow
#        is deliberately written OUTSIDE the backup artifact, because a backup
#        that ships off-host must carry ciphertext only. See
#        docs/install/deployment-topology.md §2.1.
#   4. Config snapshot note (config is version-controlled in git — ADR-081)
#      plus a sha256 integrity manifest over every component above, which
#      verify-restore.sh re-checks before restoring anything.
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
CONDUCTOR_SERVICE="${CONDUCTOR_SERVICE:-hive-conductor}"
PG_USER="${POSTGRES_USER:-maistro}"
PG_DB="${POSTGRES_DB:-maistro}"
FILE_STORE_VOLUME="${FILE_STORE_VOLUME:-deploy_file-store}" # TODO: confirm volume name (docker volume ls)
# Compose prefixes volumes with the project name (deploy/), same as the other
# defaults above. CONDUCTOR_DATA_DIR=/data on this volume holds the Conductor's
# authoritative state — see the D-18 audit: a backup without it loses identities,
# sessions, and every stored secret.
CONDUCTOR_DATA_VOLUME="${CONDUCTOR_DATA_VOLUME:-deploy_conductor-data}"
# The decryption roots (admin.key -> secrets.age, credential_master.key ->
# user_credentials.enc) are escrowed here, NOT in the backup artifact: the
# identity that decrypts the vault must not live only beside the ciphertext it
# opens. Replicate this directory off-host through your secret manager.
ESCROW_ROOT="${ESCROW_ROOT:-/var/lib/maistro-escrow}"
# Set SKIP_CONDUCTOR_BACKUP=1 only for stacks that genuinely run no Conductor;
# verify-restore.sh will then report the conductor state as absent.
SKIP_CONDUCTOR_BACKUP="${SKIP_CONDUCTOR_BACKUP:-0}"
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

# ── 3.5. Conductor durable state ─────────────────────────────────────────────
#   The Conductor's authoritative state is NOT reconstructable from the
#   PostgreSQL/Redis/file-store backups above:
#     state.db              SQLite: canonical Workspaces/Memberships,
#                           Runs/NodeRuns/Attempts, graph continuations
#                           (continuation version + attempt-lease fencing),
#                           sessions, schedules, audit log.
#     secrets.age           age-encrypted secrets vault (SPEC-011).
#     user_credentials.enc  Fernet-encrypted per-user provider tokens.
#   state.db is snapshotted with the SQLite online-backup API through the
#   running container (a raw copy of a live SQLite file can be torn); the
#   remaining files are static ciphertext, safe to copy.
if [[ "${SKIP_CONDUCTOR_BACKUP}" == "1" ]]; then
  echo "[backup] WARNING: SKIP_CONDUCTOR_BACKUP=1 — Conductor durable state NOT captured"
else
  compose exec -T "${CONDUCTOR_SERVICE}" python - <<'PY'
import sqlite3

src = sqlite3.connect("file:/data/state.db?mode=ro", uri=True)
dst = sqlite3.connect("/tmp/state.db.backup-snapshot")
try:
    src.backup(dst)
finally:
    dst.close()
    src.close()
PY
  docker run --rm -v "${CONDUCTOR_DATA_VOLUME}:/data:ro" -v "${DEST}:/dest" alpine \
    sh -c 'mkdir -p /dest/conductor-data && cp -a /data/. /dest/conductor-data/ && rm -f /dest/conductor-data/state.db'
  compose exec -T "${CONDUCTOR_SERVICE}" cat /tmp/state.db.backup-snapshot \
    > "${DEST}/conductor-data/state.db"
  compose exec -T "${CONDUCTOR_SERVICE}" rm -f /tmp/state.db.backup-snapshot
fi

# ── 3.6. Credential escrow (decryption roots — NOT part of ${DEST}) ─────────
#   admin.key           age/X25519 identity; the ONLY key that decrypts
#                      secrets.age. Losing it (with no escrow) makes every
#                      stored vault secret cryptographically unrecoverable.
#   credential_master.key  Fernet root for user_credentials.enc.
#   This is the documented escrow mechanism: a dated, root-owned snapshot
#   outside the backup tree. If the escrow is lost, the runbook at
#   docs/install/deployment-topology.md §2.1 lists what becomes unrecoverable.
if [[ "${SKIP_CONDUCTOR_BACKUP}" != "1" ]]; then
  ESCROW_DIR="${ESCROW_ROOT}/${STAMP}"
  mkdir -p "${ESCROW_DIR}"
  chmod 700 "${ESCROW_ROOT}" "${ESCROW_DIR}" 2>/dev/null || true
  ESCROWED="$(docker run --rm -v "${CONDUCTOR_DATA_VOLUME}:/data:ro" -v "${ESCROW_DIR}:/escrow" alpine \
    sh -c 'for f in admin.key credential_master.key; do
             if [ -f "/data/$f" ]; then cp -a "/data/$f" "/escrow/$f"; chmod 600 "/escrow/$f"; echo "$f"; fi
           done')"
  : > "${ESCROW_DIR}/manifest.sha256"
  for f in ${ESCROWED}; do
    (cd "${ESCROW_DIR}" && sha256sum "${f}") >> "${ESCROW_DIR}/manifest.sha256"
  done
  if [[ -s "${DEST}/conductor-data/secrets.age" ]] && ! grep -q '^admin\.key$' <<< "${ESCROWED}"; then
    echo "[backup] FAIL: secrets.age was backed up but admin.key is missing from the volume —" >&2
    echo "[backup]   the vault cannot be decrypted and the escrow is gone. Restore admin.key" >&2
    echo "[backup]   from your off-host escrow before this backup can be verified." >&2
    exit 1
  fi
  if [[ -s "${DEST}/conductor-data/user_credentials.enc" ]] && ! grep -q '^credential_master\.key$' <<< "${ESCROWED}"; then
    echo "[backup] FAIL: user_credentials.enc was backed up but credential_master.key is missing —" >&2
    echo "[backup]   escrow it from your off-host copy before this backup can be verified." >&2
    exit 1
  fi
  # TODO: the escrow has its own off-host path (secret manager / encrypted
  #   media), deliberately NOT ${REMOTE_TARGET}: whatever ships the backup
  #   must not carry the keys that open it.
fi

# ── 4. Config snapshot ───────────────────────────────────────────────────────
# Configuration is version-controlled in git (ADR-081); record the deployed ref.
git -C "$(dirname "$0")/../.." rev-parse HEAD > "${DEST}/deployed-git-ref.txt" 2>/dev/null \
  || echo "unknown" > "${DEST}/deployed-git-ref.txt"

# ── 4.5. Integrity manifest ──────────────────────────────────────────────────
#   verify-restore.sh re-checks every hash before restoring: a missing or
#   corrupt component (including an empty conductor capture) fails the drill
#   loudly instead of restoring a silently truncated backup.
MANIFEST="$(cd "${DEST}" && find . -type f ! -name manifest.sha256 ! -name .manifest.sha256.tmp -print0 \
  | sort -z | xargs -0 sha256sum)"
[[ -n "${MANIFEST}" ]] && printf '%s\n' "${MANIFEST}" > "${DEST}/manifest.sha256"

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
if [[ -d "${ESCROW_ROOT:-}" ]]; then
  find "${ESCROW_ROOT}" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" \
    -exec rm -rf {} +
fi

echo "[backup] done: $(du -sh "${DEST}" | cut -f1); escrow: ${ESCROW_DIR:-skipped}"
