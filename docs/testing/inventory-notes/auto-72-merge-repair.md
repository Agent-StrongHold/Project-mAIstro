---
inventory-delta:
  packages/maistro-server/tests: +1
---

# auto-72 merge repair (develop ba2f1f077 into auto-72)

Resolves the duplicate #1157 implementations (`persistence/sqlite_schema.py`'s
`begin_schema_upgrade` versus trunk's `maistro/sqlite_schema.py`) in favor of
trunk's `serialized_schema_upgrade`: all seven SQLite stores, the usage log's
`ensure_schema`, and `SqliteElevationStore` now upgrade inside the shared
`BEGIN IMMEDIATE` critical section; the duplicated module is gone. The
usage-log snapshot/restore keeps the event-identity design (stable `event_id`,
`INSERT OR IGNORE` + unique index, per-instance flush lock), which subsumes
trunk's watermark approach for #1204 — overlapping flushes and same-timestamp
events cannot double-count one logical usage event.

The alembic clash (both sides claimed revision "036") is resolved by attaching
`elevation_grants` at the end of the trunk chain as revision "039"
(down-revision "038"); `EXPECTED_TABLES` in `tests/migrations/` gains the
`elevation_grants` table so the live-catalog assertion stays exact.

Health truthfulness (#72): the container now records `stores_memory_backed`
when a pathless `sqlite://` wires the durable-twin classes over SQLite's
in-memory database, and `_persistence_diagnostics` reports those families as
`durable: false` with an explicit restart-ephemeral note instead of trusting
the class-name prefix.

New test: `test_persistence_diagnostics_report_memory_backed_sqlite_as_ephemeral`
(packages/maistro-server/tests/api/test_health.py) pins that disposition.
Validation: persistence suite 613 passed / 0 skipped against a migrated
pgvector:pg18 (chain applied 001 -> 039), migration-chain suite 11 passed,
ruff and mypy clean.
