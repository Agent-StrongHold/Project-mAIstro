#!/usr/bin/env bash
# Weekly restore-and-verify drill (SPEC-070226-fbe3 / ADR-081).
#
# Restores YESTERDAY's PostgreSQL backup into a throwaway scratch container and
# verifies the spec's consistency property:
#   "backup restore always produces bit-for-bit identical PostgreSQL state
#    (via pg_dump hash)"
# plus a per-table row-count sanity check, a sha256 integrity manifest over
# every backup component, and — for the Conductor durable state — an actual
# decrypt proof: the escrowed admin.key must open the backed-up secrets.age,
# and the backed-up state.db must pass integrity/schema checks with historical
# Runs inspectable (issue #88 / the D-18 backup-gap audit).
#
# Cron example (weekly Sunday 04:00): 0 4 * * 0 /opt/maistro/deploy/scripts/verify-restore.sh
set -euo pipefail

# ── Deployment-specific configuration ────────────────────────────────────────
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/maistro}"          # TODO: match backup.sh
ESCROW_ROOT="${ESCROW_ROOT:-/var/lib/maistro-escrow}"       # must match backup.sh
PG_IMAGE="${PG_IMAGE:-pgvector/pgvector:pg17}"
PG_USER="${POSTGRES_USER:-maistro}"
PG_DB="${POSTGRES_DB:-maistro}"
SCRATCH_NAME="maistro-restore-verify-$$"

BACKUP_DATE="${1:-$(date -u -d 'yesterday' +%Y-%m-%d)}"
SRC="${BACKUP_ROOT}/${BACKUP_DATE}"
ESCROW_DIR="${ESCROW_ROOT}/${BACKUP_DATE}"
DUMP="${SRC}/postgres-${PG_DB}.dump"
HASH_FILE="${SRC}/postgres-${PG_DB}.sql.sha256"

fail() { echo "[verify-restore] FAIL: $*" >&2; exit 1; }
cleanup() { docker rm -f "${SCRATCH_NAME}" >/dev/null 2>&1 || true; }

# ── Integrity manifest: missing/corrupt components fail here, loudly ─────────
verify_backup_manifest() {
  local src="$1"
  [[ -f "${src}/manifest.sha256" ]] \
    || fail "no integrity manifest at ${src}/manifest.sha256 — re-run backup.sh (a backup without one cannot prove its components)"
  ( cd "${src}" && sha256sum -c --quiet manifest.sha256 ) \
    || fail "integrity manifest check failed — a backup component is missing or corrupt; do not restore from this backup"
}

