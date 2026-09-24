---
inventory-delta:
  packages/maistro-core/tests: +4
  packages/maistro-server/tests: +3
  packages/hive-conductor/backend/tests: +1
  tests/: +1
---

# #1057 — task principal delegation

Adds contract coverage for the signed Conductor-to-maistro-server delegation envelope,
server-side effective actor binding and two-principal task isolation. The adapter tests
cover propagation of signed user context and fail-closed configuration; the existing
production task bridge tests are updated to provide the required host key. The migration
repair adds live-schema coverage for classifying pre-provenance receipts as explicit
system work, while queue restore coverage rejects a partially migrated ownerless receipt.

Repair-phase re-validation (no test count change): the full battery was re-executed
independently on head `cfe012006` after the 040 re-chain —
`packages/maistro-core/tests/tasks` (315 passed), `packages/maistro-server/tests/api`
(356 passed), the Hive bridge suites `test_production_workspace_scope.py` /
`test_workspace_scoped_submission.py` / `test_adapter_ports.py` (23 passed, including the
two-user E2E through real Hive session login), and the live-PostgreSQL migration chain
(12 passed against `pgvector/pgvector:pg18`, including `test_pre_provenance_receipts_become_explicit_system_work`
asserting `('system', 'system')` for a pre-#1057 row). `ruff check` / `ruff format --check`,
`check-suite-inventory.py`, `verify-monorepo-layout.sh` and `check-compose-secrets.py` all
pass.

Second repair phase (merge head `765284d1d`, one production-code edit + one test-assertion
update): executing `tests/migrations/test_migration_chain.py` against a live
`pgvector/pgvector:pg18` reproduced a real fork — the `8bb344e32` develop sync brought
develop's `036_audit_log_org_scope` (`down_revision = "040"`) while this branch had already
taken 040's child slot with `041_task_identity_provenance`, so `alembic upgrade head` died
with rc 255, "Multiple head revisions are present" (10 of 12 chain tests failed before the
fix). Following the reconciliation convention recorded in the audit revision's own
docstring, `036_audit_log_org_scope` was re-parented onto this branch's chain tip
`042_task_receipt_dispatch_inputs`, and the hard-coded parent assertion in
`tests/migrations/test_audit_scope_migration.py::test_audit_scope_migration_is_the_single_head`
was updated to match (the generic single-head guards in `test_single_migration_head.py` /
`test_revision_metadata.py` passed unchanged). Re-executed after the fix on a fresh
pg18 container: `tests/migrations/` 97 passed (including `upgrade head` on an empty
database, the round-trip, and the explicit-system-actor legacy-receipt check),
`packages/maistro-server/tests/api` 356 passed, `packages/maistro-core/tests/tasks` 315
passed, Hive bridge suites 50 passed, `ruff check` / `ruff format --check`,
`check-compose-secrets.py` and `verify-monorepo-layout.sh` all pass.
