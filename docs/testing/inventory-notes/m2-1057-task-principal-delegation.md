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
