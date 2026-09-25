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

## Round 4 (repair pass, lane auto-41)

Addressed the recorded findings against this head:

- **EXPECTED_TABLES / live migration chain (finding 1).** Already repaired on
  this branch by `eb6b7b36b` (chain-owned tables only; runtime-provisioned
  capability/workspace-lifecycle tables excluded). Re-verified against a fresh
  pgvector/pg18 server: `tests/migrations/test_migration_chain.py` 15 passed —
  `EXPECTED_TABLES` matches the live catalog exactly, head stamps via
  `_head_revision()`, and all four runtime-self-provisioning scenarios behave
  as asserted.
- **038 reconcile-path validation (finding 3).** Already repaired on this
  branch: full shape check (compiled type names, nullability, `completed_at`
  zero default, `scope_key` PK reconstruction, expiry index) plus loud refusal
  of foreign shapes. The salvaged uncommitted hunk comparing compiled type
  names (`str(actual["type"]).upper() != str(expected.type).upper()`) is kept
  and the file's `CLAIM_COLUMNS` comment updated to describe it: live
  PostgreSQL reflection hands back exactly `sqltypes.TEXT`/`sqltypes.BIGINT`
  (verified on the live server), so the comparison matches a real reconcile
  byte-for-byte while tolerating a dialect subclass that compiles to the same
  DDL. No gate weakened: missing columns, nullability, default, PK and index
  checks are untouched and still refuse.
- **Stale revision references.** The renumbering left `migration 034` docstring
  pointers in `maistro/tasks/idempotency.py` (the revision is now 038;
  `034_hitl_deadline_index` is unrelated). Corrected. Noted, out of this
  issue's scope: `capabilities/invocation_store.py` cites revision 034 for the
  capability schema, which now lives in `035_capability_invocations`.
- **LocalTaskBackend idempotency wiring (finding 2).** Already implemented:
  `LocalTaskBackend.__init__` takes `idempotency_store` and hands it to
  `TaskQueue`; the server (`main.py`) and conductor engine pass the container's
  claim store. Proven by the suites below.
- **#1176 tracker state (finding 4).** The issue remains open on GitHub;
  closing it is a GitHub mutation this worker is prohibited from performing.
  The durable admission-idempotency contract it owns is implemented and proven
  here.

Fresh evidence at this round's head (dedicated pgvector/pg18 container, port
55491): `test_migration_chain.py` 15 passed (live);
`test_idempotency_durable.py` 27 passed (`MAISTRO_TEST_PG_DSN`, chain at head);
core tasks 333 passed / 1 skipped; `test_tasks_idempotency.py` 13 passed;
`maistro-core/tests/integration` 5 passed (chat→graph E2E);
`test_engine_service.py` 35 passed; `ruff check`, `ruff format --check`, mypy
on `maistro/tasks/idempotency.py`, `check-suite-inventory.py`,
`check-doc-links.py`, `check-durable-table-inventory.py` all clean.
