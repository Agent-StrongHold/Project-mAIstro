---
inventory-delta:
  packages/maistro-core/tests: +26
---
# 1205-quota-compat-helpers

#1205 retires/validates the unused quota compatibility helpers without letting
a second quota interpretation survive anywhere.

What moved and why:

- `tests/quota/test_verifiers_mistral.py` was rewritten around the retired
  guess-list. The old suite pinned first-match-wins over four plausible
  remaining-quota field names (4 parametrized accept-cases, a first-match-wins
  case, and a none-matched case). The verifier now requires an explicit
  `MistralRateLimitSchema(version, remaining_field)` contract and fails
  loudly off-contract, so the suite now pins: schema-contract is required to
  construct, only the declared field parses, a lookalike field is never
  adopted, and strict type (JSON number, bool rejected) and range (finite,
  non-negative) validation — 16 node IDs replacing 8 (+8).
- `tests/quota/test_tracker.py` flips the silent fallbacks into explicit
  failures: `cycle_key`/`daily_budget`/`InMemoryQuotaTracker.record_usage`
  must raise `UnknownBillingCycleError` for unknown cycles instead of
  bucketing them as monthly (4+2+1 replacing 2), and a new cross-check pins
  that the retained `billing.daily_budget` alias and the router's scarcity
  scorer agree everywhere (2 cycles × 3 token scales = 6) so the alias stays
  a pure re-export of the one formula (+11 net).
- `tests/persistence/test_sqlite_quota.py` and `tests/persistence/test_pg_quota.py`
  drop their pins on the accidental leniency (record with `'  Monthly  '` /
  `'MONTHLY'`, read with `'monthly'` — same bucket only because everything
  non-"daily" silently meant monthly) and pin the exact vocabulary instead:
  unnormalized spellings now raise `UnknownBillingCycleError` at each
  persistence seam (+3 net across the two files).
- `tests/router/test_scarcity.py` pins the same vocabulary at the cost seam:
  unknown cycles raise from `compute_effective_cost` (3) and the
  daily/monthly magnitudes are unchanged by the delegation (+5 total minus 0
  removed).

`packages/maistro-rsi/tests/test_quota_burn.py` changed a fixture constant
only (`CYCLE = "2026-06"` → `"monthly"`): the old fixture fed a precomputed
bucket key into the `billing_cycle` parameter and relied on the silent
treat-as-monthly fallback #1205 removes. Node-ID counts there are unchanged.

The tracker/recorder/recording half of quota is production authority
(#718/#1196); these tests cover the compatibility helpers feeding it, not a
second authority.

## CI-repair amendment (merge-queue evaluation at 9d391160)

CI failed three tests that still fed precomputed bucket keys into the
`billing_cycle` parameter — the exact silent-fallback shape this issue
retires (`record_usage("openai", "2026-06", …)` relied on non-`"daily"`
silently meaning monthly, and since the key is derived from *now*, it never
actually pinned June). No node IDs added or removed; all three were in-body
fixes to the validated vocabulary (`"monthly"`):

- `packages/maistro-core/tests/test_container_sqlite_backend.py::
  test_sqlite_backend_quota_tracker_write_then_read_back`
- `tests/migrations/test_pg_store_wiring.py::TestStoresRunAgainstTheMigrated
  Schema::test_quota_accumulates_across_calls`
- `tests/migrations/test_quota_and_session_stores.py::
  TestQuotaTrackerRunsAgainstTheMigration::test_usage_accumulates_rather_than_raising`

`inventory-delta` above is unchanged: no suite gained or lost a node.
