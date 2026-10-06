---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---

# 1453-unindexed-legacy-username-allocation

Added two regression tests to `test_username_registry.py` covering the
fail-closed rejection of a username whose only holder predates the claim
index. `test_create_users_indexes_an_unmigrated_legacy_row_instead_of_duplicating_it`
exercises memory mode (the shape the hive test harness hits: users seeded
directly into the store after startup migration already ran) and asserts that
`create_users` raises `UsernameTakenError`, writes no second account, and
leaves the lazily created claim naming the ORIGINAL row so login keeps
resolving to it. `test_create_users_indexes_an_unmigrated_durable_legacy_row`
covers the same scenario against a SQLite-backed store where the legacy row
was written before the registry bound.

Motivation: the atomic-allocation repair (#1061/#1453) replaced the
registration scan of `stores.users` with a pure claim-index check, so an
unindexed legacy row no longer blocked re-registration of its name; the
duplicate then hijacked the canonical claim and every later login for that
username resolved to the attacker-controlled account. This is deterministic
and reproducible on develop (14 failures in
`packages/hive-conductor/backend/tests/test_api.py` at 151bcfe2e), rooted in
`UsernameRegistry.create_users`. The fix indexes the requested username inside
the allocation critical section (`migrate_or_index_one`) before
`_reject_existing_claims`, restoring the fail-closed contract the module
already documents for corrupt claims.
