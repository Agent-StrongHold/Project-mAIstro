---
inventory-delta:
  packages/maistro-core/tests: +7
---
# aud12-v2-38ca

7 new tests cover PR #1528's diff-coverage gap: 5 branch arcs in `state.py`
this PR itself added (the migration-retry/WAL-switch/duplicate-username-
warning code) went unexercised by any existing test.

- `tests/state/test_state_gaps.py::TestRetryOnLocked` (4 tests) — the new
  `_retry_on_locked` static helper: zero-attempts loop-exit, a transient
  "locked" error that retries then succeeds, a non-"locked"
  `OperationalError` that raises immediately, and a persistent "locked"
  error that still raises once attempts are exhausted.
- `tests/state/test_writer_concurrency.py::test_migration_recheck_treats_a_concurrent_winner_as_success`
  (1 test) — the cross-process race recheck in `run_migration`'s except
  handler, modelled in-process via a connection-substitution proxy (same
  pattern as the file's existing `_PausingConn`) rather than forked
  children, since branch coverage from actual forked processes never
  reaches this repo's `coverage run` invocation.
- `tests/state/test_persisted_store.py` (2 tests) — the bounded-wait
  timeout guards in `put_model_unique`/`put_model_if_unique`, exercised via
  a new optional `timeout` keyword (default unchanged at 30.0s, mirroring
  the existing convention on `put_raw_if_absent`).

No production behavior changed for existing callers.
