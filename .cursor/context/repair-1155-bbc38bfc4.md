# Repair #1155 @ bbc38bfc4 (branch auto-1155) — 2026-09-23

## Verdict basis: fork repaired, single head restored, fresh-DB deploy path proven

### Change
- `alembic/versions/036_audit_log_org_scope.py`: `down_revision` "039" -> "040"
  (develop chain tip). Merges 685c1c118 (f695d491, adds 040) and e1058db0
  (5f7088dd) had restored the two-head fork that repair e5ca3dbf7 warned about;
  its integration note said single-head "must be re-reconciled at the develop
  merge". Docstring now records the full re-parent history (035 -> 038 -> 039
  -> 040), mirroring 040's own reconciliation note.
- `tests/migrations/test_audit_scope_migration.py`: head test now asserts
  `down_revision == "040"` and single head.
- `docs/testing/inventory-notes/1155-audit-migration-online.md`: records the
  second reconciliation.

### Executed evidence at bbc38bfc4
- `uv run alembic heads` -> exactly one head: 036_audit_log_org_scope.
- Fresh PG18 DB (repair1155 on auto-1155-audit-pgvector @127.0.0.1:55462):
  `DATABASE_URL=... uv run alembic upgrade head` -> full chain runs through
  040 -> 036_audit_log_org_scope, exit 0. Schema verified: org_id text
  nullable default ''::text; ix_audit_log_scope btree (org_id, "timestamp").
  Downgrade 036_audit_log_org_scope -> 040 drops both; re-upgrade restores.
- `uv run pytest tests/migrations -q` -> 17 passed, 79 skipped (the 4 fork
  failures from e1058db0 now pass).
- MAISTRO_TEST_PG_DSN battery: pg+sqlite audit + sentinel audit = 36 passed,
  0 skipped, incl. test_real_postgres_two_org_scope_and_schema (org-a/org-b
  isolation on real PG; previously UNVERIFIED).
- Full battery (migrations + persistence + sentinel + policy + redaction):
  110 passed, 67 skipped.
- Gates: ruff check, ruff format --check, check-suite-inventory,
  check-doc-links, check-vulture-baseline, check-radon-baseline -> all exit 0.

### Residual (unchanged from prior findings, not #1155)
- packages/maistro-core/tests/security/test_log_redaction.py::
  test_install_is_idempotent fails deterministically at head and at develop
  base (pre-existing since initial release; untouched by this branch).
- If develop later lands another migration whose parent is 040, the fork risk
  recurs at the next merge — reconciliation duty is recorded in the inventory
  note and the migration docstring.
