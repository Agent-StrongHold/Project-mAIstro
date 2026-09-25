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

Independent repair-phase validation (merge head `cc4ab4db7`, no code or test
changes in this phase — verification only): the full battery was re-executed
from scratch — `packages/maistro-core/tests/tasks` 315 passed,
`packages/maistro-server/tests/api` 356 passed, the three Hive bridge suites
`test_production_workspace_scope.py` / `test_workspace_scoped_submission.py` /
`test_adapter_ports.py` 23 passed (including the two-user E2E through real Hive
session logins with spoofed body user ids), `tests/migrations/` 97 passed
against a fresh `pgvector/pgvector:pg18` container (single-head chain,
upgrade-from-empty, round trip, and
`test_pre_provenance_receipts_become_explicit_system_work` asserting
`('system', 'system')`), plus `ruff check` / `ruff format --check`,
`check-suite-inventory.py`, `check-compose-secrets.py` and
`verify-monorepo-layout.sh`. Harness note for future runs: the live-Postgres
suites must be invoked with only `MAISTRO_TEST_DATABASE_URL` set — also
exporting `DATABASE_URL` silently overrides the fixtures' `DB_HOST/DB_PORT/
DB_NAME/DB_USER/DB_PASSWORD` scratch-database targeting
(`resolve_database_url` precedence), which shows up as spurious
`UndefinedTableError` failures in the store-leg suites, not as a fixture
guard.

Second independent repair-phase validation (merge head `54498b648`, which
merges develop's HITL workspace-authorization commit `60862b6c5`; no code or
test changes in this phase — verification only): re-executed
`packages/maistro-core/tests/tasks` + `tests/migrations/` 332 passed (80
skips without `MAISTRO_TEST_DATABASE_URL`),
`packages/maistro-server/tests/api` task-scope/rate-limit/webhooks 58 passed,
the four Hive bridge suites (`test_api`, `test_engine_service`,
`test_production_workspace_scope`, `test_workspace_scoped_submission`) 80
passed, `ruff check` / `ruff format --check`, `check-suite-inventory.py`,
`check-compose-secrets.py` and `verify-monorepo-layout.sh` all pass. The
live-Postgres chain suite was re-run against a scratch database on the
existing `pgvector/pgvector:pg18` container: 12 passed, including
`test_pre_provenance_receipts_become_explicit_system_work` (re-selected
individually for an explicit PASSED line) plus the named acceptance tests
`TestPrincipalIdentityKeying::test_delegated_users_have_independent_budgets_behind_one_service_key`,
`test_delegated_users_keep_distinct_task_and_run_ownership`,
`test_shared_bridge_keeps_two_authenticated_user_tasks_isolated` and
`test_system_delegation_has_an_explicit_system_actor`. `mypy` on
`maistro-core`/`maistro-server` reports only the 5 pre-existing
`import-not-found` errors for `maistro_bootstrap` stubs in `cli/` files this
branch does not touch. Integration-layer note: PR #1394's status checks have
now concluded — 3 failures (`test`, `quality`/Quality gate, Coverage gate) —
but against PR head `39bdab11f`, the OLD diverged lineage of `auto-1057`
(six linear commits based on trunk's former 038 head) that conflicts with
current develop (`mergeStateStatus: DIRTY`); this worktree's head is the
reconciled lineage (migrations renumbered to 041/042, audit-scope re-parent
`1c1504259`), so the recorded failures do not reproduce here — the remote
branch must be updated to this lineage before integration.
