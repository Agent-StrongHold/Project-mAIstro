---
inventory-delta:
  added: []
  modified:
    - packages/hive-conductor/backend/tests/conftest.py
  removed: []
  rationale: >-
    Repair round for lane L53 (issue #53) after the develop-sync merge
    (961439b01). The previous verify battery failed on
    test_api.py::test_register_duplicate_username (expected 409, got 200).
    Root cause is inherited from develop's #1061 username-registry refactor,
    not from the merge itself: the register route's duplicate authority is
    now the atomic username-claim allocation (create_users), which does not
    index legacy rows, while the shared test conftest seeded testuser AFTER
    initialize_stores() had already run migrate_legacy_claims() — so the
    seeded row never received a canonical claim and could be re-registered.
    Confirmed failing standalone on pure develop ca4caec7d (scratch detached
    worktree probe). The fix mirrors production ordering (seed, then
    migrate) by re-running migrate_legacy_claims() after _seed_test_user()
    in the session-scoped _init_engine fixture. No production code changed.
---

# auto-53 post-merge repair (round 3, job 97493f01)

## Failure being repaired

Previous verify (job a77453f62, check-4.log):

    FAILED packages/hive-conductor/backend/tests/test_api.py::test_register_duplicate_username
    assert 200 == 409

Run with `-x`, everything before it passed; running the file without `-x`
showed 13 follow-on failures (test_whoami_authenticated, test_user_can_chat,
elevate/logout flows) all caused by the duplicate registration re-creating
`testuser` with password `otherpass1`, breaking every later
`_login("testuser", "testpass")`.

## Root cause chain

1. `routes/auth.py::register` (develop side of the merge, #1061) detects
   duplicates only through `username_registry.create_users`, whose
   `_reject_existing_claims` consults the claim index — it never
   legacy-indexes rows. The branch-side pre-check `_username_taken()`
   (which calls `migrate_or_index_one`) was dropped by develop's refactor.
2. Production is fine: `stores.initialize_stores()` seeds users and then
   runs `migrate_legacy_claims()`, so every durable row is indexed before
   the route can be reached.
3. The shared test conftest bypassed that ordering:
   `_init_engine` called `initialize_stores()` (users empty at that point)
   and only afterwards `_seed_test_user()` — leaving `testuser`/`testadmin`
   as unindexed legacy rows.
4. Login still worked (login resolves through `resolve()`, which
   lazy-indexes), and `_isolate_username_claims` wipes any claim a test
   created, so the gap never self-healed before the duplicate test ran.
5. Ground truth: the test also fails on pure develop `ca4caec7d` (verified
   in a detached scratch worktree, since removed). The merge merely made
   the lane battery the first place that ran it.

## Fix

`packages/hive-conductor/backend/tests/conftest.py::_init_engine` now re-runs
`migrate_legacy_claims()` after `_seed_test_user()`, reproducing production's
seed-then-migrate order. The seeded claims are created during session setup,
so every per-test `_isolate_username_claims` snapshot carries them and they
persist for the whole session.

No test expectations changed; no production code changed.

## Evidence

- Single test + neighbors: 3 passed.
- Lane battery (check-4 argv, no -x): 186 passed across the 10 files.
- Whole backend suite (shared conftest blast radius):
  `pytest packages/hive-conductor/backend/tests -q` → 2813 passed, 6 skipped.
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- `uv run pytest packages/maistro-core/tests/test_container_chat_runs.py -q -x`
  → 43 passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0,
  1412 → 1412 identities, unclassified 0, never_allowlist 0.
