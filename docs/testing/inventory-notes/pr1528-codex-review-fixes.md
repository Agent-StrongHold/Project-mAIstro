---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-core/tests: +9
---
# pr1528-codex-review-fixes

Tests added while fixing the 4 Codex review findings on PR #1528 (#1248's
username-registration race fix). No tests were removed or renamed; both
deltas are pure additions.

- `packages/hive-conductor/backend/tests`: `+2` — `test_setup_guard.py` gains
  `test_identical_admin_and_user_usernames_are_rejected_before_any_write` and
  `test_identical_usernames_rejected_on_direct_call_too`, pinning finding 1's
  fix: `SetupCompleteBody` now rejects `admin_username == user_username`
  (case-insensitively) via a `model_validator`, before either account write
  can land. Before the fix, identical usernames let the admin write commit
  and then made the user write fail on the store's own uniqueness
  enforcement, after which the durable setup claim was retained (an account
  now existed) and the request returned an unretryable 500.

- `packages/maistro-core/tests`: `+9` — all in `state/`:
  - `test_writer_concurrency.py` gains
    `test_independent_processes_apply_first_run_migrations_exactly_once`
    (finding 3): 8 real OS processes (`multiprocessing`, `fork`) race
    `PersistedStore.initialize()` against one fresh database. Reproduced
    against the pre-fix code before this test existed: 4 of 5 trials with 8
    concurrent processes failed with `MigrationFailedError` or a raw
    "database is locked"; against the fix, 0 of 30 trials with 10 processes
    failed. The fix: `State.run_migration` now re-checks `schema_migrations`
    after a failed apply and treats a concurrent winner as success instead of
    raising, `open_writer` sets `PRAGMA busy_timeout` before the WAL-mode
    switch (was set after it, too late to cover that specific statement),
    and a bounded retry covers the WAL switch's own first-open handshake,
    which isn't fully covered by `busy_timeout` in practice.
  - `test_persisted_store.py` gains `TestDuplicateUsernameMigrationReconciliation`
    (3 cases, finding 2) covering `PersistedStore.initialize()`'s new warning
    for `users` rows whose duplicate username the `kv_unique_fields_001`
    backfill's `INSERT OR IGNORE` could not claim (pre-existing legacy data
    only, since `put_model_unique` prevents new duplicates) — asserting the
    warning fires with the right unclaimed keys, does not fire when usernames
    are unique, and re-fires on every `initialize()` rather than once.
  - `test_persisted_store.py` gains `TestUsernameUniquenessDatabaseBoundary`
    (5 cases, finding 4) for the new `kv_users_username_unique_001` migration
    — a real SQL `UNIQUE` index on `kv_store` itself — covering: the index is
    created on a clean DB; an old-version writer using the generic `put()`
    path (which never consults `unique_fields`) is rejected at the DB layer
    when it would create a duplicate username, closing the mixed-version
    rolling-upgrade gap the finding describes; that same old-version path
    still works for a non-colliding rename; a DB with pre-existing legacy
    duplicates degrades to a logged warning instead of crashing startup; and
    the index is created retroactively once an operator resolves those
    duplicates and restarts.
