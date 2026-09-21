---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---

# 1126-invite-single-use

**+3 `packages/hive-conductor/backend/tests`** — the concurrency coverage
#1126 demanded, in two files:

- `test_model_store_svc.py`
  (`test_json_store_put_if_absent_is_atomic_under_in_memory_contention`):
  eight threads released through a barrier claim one key of a persisted-less
  `JsonStore`; the value carries a payload whose `str()` sleeps, so every
  racer parks inside `put_if_absent`'s check-to-write window (`json.dumps`
  with `default=str`) with the GIL released. Exactly one insert may win, and
  the surviving record must be the winner's, not the last writer's.
- `test_registration_policy.py`
  (`test_concurrent_redeem_invitation_spends_the_token_exactly_once`,
  `test_concurrent_register_race_through_the_open_window_mints_one_account`):
  the same window held open via a patched `json.dumps` that parks only the
  redemption marker, then eight `ThreadPoolExecutor` threads either all call
  `redeem_invitation` with one token (one True, seven False, the stored
  marker naming the winner) or all POST `/v1/auth/register` with it through
  the real synchronous route (one 200, seven 403, one account). The route
  case swaps in a fresh register throttle so failures earlier suites charged
  to the TestClient bucket cannot turn the race's losers into 429s.

Both new registration cases fail against the pre-fix unlocked check-then-set
(all eight redemptions succeed; multiple 200s) — verified by mutating
`JsonStore.put_if_absent` back to the unlocked shape and running them.
