# M2 #448 CI repair at 34379a166 — runtime DDL in PgAuditLog.ensure_schema

Round: CI-repair, lane L448, branch `auto-448`. Full evidence and gate output:
`docs/testing/inventory-notes/auto-448-ci-repair-pg-audit-runtime-ddl.md`.

## What was red and why (per-job log evidence, `gh api .../actions/jobs/<id>/logs`)

| check | job | cause |
|---|---|---|
| postgres (pg17/pg18) | 118633528887 / 118633528819 | `test_pg_audit.py::test_ensure_schema_adds_proof_columns_idempotently` → `'FakeConnection' object has no attribute 'transaction'` |
| coverage (no services) | 118633347128 | same, plus `test_container_wiring.py::test_audit_log_wiring_prefers_postgres_and_upgrades_its_schema` |
| coverage (PostgreSQL) | 118633347094 | same, `1 failed, 6285 passed` |
| test | 118633345746 | 3 reachability-baseline tests, `maistro.runs.admission_identity` (inherited) |
| Quality / Reachability | 118633347376 | `maistro.runs.admission_identity` NEWLY UNREACHABLE (inherited) |
| exact-debt-ledger | 118633345789 | reachability provenance; vulture clean 1326→1326 |
| Quality gate / integration-scope / gates-ran | aggregators over the above |

## Repair

`PgAuditLog.ensure_schema` is back to the idempotent `ADD COLUMN IF NOT EXISTS`
half (base behaviour) with a docstring recording why it must not own the table.
The 34379a166 version created `audit_log` at startup, which:

1. contradicts migration 036 (`org_id` must carry `server_default ''`);
2. bricks the chain — `ensure_schema()` then `alembic upgrade head` →
   `DuplicateTable: relation "audit_log" already exists` (proved on
   `pgvector/pgvector:pg17`).

New witness: `test_ensure_schema_never_fabricates_the_migrated_audit_table`
(throwaway database; must raise `UndefinedTableError` and leave
`to_regclass('audit_log')` NULL). Fails against 34379a166, passes now.

## Still open, NOT this lane's

`quality/reachability` + 3 root-suite tests + `exact-debt-ledger` +
`integration-scope` + `gates-ran` all reduce to `maistro.runs.admission_identity`
(develop #1851, no src importer, no baseline entry). The base tree fails the same
scan (`git archive e20e9f52e` + `check-reachability.py`); `git diff
origin/develop...HEAD -- quality/` is empty. Banking it needs an owner grant
landed on develop first (two-merge rule) and an architecture answer about
#1851's surface — deliberately not attempted here.
