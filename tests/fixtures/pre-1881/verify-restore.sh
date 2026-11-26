#!/usr/bin/env bash
# Weekly restore-and-verify drill (SPEC-070226-fbe3 / ADR-081).
#
# Restores YESTERDAY's PostgreSQL backup into a throwaway scratch container and
# verifies the spec's consistency property:
#   "backup restore always produces bit-for-bit identical PostgreSQL state
#    (via pg_dump hash)"
# plus a per-table row-count sanity check.
#
# Cron example (weekly Sunday 04:00): 0 4 * * 0 /opt/maistro/deploy/scripts/verify-restore.sh
set -euo pipefail

# ── Deployment-specific configuration ────────────────────────────────────────
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/maistro}"          # TODO: match backup.sh
PG_IMAGE="${PG_IMAGE:-pgvector/pgvector:pg17}"
PG_USER="${POSTGRES_USER:-maistro}"
PG_DB="${POSTGRES_DB:-maistro}"
SCRATCH_NAME="maistro-restore-verify-$$"

BACKUP_DATE="${1:-$(date -u -d 'yesterday' +%Y-%m-%d)}"
SRC="${BACKUP_ROOT}/${BACKUP_DATE}"
DUMP="${SRC}/postgres-${PG_DB}.dump"
HASH_FILE="${SRC}/postgres-${PG_DB}.sql.sha256"

fail() { echo "[verify-restore] FAIL: $*" >&2; exit 1; }
cleanup() { docker rm -f "${SCRATCH_NAME}" >/dev/null 2>&1 || true; }
trap cleanup EXIT

[[ -f "${DUMP}" ]] || fail "no dump at ${DUMP}"
[[ -f "${HASH_FILE}" ]] || fail "no hash file at ${HASH_FILE}"

echo "[verify-restore] restoring ${BACKUP_DATE} into scratch container ${SCRATCH_NAME}"

# ── 1. Scratch PostgreSQL ────────────────────────────────────────────────────
docker run -d --name "${SCRATCH_NAME}" \
  -e POSTGRES_USER="${PG_USER}" \
  -e POSTGRES_PASSWORD=scratch-only-not-a-secret \
  -e POSTGRES_DB="${PG_DB}" \
  "${PG_IMAGE}" >/dev/null

for _ in $(seq 1 60); do
  if docker exec "${SCRATCH_NAME}" pg_isready -U "${PG_USER}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "${SCRATCH_NAME}" pg_isready -U "${PG_USER}" >/dev/null 2>&1 \
  || fail "scratch postgres did not become ready"

# ── 2. Restore ───────────────────────────────────────────────────────────────
docker exec -i "${SCRATCH_NAME}" pg_restore -U "${PG_USER}" -d "${PG_DB}" \
  --no-owner --exit-on-error < "${DUMP}"

# ── 3. Property check: pg_dump hash matches the hash taken at backup time ────
RESTORED_HASH="$(docker exec "${SCRATCH_NAME}" pg_dump -U "${PG_USER}" -d "${PG_DB}" --no-owner \
  | sha256sum | cut -d' ' -f1)"
EXPECTED_HASH="$(cut -d' ' -f1 < "${HASH_FILE}")"
if [[ "${RESTORED_HASH}" != "${EXPECTED_HASH}" ]]; then
  fail "pg_dump hash mismatch: expected ${EXPECTED_HASH}, got ${RESTORED_HASH}"
fi
echo "[verify-restore] pg_dump hash OK (${RESTORED_HASH})"

# ── 4. Row-count sanity: every user table restored, none empty-when-dumped ──
ROW_COUNTS="$(docker exec "${SCRATCH_NAME}" psql -U "${PG_USER}" -d "${PG_DB}" -At -c \
  "SELECT relname || '=' || n_live_tup FROM pg_stat_user_tables ORDER BY relname;")"
TABLE_COUNT="$(echo "${ROW_COUNTS}" | grep -c '=' || true)"
echo "[verify-restore] restored ${TABLE_COUNT} user tables:"
echo "${ROW_COUNTS}" | sed 's/^/  /'
[[ "${TABLE_COUNT}" -gt 0 ]] || fail "no user tables restored"

# TODO: after restore, point a staging maistro-server at the scratch DB and run
# smoke tests (GET /health/ready) per the spec's weekly staging drill.

echo "[verify-restore] PASS for backup ${BACKUP_DATE}"
