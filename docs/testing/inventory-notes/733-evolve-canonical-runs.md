---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---

# PR #733 Evolve canonical Run coverage

PR #733 adds `test_evolution_canonical_graph.py` and `test_evolution_persisted_pair_plan.py` to the Hive/Conductor backend suite. Together they contribute six collected behavioral cases covering canonical Evolve cycle execution evidence, multi-pair tournament ordering, suppression of unexecuted battle NodeRuns, failed-attempt isolation from Evolve score state, evaluation recovery idempotency after process loss, and reconstruction of tournament pair/cursor execution state from persisted NodeRun data.

The existing `test_evolution_service.py` cases are updated and renamed in place, so they do not change the collected test count.
