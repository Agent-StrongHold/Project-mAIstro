---
inventory-delta:
  packages/maistro-core/tests: +5
---
# Task admission: SQLite root helper counts on a caller-supplied connection

`SqliteRunStore._admit_root` now takes the connection it counts and cleans up
on as a keyword argument; the real `create_run` caller passes its existing
`self._conn`, so runtime admission behavior is unchanged. Five maistro-core
node IDs arrive, all in `tests/runs/test_run_concurrency_limits.py`:

- `test_sqlite_root_helper_counts_on_supplied_connection` — the helper counts
  on the connection it was handed: two genuinely distinct initialized
  `:memory:` connections hold distinguishable active-root populations, the
  named savepoint is established on the supplied connection before the
  candidate row is inserted (matching `create_run`'s order), and the refusal
  must follow the supplied connection's population. A helper that read the
  store's own connection would count zero and admit.
- `test_sqlite_root_helper_refusal_rolls_back_only_supplied_savepoint` —
  controlled sentinel writes sit open on both connections; a refusal undoes
  the candidate row alone, the savepoint is released (not merely rolled
  back), neither connection's test-owned transaction is ended, and no helper
  commit occurs.
- `test_sqlite_count_read_failure_rolls_back_only_supplied_savepoint` — the
  same ownership proof when the count itself fails (the existing
  `BaseException` cleanup path, fault-injected at the now-explicit count
  seam rather than through the general `_fetchone` helper).
- `test_sqlite_count_cancellation_still_unwinds_the_supplied_savepoint` —
  cancellation hits the same cleanup, in the same order (rollback, then
  release, on the supplied connection), with the original exception identity
  propagating. No new cancellation semantics are decided.
- `test_sqlite_create_run_supplies_existing_connection_to_root_helper` — the
  real public `create_run` passes its own connection to the helper exactly
  once (object identity, real helper still executing).

`test_a_sqlite_count_that_fails_does_not_leave_its_row_for_the_next_commit`
is retained with the same failure proof; only its fault injection moved from
`store._fetchone` (which the helper no longer calls) to the module's
`_ACTIVE_ROOT_COUNTS_SQL` executed through the supplied connection. The
retained policy and rollback nodes
(`test_a_sqlite_refusal_leaves_a_sibling_stores_open_write_intact`,
`test_a_sqlite_refusal_with_no_open_transaction_leaves_none_open`,
`test_sqlite_counts_read_the_active_root_indexes`) are unchanged and pass.

Deliberate mutations — the helper reading `self._conn` for the count, and the
cleanup running on `self._conn` — were each shown to fail these tests before
the correct implementation was restored.
