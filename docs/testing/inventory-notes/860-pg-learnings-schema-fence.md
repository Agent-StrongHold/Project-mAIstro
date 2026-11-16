---
inventory-delta:
  packages/maistro-core/tests: +1
---
# Issue #860 — PostgreSQL learnings schema-fence regression test

Adds `test_ensure_schema_fences_ddl_behind_advisory_lock` in
`packages/maistro-core/tests/persistence/test_pg_learnings.py`. The test asserts
schema DDL is enclosed in one transaction and that the advisory lock is taken
before all upgrades, preventing concurrent replica boots from racing schema
creation. The test adds one collected node to the `packages/maistro-core/tests/`
suite.
