---
inventory-delta:
  packages/maistro-core/tests: +9
---

# #1572 — refuse a missing PostgreSQL Goal schema

The prior wiring test claimed refusal but asserted an in-memory fallback.
Replace that assertion with `ConfigError` for a completely absent schema and
each individually missing Goal table, both with and without an available real
SQLite connection (one existing case becomes eight: +7). Check the migration
remedy, missing table names, all probes, and no SQLite schema writes on refusal.

Two additional cases prove a migrated PostgreSQL pool remains selected even
when SQLite is also available (+2). The pool double only implements the actual
`to_regclass` query. These are deterministic wiring tests, not substitutes for
live PostgreSQL conformance or installed-base migration acceptance. Existing
no-database memory, SQLite-only, Container authorization and live PG tests
remain.

Regression and final validation results are recorded in
`docs/testing/goal-1572-repair-20261007.md`.
