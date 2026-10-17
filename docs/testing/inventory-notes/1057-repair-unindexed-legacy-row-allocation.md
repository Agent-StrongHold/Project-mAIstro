---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---

# #1057 repair — allocation sees unindexed legacy identity rows

The lane's verifier battery failed `test_api.py::test_register_duplicate_username`
(assert 200 == 409) at head `1b5df5895`. Root cause, found by execution: the
conftest development seed (like any user row written without going through the
registry — a direct import, a restored backup) holds no `username_claims`
record, and `UsernameRegistry.create_users` (#1061) rejected duplicates from
the claim index alone. The read paths (`resolve` / `is_claimed`) lazily index
such legacy rows via `migrate_or_index_one`, so login reported the account as
existing while registration considered the same name free — a read/write
identity inconsistency that silently minted a second account behind one
username. `username_registry.py` and `conftest.py` are byte-identical to
`origin/develop` at this head, so the failure is pre-existing on develop, not
introduced by the #1057 delegation work; it surfaced here because the salvage
merge `25259b5d7` brought develop's #1453/#1061 allocator in after the last
recorded hive validation round.

Repair (production, `services/username_registry.py`): `create_users` now runs
`migrate_or_index_one` for every name in the batch before rejecting claims, so
the write path sees the same identities the read path does. An unindexed legacy
row blocks its name with `UsernameTakenError` (route: 409); an unindexed
historical duplicate is quarantined and also blocks. No test was modified.

**+2 `packages/hive-conductor/backend/tests/test_username_registry.py`**:

- `test_create_users_blocks_an_unindexed_legacy_row` — a claim-less legacy row
  refuses allocation, the refusal indexes the legacy identity (active claim
  naming the legacy id, `resolve` finds it), and no new account row is written.
- `test_create_users_fails_closed_on_unindexed_legacy_duplicates` — two legacy
  rows with the same normalized name quarantine the name and refuse allocation.

Validation on this head: full hive-conductor backend suite 2808 passed /
6 skipped; verifier battery files (`test_api`, `test_engine_service`,
`test_mission_controls`, `test_production_workspace_scope`,
`test_workspace_scoped_submission`) 112 passed; auth-adjacent suites
(`test_registration_policy`, `test_auth_throttle_routes`,
`test_auth_password_storage`, `test_credentials_api`, `test_auth_routes`,
`test_setup_guard`, `test_voice_auth`) 136 passed.
