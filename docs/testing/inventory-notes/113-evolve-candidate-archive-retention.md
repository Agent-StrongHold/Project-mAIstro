---
inventory-delta:
  packages/maistro-evolve/tests: +35
---
# 113 — evolve candidate archive + historical-retention evaluation

M4-A6 ("Preserve candidate lineage/archive and enforce historical-retention
evaluation") adds one test module and modifies one existing test:

- `packages/maistro-evolve/tests/test_archive.py` — 35 tests covering the
  four acceptance seams: provenance stamping on every candidate producer
  (mutate operators, crossover, challengers, seeds), the immutable
  `CandidateArchive` (snapshots, retirement survival, non-champion branching,
  SQLite persistence, cross-retirement lineage resolution), the declared
  `RetentionPolicy` (replay vs deterministic sample), and the promotion gate
  (regression blocks, unreplayed-scenario blocks, governance override only
  when the objective actually changes, incomplete-provenance fail-closed), plus
  two `EvolutionCycle` integration tests proving the production cycle archives
  retired candidates and created children automatically.
- `packages/maistro-evolve/tests/test_crossover.py` — `test_crossover_and_mutate_returns_a_mutated_child`
  asserted the OLD lossy behavior in prose ("the crossover's parent_b lineage
  is dropped"); M4-A6 makes two-parent records mandatory, so the assertion now
  requires both parents plus the composite-operator record. Same single test
  node — modified, not added or removed.
