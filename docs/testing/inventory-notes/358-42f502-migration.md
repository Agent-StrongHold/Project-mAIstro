---
inventory-delta:
  tests/: +1
---
# Issue #358 audit migration collision repair

`tests/migrations/test_migration_chain.py` adds one real PostgreSQL regression:
upgrade from the existing learning-lifecycle revision through the audit-index
migration, verify all eight ordered scope indexes, downgrade just the audit
migration, and verify audit rows and preceding learning schema survive.

Existing revision uniqueness/reachability tests reproduce the duplicate `053`
regression without PostgreSQL. The adjacent capability-index chain-tip assertion
advances to `054` and continues to assert every existing ancestor is reachable.

Executed results and residual gate prerequisites are recorded in
`docs/testing/358-42f502-repair.md`.
