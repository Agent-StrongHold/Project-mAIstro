---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# Issue #41 CI-repair round 30: local coverage validation

No production or test code changed in this validation-only round. At
`47114d54de1cdce60fdad9b7dfe6d2150b055e3780`, the current branch head, the
CI-shaped publish-set producer completed and its aggregate report passed the
87% floor at 92%.

A real isolated PostgreSQL 17 database was then created on the local Docker
service and used for the migration producer. `tests/migrations` passed (104),
`alembic upgrade head` passed, and the configured core PostgreSQL suite passed
(4,884 passed, 8 skipped). The final Canvas PostgreSQL coverage invocation did
not complete: five `test_canvas_store_migration.py` fixture teardowns timed out
while issuing `DROP DATABASE ... WITH (FORCE)` after their test bodies had run.
This unrelated Canvas cleanup failure prevents claiming a complete local
reproduction of the combined coverage gate; no #41 code was changed to mask or
work around it.

The supplied deterministic logs pass, and the exact vulture ledger command
passes with 1,342 reviewed identities. The independent acceptance review still
finds the #1845 residual: `TaskQueue._admit_claimed` writes the canonical Run
through `_mint` and only then separately calls `store.complete`
(`packages/maistro-core/src/maistro/tasks/queue.py:276-320`). The SQLite
completion-write/store-recreation regression passes, but it is not the required
joint PostgreSQL Run+binding commit or process-kill/multi-replica evidence.
Those gaps remain assigned to #1845/#1325/#1855; this round neither changes
scope semantics nor introduces a second admission authority.
