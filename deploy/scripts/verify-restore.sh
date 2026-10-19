#!/usr/bin/env bash
# Weekly restore-and-verify drill (SPEC-070226-fbe3 / ADR-081, #1881).
#
# Restores a backup's custom-format pg_dump archive into a throwaway scratch
# container and verifies restored SEMANTICS against evidence recorded at
# backup time — a schema inventory plus exact per-table row counts, bound to
# the same exported snapshot as the archive (see pg-semantic-oracle.sh).
#
# The drill deliberately does NOT compare raw dump bytes. The previous oracle
# (re-dump the restored DB, compare SHA-256 with a hash of a second plain dump
# taken at backup time) was invalid twice over: unconstrained dumps can
# describe different snapshots under concurrent writes, and PostgreSQL >= 17
# plain output embeds a random psql restrict key by default, so bytes differ
# even for unchanged semantic state. pg_dump/psql security defaults are
# preserved: no --restrict-key is set, and untrusted dump SQL is never
# rewritten.
#
# Distinct failure classes (all exit 1; the class is in the message):
#   artifact  — missing or corrupt backup artifacts (dump, evidence, hashes,
#               provenance)
#   restore   — the restore command itself failed
#   semantic  — restored schema/row-count evidence differs from the backup-time
#               evidence (real data loss or corruption)
#   verifier  — the verification machinery failed (scratch database not ready,
#               evidence could not be collected, no user tables restored)
#
# Explicit limits: this oracle proves structure and cardinality survive the
# restore (tables, columns, exact row counts). Cell-level content equality is
# out of scope; per-table contents beyond their counts are not compared.
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
SCHEMA_EVIDENCE="${SRC}/postgres-${PG_DB}.schema"
ROWCOUNT_EVIDENCE="${SRC}/postgres-${PG_DB}.rowcounts"
PROVENANCE="${SRC}/postgres-${PG_DB}.provenance"
DUMP_HASH_FILE="${SRC}/postgres-${PG_DB}.dump.sha256"
SCHEMA_HASH_FILE="${SRC}/postgres-${PG_DB}.schema.sha256"
ROWCOUNT_HASH_FILE="${SRC}/postgres-${PG_DB}.rowcounts.sha256"

fail_artifact()  { echo "[verify-restore] ARTIFACT FAIL: $*" >&2; exit 1; }
fail_restore()   { echo "[verify-restore] RESTORE FAIL: $*" >&2; exit 1; }
fail_semantic()  { echo "[verify-restore] SEMANTIC FAIL: $*" >&2; exit 1; }
fail_verifier()  { echo "[verify-restore] VERIFIER FAIL: $*" >&2; exit 1; }

RESTORED_SCHEMA="$(mktemp /tmp/restore-schema.XXXXXX)"
RESTORED_ROWCOUNTS="$(mktemp /tmp/restore-rowcounts.XXXXXX)"
SCHEMA_DIFF="$(mktemp /tmp/restore-schema-diff.XXXXXX)"
ROWCOUNT_DIFF="$(mktemp /tmp/restore-rowcount-diff.XXXXXX)"
cleanup() {
  docker rm -f "${SCRATCH_NAME}" >/dev/null 2>&1 || true
  rm -f "${RESTORED_SCHEMA}" "${RESTORED_ROWCOUNTS}" "${SCHEMA_DIFF}" "${ROWCOUNT_DIFF}"
}
trap cleanup EXIT

# ── 1. Artifact preflight: everything the oracle needs, integrity-checked ────
[[ -f "${DUMP}" ]] || fail_artifact "no dump at ${DUMP}"
[[ -f "${SCHEMA_EVIDENCE}" ]] || fail_artifact "no schema evidence at ${SCHEMA_EVIDENCE} (backup predates the #1881 evidence format; re-run backup.sh)"
[[ -f "${ROWCOUNT_EVIDENCE}" ]] || fail_artifact "no row-count evidence at ${ROWCOUNT_EVIDENCE} (backup predates the #1881 evidence format; re-run backup.sh)"
[[ -f "${PROVENANCE}" ]] || fail_artifact "no provenance at ${PROVENANCE}"

verify_sha256() {
  local file="$1" hash_file="$2"
  [[ -f "${hash_file}" ]] || fail_artifact "no hash file at ${hash_file}"
  local expected actual
  expected="$(cut -d' ' -f1 < "${hash_file}")"
  actual="$(sha256sum "${file}" | cut -d' ' -f1)"
  [[ "${expected}" == "${actual}" ]] || fail_artifact "hash mismatch for ${file}: expected ${expected}, got ${actual} (corrupt backup artifact)"
}

