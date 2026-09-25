---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-core/tests: +0
---

# M2 #1061 repair round: throttle-ordering assertion updated for the atomic allocator

No tests were added, removed, renamed, or moved; both counts are unchanged.
One existing test in `tests/test_auth_throttle_routes.py` was rewritten in
place because the mechanism it statically pinned no longer exists.

## What changed and why

`test_it_is_throttled_before_the_availability_check` asserted, on the register
route's source, that `_enforce(` appears before `_username_taken(`. That
property (a definitive 409 "username is taken" must sit behind the
registration throttle budget, so an anonymous caller cannot walk the user list
at zero cost) is unchanged, but #1061 removed the in-route `_username_taken`
scan: the availability authority is now the atomic claim transaction in
`username_registry.create_users`, whose `UsernameTakenError` branch answers
the 409 and charges `_REGISTER_THROTTLE.record_failure`.

The assertion now requires `_enforce(` before `username_registry.create_users(`
plus the presence of `_REGISTER_THROTTLE.record_failure` in the register
function — the same ordering property expressed against the structure the
route actually ships. Without this update the test raises `ValueError`
(substring not found) on the current source, which the previous #1061 commit
did not run.
