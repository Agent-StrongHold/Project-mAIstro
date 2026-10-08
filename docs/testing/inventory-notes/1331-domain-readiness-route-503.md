---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# 1331-domain-readiness-route-503

One node ID added to `packages/hive-conductor/backend/tests` for issue #1331
(include domain readiness in Evolve execution availability).

`test_cycle_route_with_healthy_owner_but_missing_domain_state_is_503_unavailable`
drives `trigger_cycle` with a real `_EvolutionService` in the issue's exact
failure scenario — a healthy `canonical_execution_owner()` with a population
and tournament that `initialize_domain_state()` never produced — and asserts
the availability-shaped 503 (`evolution_unavailable`, `availability:
"unavailable"`) rather than the generic 500 a bare `RuntimeError` would
receive from the route's fallback handler.

Why it earns its count: the pre-existing coverage held the scenario only as a
disjunction. `test_run_one_cycle_rejects_half_initialized_domain_state`
asserts the service-level raise but matches `RuntimeError`, the *parent*
class — the pre-fix behavior (a bare `RuntimeError("Evolution population is
not initialized")` mapping to a generic 500) passes it unchanged. The
route-mapping tests either stub the whole service
(`test_unavailable_cycle_is_distinguishable_from_execution_failure`) or
exercise the degraded-engine path (`test_stub_cycle_route_returns_explicit_
availability_error`), so no single test pinned the composition. The new test
keeps that regression visible, and also re-checks the `status()` projection
(`running`/`execution_available` false) that gates the cadence task and the
frontend Run Cycle button in the same state.