verify_sha256 "${DUMP}" "${DUMP_HASH_FILE}"
verify_sha256 "${SCHEMA_EVIDENCE}" "${SCHEMA_HASH_FILE}"
verify_sha256 "${ROWCOUNT_EVIDENCE}" "${ROWCOUNT_HASH_FILE}"

grep -q '^snapshot=' "${PROVENANCE}" || fail_artifact "provenance is missing the snapshot id"
echo "[verify-restore] artifacts OK for ${BACKUP_DATE} ($(grep '^snapshot=' "${PROVENANCE}"))"
grep '^server_version=' "${PROVENANCE}" || true

echo "[verify-restore] restoring ${BACKUP_DATE} into scratch container ${SCRATCH_NAME}"

# ── 2. Scratch PostgreSQL ────────────────────────────────────────────────────
docker run -d --name "${SCRATCH_NAME}" \
  -e POSTGRES_USER="${PG_USER}" \
  -e POSTGRES_PASSWORD=scratch-only-not-a-secret \
  -e POSTGRES_DB="${PG_DB}" \
  "${PG_IMAGE}" >/dev/null

# Readiness must target what pg_restore actually needs: the FINAL server
# accepting queries on the TARGET database. The image's init entrypoint runs a
# *temporary* server on the unix socket first (created before the target
# database exists and shut down again before the real one starts), so a socket
# `pg_isready -U ...` can report ready inside that window and the restore then
# dies with `FATAL: database "maistro" does not exist` or
# `FATAL: the database system is shutting down` — both measured in CI
# (tests/test_restore_oracle_characterization.py). The temporary server starts
# with `listen_addresses=''`, so probing over TCP loopback never sees it; the
# target database only answers once init has actually created it.
scratch_ready() {
  docker exec "${SCRATCH_NAME}" psql -X -h 127.0.0.1 -U "${PG_USER}" -d "${PG_DB}" \
    -c 'SELECT 1' >/dev/null 2>&1
}

ready=0
for _ in $(seq 1 60); do
  if scratch_ready; then
    ready=1
    break
  fi
  sleep 1
done
[[ "${ready}" == 1 ]] || fail_verifier "scratch postgres did not become ready"

# ── 3. Restore the custom-format archive ─────────────────────────────────────
if ! docker exec -i "${SCRATCH_NAME}" pg_restore -U "${PG_USER}" -d "${PG_DB}" \
  --no-owner --exit-on-error < "${DUMP}"; then
  fail_restore "pg_restore exited non-zero for backup ${BACKUP_DATE}"
fi

# ── 4. Semantic oracle: recompute the evidence and compare ───────────────────
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/pg-semantic-oracle.sh"
oracle_psql() { docker exec "${SCRATCH_NAME}" psql -X -U "${PG_USER}" -d "${PG_DB}" "$@"; }

if ! oracle_collect_evidence "${RESTORED_SCHEMA}" "${RESTORED_ROWCOUNTS}"; then
  fail_verifier "could not collect semantic evidence from the restored database"
fi

if ! diff -u "${SCHEMA_EVIDENCE}" "${RESTORED_SCHEMA}" > "${SCHEMA_DIFF}"; then
  sed -n '1,40p' "${SCHEMA_DIFF}" >&2 || true
  fail_semantic "restored schema inventory differs from backup-time evidence (see diff above)"
fi

if ! diff -u "${ROWCOUNT_EVIDENCE}" "${RESTORED_ROWCOUNTS}" > "${ROWCOUNT_DIFF}"; then
  sed -n '1,40p' "${ROWCOUNT_DIFF}" >&2 || true
  fail_semantic "restored row counts differ from backup-time evidence (see diff above)"
fi

# ── 5. Sanity: the restore actually produced user tables ─────────────────────
TABLE_COUNT="$(grep -c '=' "${RESTORED_ROWCOUNTS}" || true)"
echo "[verify-restore] restored ${TABLE_COUNT} user tables:"
sed 's/^/  /' "${RESTORED_ROWCOUNTS}"
[[ "${TABLE_COUNT}" -gt 0 ]] || fail_verifier "no user tables restored"

# TODO: after restore, point a staging maistro-server at the scratch DB and run
# smoke tests (GET /health/ready) per the spec's weekly staging drill.

echo "[verify-restore] PASS for backup ${BACKUP_DATE}: semantic evidence matches the backup snapshot"
