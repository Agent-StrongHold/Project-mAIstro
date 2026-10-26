---
inventory-delta:
  packages/maistro-core/tests: +8
---

# P2a: reclaim_attempt RECOVERED writer (#2354 / #232)

Makes `runs/lifecycle.py::reclaim_attempt` the first authorized
`CancellationCause.RECOVERED` writer for expired finite canonical leases.
Live / no-lease / infinite-lease / terminal Attempts raise
`InvalidLifecycleTransition`. Physical `result` and `metrics` are preserved.
Generic `transition_attempt` still has no `cancellation_cause` argument.

## Collected node IDs

`packages/maistro-core/tests/runs/test_reclaim_attempt_lease_construction.py`
(+8):

- expired finite lease → CANCELLED + RECOVERED + finished_at + preserved
  result/metrics + reclaim error prefix
- expiry equal to `at` qualifies
- live lease / no lease / infinite lease / terminal refusals
- CREATED + expired lease still reclaims
- `transition_attempt` signature has no `cancellation_cause` kwarg

`test_attempt_cancellation_cause_model.py` replaces the P1a staging assertion
that reclaim left cause unknown with a generic-CANCELLED unknown assertion
(reclaim is now this leaf).

`test_m8a5_differential_reference_model_research.py` mirrors the expiry
refusals in the independent reference model and advances ordinary/M9 reclaim
fixtures past `LEASE_TTL` so differential agreement holds under the tightened
contract.
