---
inventory-delta:
  packages/maistro-core/tests: +23
  packages/maistro-turing/backend/tests: +1
---
# auto-325 round 3: diff-coverage closers for the purge contract's degenerate arcs (#325)

The merge-queue evaluation at `013b6a0e` failed the coverage gate on the
per-file diff floor: eight files of the #325 retention work measured below
90% lines / 80% branch arcs against base `3825fb9b5` because their purge
contracts were only proven along the happy path and the SQLite legal-hold
path. CI's own log named the uncovered lines; this round adds the missing
arcs as tests, not as exemptions. All 24 core-side tests run service-free
in the `coverage (no services)` producer except the three PostgreSQL legs,
which run in `coverage (PostgreSQL)`; the Turing test runs in the gate's
backend producer.

New/extended arcs, one per uncovered region CI named:

- `limit <= 0` is refused with `ValueError` by every purge implementation —
  SQLite delivery log and canonical events, PgEventStore, PgEventLog,
  PgAuditLog, SqliteAuditLog, PgStrikeTracker and PgRateLimiter — proving the
  guard fires before any pool I/O (the fake-pool variants assert zero
  statements issued).
- Legal holds bind on the PostgreSQL purges (`PgEventStore`,
  `PgEventLog`, `PgAuditLog`, `PgStrikeTracker`): the SQL scopes the DELETE
  with `user_id <> ALL($2::text[])` (or workspace/entity equivalents), moves
  the batch limit to `$3`, and the held rows survive a purge that removes
  their equally expired neighbors. `SqliteEventStore` gets the same arc on
  the SQLite side.
- A purge that fails mid-transaction (DELETE forced to error by a delegating
  connection double) raises, deletes nothing, and leaves the SQLite store
  usable — the rollback is proven by the next statement succeeding, which
  fails with "cannot start a transaction within a transaction" if the
  `BEGIN IMMEDIATE` was left open.
- The PG delete-status parse degrades to 0 on an unparseable status string
  (a reporting problem must not fail a committed purge).
- The stored-volume probe is amortized: a second purge inside the probe
  interval samples the table once, not per purge (SQLite delivery log,
  SQLite audit, PgAuditLog, PgEventLog, PgRateLimiter).
- Turing eviction (`execution.py`): when reclaiming a resumable Run's
  continuation state fails, the Run is left alone — not deleted, not
  orphaned, its tracking entry kept for the next sweep.

No production code changed in this round; the gate's own numbers were the
specification. Diff gate re-run locally with CI's exact invocation —
`scripts/check-diff-coverage.py coverage.xml --base 3825fb9b5...` over the
combined producers — reports `ok: every measured file this change touches is
at or above 90% lines / 80% branch arcs`.
