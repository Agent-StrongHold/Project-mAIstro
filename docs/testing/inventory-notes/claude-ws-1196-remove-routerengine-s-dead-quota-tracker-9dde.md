---
inventory-delta:
  packages/maistro-core/tests: +2
---
# claude-ws-1196-remove-routerengine-s-dead-quota-tracker-9dde

Added `packages/maistro-core/tests/fitness/test_quota_single_authority.py`
with two new tests: `test_router_has_no_quota_tracker_dependency` (an AST
scan asserting `maistro.router` carries no `QuotaTracker` import, reference,
or constructor parameter — the #1196 stop condition that a router-side quota
check cannot be revived) and `test_fitness_detector_catches_a_planted_quota_tracker`
(proves the detector itself fails on a planted regression, per the same
"a seam only tests construct doesn't count" bar the import-boundary fitness
tests already meet). No tests were removed; the existing
`packages/maistro-core/tests/router/test_selector.py` suite lost its now-dead
`_StubQuotaTracker` helper but kept the same 9 test functions, unrelated to
this +2 delta.
