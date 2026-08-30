---
inventory-delta:
  packages/hive-conductor/backend/tests: +11
---

# PR #733 Evolve canonical Run coverage

PR #733 adds `test_evolution_canonical_graph.py`, `test_evolution_persisted_pair_plan.py`, and `test_evolution_canonical_edge_cases.py` to the Hive/Conductor backend suite and adds one behavioral case to `test_evolution_service.py`. Together they contribute eleven collected cases covering canonical Evolve cycle execution evidence, multi-pair tournament ordering, suppression of unexecuted battle NodeRuns, failed-attempt isolation from Evolve score state, evaluation recovery idempotency after process loss, reconstruction and validation of persisted tournament pair/cursor execution state, actor-to-Run provenance and cycle `run_id` projection, duplicate/malformed evaluation provenance handling, half-initialized domain-state rejection, and the service contract that a failed canonical Run is surfaced rather than counted as a completed evolution cycle.
