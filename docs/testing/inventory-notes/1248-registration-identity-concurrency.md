---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---

# 1248-registration-identity-concurrency

**+1 `packages/hive-conductor/backend/tests`** — concurrent open registration
requests with the same username are forced to overlap after the availability
check. The real synchronous route must return one success and seven conflicts,
with exactly one stored identity, covering the UUID-keyed check-then-write race.

## Merge reconciliation with develop #1528 (2026-09-23)

Merging develop (8bb344e32) brought #1528's `ModelStore.put_if_unique` /
`unique_fields=("username",)` alongside #1061's canonical
`username_registry.create_users` allocator. The reconciliation keeps
`create_users` as the durable authority (one transaction claims the username
and inserts the user row, valid across processes) and demotes the in-process
`_REGISTRATION_LOCK` to guarding only the advisory availability check and the
invitation spend. Net test count unchanged; two existing tests were re-pointed
at the surviving seams:

- `test_registration_policy.py::TestInvitations::test_durable_claim_loses_after_the_in_memory_check_passes`
  previously stubbed `stores.users.put_if_unique` (a seam the reconciled route
  no longer calls). It now simulates the losing replica by letting a real
  competing allocation win durably before the request's own atomic allocation
  runs, and still asserts the allocation-stage 409, the throttle charge, a
  single surviving canonical identity, and `resolve()` picking the winner
  across casing.
- `test_voice_auth.py::TestTheCredentialResolvesToARealAccount::test_historical_duplicate_account_is_not_selected`
  planted duplicate historical user rows through `stores.users.__setitem__`,
  which the users store's new unique-field constraint correctly refuses for
  NEW writes. Historical duplicates exist at rest and are loaded by
  `ModelStore.initialize` without `__setitem__`, so the fixture now plants
  them at rest the same way; the fail-closed quarantine assertion is unchanged.
