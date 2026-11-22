---
inventory-delta:
  packages/maistro-core/tests: +1
---

# 1151 SQLite recovery index serves the sweep's ordering

`tests/runs/test_sqlite_recovery_index.py` pins, via `EXPLAIN QUERY PLAN`,
that `idx_canonical_runs_status` carries the `(created_at, run_id)` ordering
`SqliteRunStore.list_by_status` asks for, so the canonical RUNNING
reconciliation sweep's bounded page walks the index instead of building a
temporary B-tree over the whole live population on every recovery tick.

This mirrors the PostgreSQL shape migration 057 shipped
(`ix_canonical_runs_status_created`): the ordering expressions follow `status`
in the index, so the `ORDER BY json_extract(payload, '$.created_at'), run_id`
page read needs no sort node. The SQLite side previously indexed `status`
alone, and the sweep's every-tick page paid a `USE TEMP B-TREE FOR ORDER BY`.

Fail-before: with the index on `(status)` alone the plan contains
`USE TEMP B-TREE FOR ORDER BY` and the assertion fails; the widened index
removes it.
