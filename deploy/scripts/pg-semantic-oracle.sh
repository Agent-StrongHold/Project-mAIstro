#!/usr/bin/env bash
# Shared semantic restore-verification oracle (#1881, SPEC-070226-fbe3 / ADR-081).
#
# Sourced by backup.sh (producer) and verify-restore.sh (consumer) so both use
# the SAME evidence definitions. The oracle is deliberately independent of
# pg_dump's byte output:
#   * two pg_dump runs taken without a shared snapshot can describe different
#     database states under concurrent writes, and
#   * PostgreSQL >= 17 plain-text output embeds a random psql restrict key by
#     default, so raw dump bytes differ even for unchanged semantic state.
# Instead, verification evidence records:
#   * a schema inventory (every column of the 'public' schema), and
#   * exact per-table row counts,
# each computed inside a REPEATABLE READ transaction. backup.sh additionally
# binds the authoritative pg_dump archive and the evidence to ONE exported
# snapshot (pg_export_snapshot + pg_dump --snapshot), so concurrent writes
# cannot make the archive and its expected evidence disagree.
#
# Explicit limits: this oracle proves structure and cardinality (tables,
# columns, row counts survive restore). It does not prove cell-level content
# equality; that would need per-row checksums and is out of scope here.
#
# Security: pg_dump/psql security defaults are preserved. No --restrict-key
# is set anywhere (a known key would let a malicious server inject psql
# meta-commands), and dump SQL is never rewritten to force equality.
#
# A sourcing script MUST define oracle_psql() before calling any function
# here. It receives psql arguments and must run them against the target
# database, e.g.:
#   oracle_psql() { compose exec -T "${PG_SERVICE}" psql -U "${PG_USER}" -d "${PG_DB}" "$@"; }
# or, against a scratch container:
#   oracle_psql() { docker exec "${SCRATCH_NAME}" psql -U "${PG_USER}" -d "${PG_DB}" "$@"; }
#
# oracle_begin_snapshot() additionally talks to psql as a long-lived
# coprocess and must read its output mid-session. psql block-buffers stdout
# when it is a pipe, so the producer should define oracle_psql_coproc() with
# line buffering applied INSIDE the container (stdbuf lives in the postgres
# image, next to psql); otherwise the snapshot id may never reach the caller:
#   oracle_psql_coproc() { compose exec -T "${PG_SERVICE}" stdbuf -oL psql ... "$@"; }
# If it is not defined the library falls back to oracle_psql(), which works
# only where stdout is already line-buffered.

# Schema inventory of the 'public' schema: one pipe-separated row per column,
# ordered so the file diffs stably. Column defaults are inlined (empty when
# NULL) so every record has the same field count.
#
# The type is read from pg_catalog with format_type(atttypid, atttypmod), NOT
# from the information_schema data_type view: that view collapses arrays to
# 'ARRAY' and every non-built-in type (domains, extensions such as pgvector)
# to 'USER-DEFINED', hiding the type modifier entirely — so restoring a
# vector(1536) column as vector(768) would record identical evidence and the
# drill would PASS for an incompatible schema. format_type renders the full
# identity instead: 'vector(1536)', 'numeric(10,2)', 'text[]', the underlying
# type of a domain.
ORACLE_SCHEMA_SQL="SELECT c.relname || '|' || a.attname || '|' || pg_catalog.format_type(a.atttypid, a.atttypmod) || '|' || CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END || '|' || coalesce(pg_catalog.pg_get_expr(ad.adbin, ad.adrelid), '') FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid = a.attrelid JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace LEFT JOIN pg_catalog.pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum WHERE n.nspname = 'public' AND a.attnum > 0 AND NOT a.attisdropped ORDER BY c.relname, a.attnum;"

# Exact per-table row counts of the 'public' schema, as 'table=count', ordered
# by table name. count(*) runs per table so the numbers are exact (unlike the
# pg_stat_user_tables estimates) and repeatable inside one snapshot.
ORACLE_ROWCOUNTS_SQL="SELECT c.relname || '=' || (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', n.nspname, c.relname), false, true, '')))[1]::text FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind = 'r' AND n.nspname = 'public' ORDER BY c.relname;"

oracle_require_psql() {
  if ! declare -F oracle_psql >/dev/null; then
    echo "[pg-semantic-oracle] FAIL: sourcing script must define oracle_psql()" >&2
    return 1
  fi
}

oracle_psql_coproc() { oracle_psql "$@"; }

# Begin a REPEATABLE READ, READ ONLY transaction in a psql coprocess, export
# its snapshot, and leave the transaction OPEN, so a pg_dump run with
# --snapshot=<id> and evidence reads all observe exactly the same state.
# Sets ORACLE_SNAPSHOT to the snapshot id; call oracle_end_snapshot when done.
# MUST be called in the main shell: the exporting coprocess lives as long as
# the calling shell does, so wrapping this call in a command substitution (or
# any other subshell) would close its stdin and roll the snapshot away before
# pg_dump can adopt it.
oracle_begin_snapshot() {
  oracle_require_psql || return 1
  coproc ORACLE_TX { oracle_psql_coproc -X -Atq -v ON_ERROR_STOP=1; }
  # Capture the coprocess PID immediately: bash unsets the transient
  # ORACLE_TX_PID variable once the coprocess is reaped, which can happen
  # right after oracle_end_snapshot closes its stdin; callers run under
  # set -u, so wait must use this saved copy instead of the special var.
  ORACLE_TX_PID_SAVED="${ORACLE_TX_PID}"
  local snap
  if ! printf 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot();\n' \
      >&"${ORACLE_TX[1]}"; then
    echo "[pg-semantic-oracle] FAIL: could not talk to the snapshot-export session" >&2
    return 1
  fi
  if ! read -t 30 -r snap <&"${ORACLE_TX[0]}" || [[ -z "${snap}" ]]; then
    echo "[pg-semantic-oracle] FAIL: pg_export_snapshot() returned no snapshot id (is oracle_psql_coproc line-buffered?)" >&2
    return 1
  fi
  # Consumed by the caller (see the function's comment about the main shell).
  # shellcheck disable=SC2034
  ORACLE_SNAPSHOT="${snap}"
}

# Collect semantic evidence into $1 (schema inventory) and $2 (row counts).
# With $3 set to a snapshot id from oracle_begin_snapshot, each query runs in
# its own REPEATABLE READ transaction adopting that snapshot; without it the
# queries run in fresh transactions (fine for an idle scratch database).
oracle_collect_evidence() {
  oracle_require_psql || return 1
  local schema_file="$1" rowcounts_file="$2" snap="${3:-}"
  local begin="BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;"
  [[ -z "${snap}" ]] || begin+=" SET TRANSACTION SNAPSHOT '${snap}';"
  oracle_psql -X -Atq -v ON_ERROR_STOP=1 \
    -c "${begin}" -c "${ORACLE_SCHEMA_SQL}" -c "COMMIT;" > "${schema_file}" || return 1
  oracle_psql -X -Atq -v ON_ERROR_STOP=1 \
    -c "${begin}" -c "${ORACLE_ROWCOUNTS_SQL}" -c "COMMIT;" > "${rowcounts_file}" || return 1
}

# End the snapshot-exporting transaction opened by oracle_begin_snapshot.
oracle_end_snapshot() {
  local rc=0
  if ! printf 'COMMIT;\n' >&"${ORACLE_TX[1]}"; then
    rc=1
  fi
  eval "exec ${ORACLE_TX[1]}>&-" 2>/dev/null || true
  wait "${ORACLE_TX_PID_SAVED}" 2>/dev/null || rc=1
  return "${rc}"
}
