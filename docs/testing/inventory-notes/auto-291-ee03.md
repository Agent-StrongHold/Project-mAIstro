---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# auto-291 repair: allocation refuses an unindexed legacy username row

Repair round for the #291 check battery. The driver's targeted run
(`test_api.py` + `test_identity_health.py` + `test_setup_guard.py`)
failed `test_api.py::test_register_duplicate_username` with 200 instead
of 409 — a failure the full-suite ordering masks (the first
session-scoped `authed_client` use in `test_agents_routes.py` logs in as
`testuser`, and `resolve()`'s `migrate_or_index_one` then creates the
claim *before* the per-test `_isolate_username_claims` snapshot, so every
later test inherits it).

The production gap behind the ordering accident:
`username_registry.create_users` — unlike `resolve()`/`is_claimed()` —
never self-healed rows the claim index had not seen. A user row that
appeared after startup migration through a path outside the registry
(direct store write, restored snapshot, test seed) was invisible to
allocation, so `/v1/auth/register` could mint a second identity under an
existing login name in memory mode. Durable mode already refuses that
duplicate via the unique-claim transaction; this brings memory mode to
parity by running `migrate_or_index_one` for each batch name inside the
allocation lock before the claim check.

Test delta: `+1` node in `packages/hive-conductor/backend/tests` —
`test_username_registry.py::test_allocation_refuses_an_unindexed_legacy_row`
seeds a claim-less legacy row and proves `create_users` raises
`UsernameTakenError`, creates no rival account, and indexes the
discovered row. Full backend suite after the change: 2779 passed,
5 skipped (2784 collected).
