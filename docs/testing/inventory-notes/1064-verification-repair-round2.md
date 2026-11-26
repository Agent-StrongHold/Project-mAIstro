---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---
# 1064-verification-repair-round2

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Six collected items join `packages/hive-conductor/backend/tests` (+3 in
`test_evolution_restart_replay.py`, +3 in `test_evolve_domain_store.py`, one
of them PG-gated). They are the #1064 repair's evidence, not padding:

- three `_EvolutionService.refresh_committed_finalize_evidence` outcomes —
  the durable committed-finalize evidence the shipped recovery resolver
  consults synchronously was never executed on any coverage-measured path
  (hosted diff gate: lines 380-388, 391, 394-395 uncovered at b0b32ec);
- one evaluation-journal replay leg for a receipt whose genome the restored
  snapshot no longer holds (hosted-uncovered line 607);
- the evaluation-publication exactly-once fence across memory/sqlite stores
  and the three PG lookup miss outcomes (hosted-partial branch arcs at 258,
  374, 416, 500).

`packages/maistro-evolve/tests` is unchanged (1017). All 4546 identities are
unique cross-suite; duplicate evidence remains 0.
