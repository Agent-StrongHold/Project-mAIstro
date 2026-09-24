---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  tests/: +1
---
# Issue 41 repair

Added one Hive Conductor regression test proving the demo LocalTaskBackend
passes the canonical task-admission claim store into TaskQueue, and one live
PostgreSQL migration-chain test proving migration 034 refuses a table whose
column names match but whose type/default does not.

## Round 2 (verification pass, lane auto-41)

Live-PostgreSQL validation against a fresh pgvector/pg18 server exposed two
real failures that the recorded findings missed:
`TestTheChainSurvivesRuntimeSelfProvisioning::test_upgrade_head_adopts_the_runtime_provisioned_table`
and `::test_adopts_runtime_provisioned_table_without_a_primary_key` both
asserted `alembic_version == [("038",)]` after `upgrade head`. That literal was
written when 038 was the chain tip; the reconciliation onto develop's chain
(`038 -> 039 -> 040 -> 036_audit_log_org_scope`) moved the tip, so the
production upgrade reached head correctly while the tests kept demanding the
old revision id.

Fix: both assertions now compare against `_head_revision()`, resolved from
`alembic heads` at run time, so the assertion stays about "the upgrade stamped
the chain's head" rather than about a revision number that belongs to history.
The behavioral checks those tests exist for (claim columns, expiry index,
primary-key reconstruction) were already asserting correctly and are untouched.
No production code changed in this round; all 15 tests in the file pass against
a live server, and `scripts/check-suite-inventory.py` records the consolidated
delta in `auto-41-5cc9.md`.

## Round 3 (final validation record, head 03f512946)

Full battery re-run at the finished head; no code changed, evidence only.
Against a fresh pgvector/pg18 server (`MAISTRO_TEST_DATABASE_URL`):
`tests/migrations/test_migration_chain.py` 15 passed — `EXPECTED_TABLES`
matches the live catalog exactly, and all four runtime-self-provisioning
scenarios (adoption, PK-less adoption, incompatible-type refusal, foreign-shape
refusal) behave as asserted. The chain applies `038 -> 039 -> 040 ->
036_audit_log_org_scope` to head on a clean database. With the chain applied and
`MAISTRO_TEST_PG_DSN` set, `test_idempotency_durable.py` 27 passed including the
real-server reconcile test (`quota_usage` requires the full schema, which is why
the DSN-only run must follow `alembic upgrade head`). Sans DSN, the core tasks
suite is 333 passed / 1 skipped, `test_tasks_idempotency.py` 13 passed,
maistro-server API 359 passed, integration E2E 5 passed,
`packages/maistro-core/tests/runs` + `graph/durable_runs` 1324 passed / 224
skipped, hive-conductor 2661 passed / 1 skipped. `ruff check`,
`ruff format --check`, the six-package mypy command from AGENTS.md (713 files),
`check-suite-inventory.py`, `check-doc-links.py`, and
`check-durable-table-inventory.py` all pass. Residual (out of tree scope):
issue tracker closure of #1176 is a GitHub mutation workers are prohibited from
performing; the code contract it owns is implemented and proven here.
