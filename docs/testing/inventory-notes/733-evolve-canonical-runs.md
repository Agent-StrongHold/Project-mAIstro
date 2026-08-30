---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
---

# PR #733 Evolve canonical Run coverage

PR #733 adds `test_evolution_canonical_graph.py` to the Hive/Conductor backend suite. The new module contributes five collected behavioral cases covering canonical Evolve cycle execution evidence, multi-pair tournament ordering, suppression of unexecuted battle NodeRuns, failed-attempt isolation from Evolve score state, and recovery idempotency for an evaluation NodeRun whose domain state was already published before process loss.

The existing `test_evolution_service.py` cases are updated and renamed in place, so they do not change the collected test count.
