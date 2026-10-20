#!/usr/bin/env bash
# Weekly restore-and-verify drill (SPEC-070226-fbe3 / ADR-081, #1881 + #88).
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
# Beyond the PostgreSQL oracle, the drill proves the Conductor's own
# authoritative state (#88 / the D-18 backup-gap audit): the backup must
# contain the conductor-data capture with a nonempty state.db, which must pass
# integrity/schema checks with historical Runs inspectable and fencing values
# preserved. secrets.age and user_credentials.enc are optional stores (the
# vault is provisioned lazily; user_credentials.enc appears with the first
# persisted credential), so each is verified — together with its escrow root —
# only when it was actually captured; when either is captured, the decrypt
# proof demands its escrowed root (admin.key for secrets.age,
# credential_master.key for user_credentials.enc) actually decrypt AND parse
# the backed-up payload — key/ciphertext existence checks alone pass even when
# a rotation left the volume copy and the escrow copy on opposite sides of the
# atomic swap, or the store was already corrupt.
#
# Distinct failure classes (all exit 1; the class is in the message):
#   artifact  — missing or corrupt backup artifacts (dump, evidence, hashes,
#               provenance, conductor-data, credential escrow)
#   restore   — the restore command itself failed
#   semantic  — restored schema/row-count evidence differs from the backup-time
#               evidence (real data loss or corruption)
#   verifier  — the verification machinery failed (scratch database not ready,
#               evidence could not be collected, no user tables restored,
#               age(1) or the python3 cryptography module missing for the
#               decrypt proofs)
#
# Explicit limits: this oracle proves structure and cardinality survive the
# restore (tables, columns, exact row counts). Cell-level content equality is
# out of scope; per-table contents beyond their counts are not compared.
#
# Callers may source this script and invoke verify_backup_manifest /
# verify_conductor_backup directly; main only runs when the script is executed.
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
SCHEMA_EVIDENCE="${SRC}/postgres-${PG_DB}.schema"
ROWCOUNT_EVIDENCE="${SRC}/postgres-${PG_DB}.rowcounts"
PROVENANCE="${SRC}/postgres-${PG_DB}.provenance"
DUMP_HASH_FILE="${SRC}/postgres-${PG_DB}.dump.sha256"
SCHEMA_HASH_FILE="${SRC}/postgres-${PG_DB}.schema.sha256"
ROWCOUNT_HASH_FILE="${SRC}/postgres-${PG_DB}.rowcounts.sha256"
# Same contract as backup.sh: set SKIP_CONDUCTOR_BACKUP=1 only for stacks that
# genuinely run no Conductor; anything else missing the conductor capture is
# the D-18 backup gap and must fail the drill.
SKIP_CONDUCTOR_BACKUP="${SKIP_CONDUCTOR_BACKUP:-0}"

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

verify_sha256() {
  local file="$1" hash_file="$2"
  [[ -f "${hash_file}" ]] || fail_artifact "no hash file at ${hash_file}"
  local expected actual
  expected="$(cut -d' ' -f1 < "${hash_file}")"
  actual="$(sha256sum "${file}" | cut -d' ' -f1)"
  [[ "${expected}" == "${actual}" ]] || fail_artifact "hash mismatch for ${file}: expected ${expected}, got ${actual} (corrupt backup artifact)"
}

# ── Integrity manifest: missing/corrupt components fail here, loudly ─────────
# backup.sh writes manifest.sha256 over every component of a real backup; a
# manifest-less artifact (e.g. the characterization harness's lib-driver
# output) is still verified per-component via the sidecar hashes above.
verify_backup_manifest() {
  local src="$1"
  [[ -f "${src}/manifest.sha256" ]] \
    || fail_artifact "no integrity manifest at ${src}/manifest.sha256 — re-run backup.sh (a backup without one cannot prove its components)"
  ( cd "${src}" && sha256sum -c --quiet manifest.sha256 ) \
    || fail_artifact "integrity manifest check failed — a backup component is missing or corrupt; do not restore from this backup"
}