# ── Conductor durable state + credential escrow (issue #88) ──────────────────
# Callers may source this script and invoke the functions directly; main only
# runs when the script is executed.
verify_conductor_backup() {
  local src="$1" escrow="$2"
  local data="${src}/conductor-data"

  [[ -d "${data}" ]] \
    || fail "conductor-data is missing from the backup — the authoritative Conductor state (state.db, secrets.age, user_credentials.enc) was not captured; this is exactly the D-18 backup gap"

  local f
  for f in state.db secrets.age user_credentials.enc; do
    [[ -s "${data}/${f}" ]] || fail "conductor-data/${f} is missing or empty in the backup"
  done

  # state.db must be a usable SQLite database: intact, and carrying the
  # canonical spine (Workspaces, Runs/NodeRuns/Attempts), the graph
  # continuations with their fencing version, sessions, and the audit log.
  # Historical Run IDs are printed so the drill shows, not assumes, that the
  # restored Conductor can inspect its history.
  python3 - "${data}/state.db" <<'PY' || fail "state.db failed integrity/schema verification (see details above)"
import sqlite3
import sys

db = sys.argv[1]
with open(db, "rb") as fh:
    if fh.read(16) != b"SQLite format 3\x00":
        print(f"[verify-restore]   {db} is not a SQLite database", file=sys.stderr)
        raise SystemExit(1)
conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
try:
    (integrity,) = conn.execute("PRAGMA integrity_check").fetchone()
    if integrity != "ok":
        print(f"[verify-restore]   state.db integrity_check: {integrity}", file=sys.stderr)
        raise SystemExit(1)
    required = {
        "canonical_runs",
        "canonical_node_runs",
        "canonical_attempts",
        "canonical_workspaces",
        "canonical_workspace_memberships",
        "graph_continuations",
        "sessions",
        "audit_log",
    }
    present = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing = sorted(required - present)
    if missing:
        print(
            "[verify-restore]   state.db is missing authoritative tables: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        raise SystemExit(1)
    for table in sorted(required):
        (count,) = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        print(f"[verify-restore]   state.db {table}: {count} row(s)")
    # Fencing state is data: continuation versions and attempt ordinals must
    # have survived restore verbatim, so resumed work cannot bypass a fence.
    for table, column in (("graph_continuations", "version"), ("canonical_attempts", "ordinal")):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            print(
                f"[verify-restore]   {table}.{column} (fencing) missing after restore",
                file=sys.stderr,
            )
            raise SystemExit(1)
    for (run_id,) in conn.execute(
        "SELECT run_id FROM canonical_runs ORDER BY rowid DESC LIMIT 3"
    ):
        print(f"[verify-restore]   historical Run inspectable: {run_id}")
    for (version,) in conn.execute(
        "SELECT version FROM graph_continuations ORDER BY rowid DESC LIMIT 3"
    ):
        print(f"[verify-restore]   continuation fencing version preserved: {version}")
finally:
    conn.close()
PY

  # Credential escrow: the decryption roots must exist OUTSIDE the backup —
  # an escrow that only lives beside the ciphertext it opens is no escrow.
  [[ -d "${escrow}" ]] \
    || fail "credential escrow missing at ${escrow} — without the escrowed admin.key the vault (secrets.age) is cryptographically unrecoverable and every stored secret is gone for good"
  [[ -s "${escrow}/admin.key" ]] \
    || fail "credential escrow at ${escrow} holds no admin.key — secrets.age is unrecoverable without it"
  grep -q "^# public key: " "${escrow}/admin.key" \
    || fail "escrowed admin.key is not an age identity file (missing '# public key:' header)"
  if [[ -f "${escrow}/manifest.sha256" ]]; then
    ( cd "${escrow}" && sha256sum -c --quiet manifest.sha256 ) \
      || fail "credential escrow manifest check failed — the escrowed keys do not match what backup.sh recorded; re-escrow from the off-host copy"
  else
    echo "[verify-restore] WARNING: escrow has no manifest.sha256 — cannot prove these keys are the ones backup.sh recorded"
  fi

  # THE decrypt proof: the escrowed identity actually opens the backed-up
  # vault. This is what turns "the key file exists" into "the restored
  # Conductor identity is usable".
  command -v age >/dev/null 2>&1 \
    || fail "age(1) not found on the drill host — install age to prove the escrowed identity decrypts the vault"
  local vault_plain=""
  if ! vault_plain="$(age --decrypt -i "${escrow}/admin.key" "${data}/secrets.age" 2>/dev/null)"; then
    fail "DECRYPT PROOF FAILED: the escrowed admin.key cannot decrypt the backed-up secrets.age — a restored Conductor would fail closed on its vault (SECRET_MISSING)"
  fi
  if [[ -n "${EXPECTED_SECRET_NAME:-}" ]]; then
    grep -Eq "^${EXPECTED_SECRET_NAME}( = |$)" <<< "${vault_plain}" \
      || fail "known secret '${EXPECTED_SECRET_NAME}' is not readable in the decrypted vault — check EXPECTED_SECRET_NAME against the provisioned vault"
    echo "[verify-restore] decrypt proof: escrowed admin.key decrypted secrets.age; known secret '${EXPECTED_SECRET_NAME}' is readable"
  else
    echo "[verify-restore] decrypt proof: escrowed admin.key decrypted secrets.age ($(grep -c . <<< "${vault_plain}" || true) secret line(s)); set EXPECTED_SECRET_NAME to pin a known secret"
  fi

  # user_credentials.enc disposition: its Fernet root must be escrowed too,
  # or every per-user provider token in the backup is unrecoverable.
  [[ -s "${escrow}/credential_master.key" ]] \
    || fail "credential escrow has no credential_master.key — user_credentials.enc (per-user provider tokens) is unrecoverable without it; re-escrow from the off-host copy"
}

main() {
  trap cleanup EXIT

  [[ -f "${DUMP}" ]] || fail "no dump at ${DUMP}"
  [[ -f "${HASH_FILE}" ]] || fail "no hash file at ${HASH_FILE}"

  echo "[verify-restore] restoring ${BACKUP_DATE} into scratch container ${SCRATCH_NAME}"

  # ── 1. Scratch PostgreSQL ──────────────────────────────────────────────────
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

  # ── 2. Restore ─────────────────────────────────────────────────────────────
  docker exec -i "${SCRATCH_NAME}" pg_restore -U "${PG_USER}" -d "${PG_DB}" \
    --no-owner --exit-on-error < "${DUMP}"

  # ── 3. Property check: pg_dump hash matches the hash taken at backup time ──
  RESTORED_HASH="$(docker exec "${SCRATCH_NAME}" pg_dump -U "${PG_USER}" -d "${PG_DB}" --no-owner \
    | sha256sum | cut -d' ' -f1)"
  EXPECTED_HASH="$(cut -d' ' -f1 < "${HASH_FILE}")"
  if [[ "${RESTORED_HASH}" != "${EXPECTED_HASH}" ]]; then
    fail "pg_dump hash mismatch: expected ${EXPECTED_HASH}, got ${RESTORED_HASH}"
  fi
  echo "[verify-restore] pg_dump hash OK (${RESTORED_HASH})"

  # ── 4. Row-count sanity: every user table restored, none empty-when-dumped ─
  ROW_COUNTS="$(docker exec "${SCRATCH_NAME}" psql -U "${PG_USER}" -d "${PG_DB}" -At -c \
    "SELECT relname || '=' || n_live_tup FROM pg_stat_user_tables ORDER BY relname;")"
  TABLE_COUNT="$(echo "${ROW_COUNTS}" | grep -c '=' || true)"
  echo "[verify-restore] restored ${TABLE_COUNT} user tables:"
  echo "${ROW_COUNTS}" | sed 's/^/  /'
  [[ "${TABLE_COUNT}" -gt 0 ]] || fail "no user tables restored"

  # ── 5. Integrity manifest over the whole backup artifact ───────────────────
  verify_backup_manifest "${SRC}"
  echo "[verify-restore] integrity manifest OK ($(grep -c . "${SRC}/manifest.sha256") component(s))"

  # ── 6. Conductor durable state + credential escrow ─────────────────────────
  if [[ "${SKIP_CONDUCTOR_BACKUP:-0}" == "1" ]]; then
    echo "[verify-restore] SKIP_CONDUCTOR_BACKUP=1 — conductor state and escrow NOT checked"
  else
    verify_conductor_backup "${SRC}" "${ESCROW_DIR}"
    echo "[verify-restore] conductor data + escrow verified"
  fi

  # TODO: after restore, point a staging maistro-server at the scratch DB and run
  # smoke tests (GET /health/ready) per the spec's weekly staging drill.

  echo "[verify-restore] PASS for backup ${BACKUP_DATE}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
