---
inventory-delta:
  packages/maistro-core/tests: +3
---

# 1116 — one clock sample for pool-exhaustion accounting

## Change

`packages/maistro-core/src/maistro/credentials/pool.py`: `_exhaustion_counts()`
(now used only by `_raise_exhausted`) classifies every scoped entry against one
`time.monotonic()` sample via a new shared `_classify_entry(entry, now)`
helper; `get_stats()` uses the same helper, so exhaustion errors and stats
report with identical classification semantics instead of two subtly different
clock rules. No behavior change away from clock boundaries.

## Tests added (all in `packages/maistro-core/tests/credentials/test_pool.py`,
class `TestExhaustionClockAccounting`)

1. `test_clock_crossing_cooldown_boundaries_cannot_contradict_the_error` —
   scripted `_AdvancingMonotonicClock` crosses both scoped cooldown expiries
   while the accounting scan runs; asserts the error's counts are exact
   (`cooling_down_keys == 2`, unauthorized keys excluded,
   `soonest_available_at == 100.0`) and true at one of the sampled instants.
   Verified to FAIL against the pre-fix implementation, which reports the
   self-contradictory `cooling_down_keys=1` ("All 2 authorized credentials
   exhausted", only 1 accounted for).
2. `test_exhaustion_error_and_stats_classify_identically_at_one_instant` —
   frozen clock; `PoolExhaustedError` (total, blocked, cooling) equals the
   `get_stats()` partition for the same state.
3. `test_cooldown_expiry_boundary_is_available_not_cooling_everywhere` —
   at `now == cooldown_until` the key is available, not cooling, in both
   stats accounting and actual selection (shared boundary rule
   `cooldown_until > now`).

## Net suite delta

`packages/maistro-core/tests`: +3 (44 pool tests where develop has 41).