# ── Conductor durable state + credential escrow (issue #88) ──────────────────
verify_conductor_backup() {
  local src="$1" escrow="$2"
  local data="${src}/conductor-data"

  [[ -d "${data}" ]] \
    || fail_artifact "conductor-data is missing from the backup — the authoritative Conductor state (state.db, secrets.age, user_credentials.enc) was not captured; this is exactly the D-18 backup gap"

  # state.db is the authoritative spine — every Conductor backup carries it.
  # secrets.age and user_credentials.enc are OPTIONAL: a supported Conductor
  # has no secrets.age until its optional vault is provisioned, and
  # user_credentials.enc is only written once the first credential is
  # persisted. A valid backup may therefore lack either, so each ciphertext is
  # verified, and its escrow root demanded, only when it was captured.
  [[ -s "${data}/state.db" ]] \
    || fail_artifact "conductor-data/state.db is missing or empty in the backup"
  local vault_captured=0 creds_captured=0
  if [[ -s "${data}/secrets.age" ]]; then vault_captured=1; fi
  if [[ -s "${data}/user_credentials.enc" ]]; then creds_captured=1; fi
  if [[ "${vault_captured}" -eq 0 && "${creds_captured}" -eq 0 ]]; then
    echo "[verify-restore] no secrets.age / user_credentials.enc captured — vault and per-user credentials were never provisioned at backup time; nothing ciphertext to verify"
  fi

  # state.db must be a usable SQLite database: intact, and carrying the
  # canonical spine (Workspaces, Runs/NodeRuns/Attempts), the graph
  # continuations with their fencing version, sessions, and the audit log.
  # Historical Run IDs are printed so the drill shows, not assumes, that the
  # restored Conductor can inspect its history.
  python3 - "${data}/state.db" <<'PY' || fail_artifact "state.db failed integrity/schema verification (see details above)"
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
  # Each root is demanded only when its ciphertext was actually captured; a
  # Conductor with neither optional store provisioned needs no escrow at all.
  if [[ "${vault_captured}" -eq 1 ]]; then
    [[ -d "${escrow}" ]] \
      || fail_artifact "credential escrow missing at ${escrow} — secrets.age was captured, so without the escrowed admin.key the vault is cryptographically unrecoverable and every stored secret is gone for good"
    [[ -s "${escrow}/admin.key" ]] \
      || fail_artifact "credential escrow at ${escrow} holds no admin.key — secrets.age is unrecoverable without it"
    grep -q "^# public key: " "${escrow}/admin.key" \
      || fail_artifact "escrowed admin.key is not an age identity file (missing '# public key:' header)"
  else
    echo "[verify-restore] secrets.age not captured — vault not provisioned at backup time; skipping vault escrow and decrypt proof"
  fi

  if [[ -d "${escrow}" && -f "${escrow}/manifest.sha256" ]]; then
    ( cd "${escrow}" && sha256sum -c --quiet manifest.sha256 ) \
      || fail_artifact "credential escrow manifest check failed — the escrowed keys do not match what backup.sh recorded; re-escrow from the off-host copy"
  elif [[ -d "${escrow}" ]]; then
    echo "[verify-restore] WARNING: escrow has no manifest.sha256 — cannot prove these keys are the ones backup.sh recorded"
  fi

  if [[ "${vault_captured}" -eq 1 ]]; then
    # THE decrypt proof: the escrowed identity actually opens the backed-up
    # vault. This is what turns "the key file exists" into "the restored
    # Conductor identity is usable".
    command -v age >/dev/null 2>&1 \
      || fail_verifier "age(1) not found on the drill host — install age to prove the escrowed identity decrypts the vault"
    local vault_plain=""
    if ! vault_plain="$(age --decrypt -i "${escrow}/admin.key" "${data}/secrets.age" 2>/dev/null)"; then
      fail_artifact "DECRYPT PROOF FAILED: the escrowed admin.key cannot decrypt the backed-up secrets.age — a restored Conductor would fail closed on its vault (SECRET_MISSING)"
    fi
    if [[ -n "${EXPECTED_SECRET_NAME:-}" ]]; then
      grep -Eq "^${EXPECTED_SECRET_NAME}( = |$)" <<< "${vault_plain}" \
        || fail_artifact "known secret '${EXPECTED_SECRET_NAME}' is not readable in the decrypted vault — check EXPECTED_SECRET_NAME against the provisioned vault"
      echo "[verify-restore] decrypt proof: escrowed admin.key decrypted secrets.age; known secret '${EXPECTED_SECRET_NAME}' is readable"
    else
      echo "[verify-restore] decrypt proof: escrowed admin.key decrypted secrets.age ($(grep -c . <<< "${vault_plain}" || true) secret line(s)); set EXPECTED_SECRET_NAME to pin a known secret"
    fi
  fi

  if [[ "${creds_captured}" -eq 1 ]]; then
    # user_credentials.enc disposition: its Fernet root must be escrowed too,
    # or every per-user provider token in the backup is unrecoverable.
    [[ -d "${escrow}" ]] \
      || fail_artifact "credential escrow missing at ${escrow} — user_credentials.enc was captured, so without credential_master.key its per-user provider tokens are unrecoverable"
    [[ -s "${escrow}/credential_master.key" ]] \
      || fail_artifact "credential escrow has no credential_master.key — user_credentials.enc (per-user provider tokens) is unrecoverable without it; re-escrow from the off-host copy"
    # THE decrypt proof for the credential store, mirroring the age-vault proof
    # above: existence and manifest checks pass even when the volume copy and
    # the escrow copy landed on opposite sides of an atomic key rotation (or
    # the store was already corrupt), so only decrypting AND parsing the
    # payload proves the escrowed key opens THIS ciphertext.
    python3 -c 'import cryptography.fernet' 2>/dev/null \
      || fail_verifier "python3 cryptography module not available on the drill host — it is needed to prove the escrowed credential_master.key decrypts the backed-up credential store"
    python3 - "${escrow}/credential_master.key" "${data}/user_credentials.enc" <<'PY' || fail_artifact "DECRYPT PROOF FAILED: the escrowed credential_master.key cannot decrypt the backed-up user_credentials.enc — every per-user provider token would be unreadable after restore (volume copy and escrow likely captured opposite sides of a rotation, or the store was already corrupt)"
import json
import sys

from cryptography.fernet import Fernet, InvalidToken

key_path, store_path = sys.argv[1], sys.argv[2]
try:
    with open(key_path, "rb") as fh:
        key = fh.read()
    with open(store_path, "rb") as fh:
        payload = Fernet(key).decrypt(fh.read())
except InvalidToken:
    print(
        "[verify-restore]   escrowed credential_master.key does not open "
        "user_credentials.enc (InvalidToken: key and ciphertext are from "
        "opposite sides of a rotation, or the store is corrupt)",
        file=sys.stderr,
    )
    raise SystemExit(1)
except Exception as exc:  # malformed key/ciphertext — not a key mismatch
    print(f"[verify-restore]   credential-store decrypt failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
try:
    records = json.loads(payload)
except ValueError:
    print("[verify-restore]   decrypted credential store does not parse as JSON", file=sys.stderr)
    raise SystemExit(1)
if not isinstance(records, dict):
    print("[verify-restore]   decrypted credential store is not a JSON object", file=sys.stderr)
    raise SystemExit(1)
print(
    f"[verify-restore] decrypt proof: escrowed credential_master.key decrypted "
    f"user_credentials.enc ({len(records)} credential record(s) parse as JSON)"
)
PY
  else
    echo "[verify-restore] user_credentials.enc not captured — no per-user credentials persisted at backup time; skipping credential_master.key escrow check"
  fi
}

main() {
  # ── 1. Artifact preflight: everything the oracle needs, integrity-checked ────
  [[ -f "${DUMP}" ]] || fail_artifact "no dump at ${DUMP}"
  [[ -f "${SCHEMA_EVIDENCE}" ]] || fail_artifact "no schema evidence at ${SCHEMA_EVIDENCE} (backup predates the #1881 evidence format; re-run backup.sh)"
  [[ -f "${ROWCOUNT_EVIDENCE}" ]] || fail_artifact "no row-count evidence at ${ROWCOUNT_EVIDENCE} (backup predates the #1881 evidence format; re-run backup.sh)"
  [[ -f "${PROVENANCE}" ]] || fail_artifact "no provenance at ${PROVENANCE}"

  verify_sha256 "${DUMP}" "${DUMP_HASH_FILE}"
  verify_sha256 "${SCHEMA_EVIDENCE}" "${SCHEMA_HASH_FILE}"
  verify_sha256 "${ROWCOUNT_EVIDENCE}" "${ROWCOUNT_HASH_FILE}"

  grep -q '^snapshot=' "${PROVENANCE}" || fail_artifact "provenance is missing the snapshot id"
  echo "[verify-restore] artifacts OK for ${BACKUP_DATE} ($(grep '^snapshot=' "${PROVENANCE}"))"
  grep '^server_version=' "${PROVENANCE}" || true

  if [[ -f "${SRC}/manifest.sha256" ]]; then
    verify_backup_manifest "${SRC}"
    echo "[verify-restore] integrity manifest OK ($(grep -c . "${SRC}/manifest.sha256") component(s))"
  else
    echo "[verify-restore] WARNING: no manifest.sha256 in ${SRC} — components verified via sidecar hashes only (re-run backup.sh to get a manifest-sealed backup)"
  fi

  echo "[verify-restore] restoring ${BACKUP_DATE} into scratch container ${SCRATCH_NAME}"

  # ── 2. Scratch PostgreSQL ────────────────────────────────────────────────────
  docker run -d --name "${SCRATCH_NAME}" \
    -e POSTGRES_USER="${PG_USER}" \
    -e POSTGRES_PASSWORD=scratch-only-not-a-secret \
    -e POSTGRES_DB="${PG_DB}" \
    "${PG_IMAGE}" >/dev/null

  # Readiness budget: 180 probes (~3 min). The drill's first CI appearance
  # (quality.yml coverage-gate, 2026-10-18) failed exactly here on a shared
  # runner: `docker run` had succeeded and the image was already cached, but a
  # runner congested by the same job's 12-minute root suite left initdb slower
  # than the old 60-probe budget, so the drill reported VERIFIER FAIL for
  # infrastructure rather than for the backup under verification. A probe that
  # finds the container gone reports the engine's last log lines immediately
  # instead of spinning out the remaining budget on a container that can no
  # longer become ready.
  #
  # The probe is pg_isready AND a real query. pg_isready alone also answers
  # during initdb's temporary-server window (it checks the socket, not the
  # final server), so a loop keyed on it alone can break mid-init, and the
  # restore that follows then fails as RESTORE instead of waiting out the
  # restart. Only the final server answers the query.
  scratch_ready() {
    docker exec "${SCRATCH_NAME}" pg_isready -U "${PG_USER}" >/dev/null 2>&1 \
      && docker exec "${SCRATCH_NAME}" psql -X -Atq -U "${PG_USER}" -d "${PG_DB}" -c 'SELECT 1' >/dev/null 2>&1
  }
  for _ in $(seq 1 180); do
    if scratch_ready; then
      break
    fi
    if [[ "$(docker inspect -f '{{.State.Running}}' "${SCRATCH_NAME}" 2>/dev/null)" != "true" ]]; then
      docker logs "${SCRATCH_NAME}" 2>&1 | tail -40 >&2 || true
      fail_verifier "scratch postgres container exited before becoming ready (last log lines above)"
    fi
    sleep 1
  done
  scratch_ready \
    || fail_verifier "scratch postgres did not become ready"

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

  # ── 6. Conductor durable state + credential escrow (issue #88) ───────────────
  if [[ "${SKIP_CONDUCTOR_BACKUP}" == "1" ]]; then
    echo "[verify-restore] SKIP_CONDUCTOR_BACKUP=1 — conductor state and escrow NOT checked"
  else
    verify_conductor_backup "${SRC}" "${ESCROW_DIR}"
    echo "[verify-restore] conductor data + escrow verified"
  fi

  # After restore, point a staging maistro-server at the scratch DB and run
  # smoke tests (GET /health/ready) — the spec's weekly staging drill; it is
  # operator-run, not automated here.

  echo "[verify-restore] PASS for backup ${BACKUP_DATE}: semantic evidence matches the backup snapshot"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
