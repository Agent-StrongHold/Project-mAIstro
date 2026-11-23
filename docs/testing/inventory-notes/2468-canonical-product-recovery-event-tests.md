---
inventory-delta:
  packages/hive-conductor/backend/tests: +10
---

# #2468 canonical recovery event authority regression oracles

This branch adds `packages/hive-conductor/backend/tests/test_recovery_event_authority.py`
for production recovery EventEnvelope persistence across scheduled registered-DAG
and Evolve recovery. It adds **10 collected pytest node IDs**:

- 3 selector/fail-closed cases for configured Container, standalone fallback, and missing RunStore
- 3 schedule wrapper cases (queued recovery, elapsed wake, and external-result polling handoff)
- 2 Evolve wrapper cases (queued recovery and elapsed wake)
- 1 duplicate-delivery test proving the canonical event identity deduplicates legacy projection
- 1 canonical append failure test proving no legacy event is emitted before persistence

On the exact PR SHA `3eaf2e7ff93b6e21d3c86cce360009c7dc242839`,
CI suite inventory run `45103349580`, job `137458985513` measured
`packages/hive-conductor/backend/tests: expected 4407, collected 4417`.
The delta is +10, attributable to this new file; no test removals or
parameterization changes elsewhere in this branch. The CI inventory remains
an independent gate on the revised commit.
