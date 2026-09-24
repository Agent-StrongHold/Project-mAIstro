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
