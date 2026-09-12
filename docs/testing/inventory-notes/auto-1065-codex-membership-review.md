---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# #1065 review: membership order, finalization scope, plan capacity

Three behavioral cases for the Codex findings on cycle membership fencing:

- `_population_membership` keeps the store's admission order and
  `_evaluation_ids` therefore selects FIFO, not lexicographically
  (`test_evolution_canonical_edge_cases.py`);
- an oversized persisted pair plan is refused on the first battle slot with
  no rating recorded (`test_evolution_canonical_edge_cases.py`);
- `_finalize_cycle` runs over the frozen membership: a genome seeded after
  admission is neither scored nor culled, while the cycle's own child joins
  (`test_evolution_canonical_graph.py`).
