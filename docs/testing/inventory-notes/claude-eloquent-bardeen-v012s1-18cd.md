---
inventory-delta:
  packages/maistro-canvas/tests: +3
---
# claude-eloquent-bardeen-v012s1-18cd

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

#1550 adds three regression tests for the Canvas retry-ceiling bypass through
admission recovery. Nothing was removed or renamed:

- `test_canonical_execution.py::test_recovery_leaves_an_exhausted_expired_lease_for_the_reaper`
- `test_canonical_execution.py::test_recovery_marks_an_exhausted_unleased_receipt_reapable`
- `test_canonical_executor_integration.py::test_worker_deaths_before_execution_cannot_bypass_the_retry_budget`
