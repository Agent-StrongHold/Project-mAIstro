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

# Database dumps and stored files may contain credentials and personal data.
# This only affects files created by this process; never widen or recursively
# rewrite permissions on an operator's existing backup tree.
umask 077
fail() { echo "[backup] FAIL: $*" >&2; exit 1; }

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
[[ ! -L "${DEST}" ]] || fail "backup destination must not be a symlink"
mkdir -p -m 700 -- "${DEST}"
[[ -d "${DEST}" && -O "${DEST}" ]] || fail "backup destination must be owned by this user"
DEST_MODE="$(stat -c '%a' -- "${DEST}")"
(( (8#${DEST_MODE} & 077) == 0 )) \
  || fail "backup destination must have owner-only permissions"

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
  # Deliberate: the escrow has its own off-host path (secret manager /
  #   encrypted media), NOT ${REMOTE_TARGET}: whatever ships the backup
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
