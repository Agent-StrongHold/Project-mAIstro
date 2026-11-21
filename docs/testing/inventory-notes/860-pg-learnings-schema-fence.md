---
inventory-delta:
  packages/maistro-core/tests: +1
  packages/maistro-server/tests: +1
---
# Issue #860 — concurrency regression tests

Adds `test_ensure_schema_fences_ddl_behind_advisory_lock` in
`packages/maistro-core/tests/persistence/test_pg_learnings.py`, asserting schema
DDL is enclosed in one transaction and the advisory lock precedes all upgrades.
It also records the added concurrency/backpressure regression test in
`packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`.
These additions contribute one collected node to each package suite.
