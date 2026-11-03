---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #860 — include epistemic upgrades in the schema-fence regression

At `b5b2f2c5bac2a9c18ef4193ae03fa24bcdfb3b4c`, the existing
`test_ensure_schema_fences_ddl_behind_advisory_lock` failed: production executes
21 DDL statements, while the assertion still expected eight. The thirteen
additional epistemic/lifecycle column upgrades already run inside the same
transaction and advisory lock in `PgLearningStore.ensure_schema()`.

Update the independently enumerated expected SQL prefixes, retaining exact
statement count/order, transaction entry first, advisory lock before any DDL,
and commit last. Do not derive expectations from production constants or
remove locking assertions. No production behavior changes and no test IDs
are added, removed, or renamed (delta zero).

This is production-method SQL-ordering coverage using a recording connection,
not live PostgreSQL concurrency or RC soak evidence. Executed validation and
mutation outcomes: `docs/testing/soak/issue-860-7396ee0e-repair.md`.
