---
inventory-delta:
  packages/maistro-rsi/tests: +43
---
# 903-m8d-planning-harness

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Evidence-only research harness for the M8-D epic (#903, leaves #925–#929):
which planning strategy best converts a Goal into reliable canonical
Graph/Run work. No product code changed — the module imports no maistro
module (research evidence, never an authority, per the epic contract and M8
guardrails 1–2), and the canonical `Goal -> Graph -> Run -> NodeRun ->
Attempt` machinery (SPEC-177: `maistro.graph.executor`,
`maistro.graph.dag_validator`, run records binding `goal_id`/`goal_revision`)
is untouched. The experiment record and per-leaf dispositions live in
[`docs/research/903-planning-goal-decomposition-graph-synthesis.md`](../../research/903-planning-goal-decomposition-graph-synthesis.md).

`test_m8d_planning_strategies_research.py` (+43 node IDs):

- `test_advisory_only_contract` + `TestModuleBoundary` (1): the ADVISORY_ONLY
  marker cannot rot, and the module imports nothing from `maistro` — the
  no-parallel-execution-authority rule enforced mechanically.
- `TestMetricIdentities` (5): hand-checked percentile/success/unnecessary/
  edit-distance/rubric math plus synthesis determinism — the instruments
  before the measurement.
- `TestCorpusSanity` (5): corpus shape and binding integrity, the clean-world
  solvable floor, a hand-checkable fan-out critical path, byte-for-byte
  benchmark repeatability, and failpoint-arming shape (transient ≠
  unavailability).
- `TestD1StrategyBenchmark` (7): the strategy gradient on 12 Goals × 3
  strategies — all succeed clean; ReAct pays calls/tokens everywhere and
  declares nothing; declared plans survive transient faults that ReAct's
  blind budget does not; Graph wins makespan exactly where parallelism
  exists; pinned p95/latency summary tables.
- `TestD2SynthesisValidation` (8): clean synthesis is legal first-pass
  everywhere (0 repair rounds); each injected defect yields exactly its named
  finding code; dead deps never cascade into `unreachable` (one defect, one
  finding — that is what makes repair-round counts interpretable); compound
  defects take strictly more rounds than either alone; accepted candidates
  execute on the one shared executor; constraint-aware binding swaps to
  available alternates before validation; the validator catches real cycles
  while passing legal chains.
- `TestD3ReplanningPolicies` (6): the recovery/cost gradient under a permanent
  fault (none 7/12 → local swap 12/12 = reuse-replan 12/12 < discard-replan
  cost), exact mechanism counters pinning the policy shapes, provenance
  correctness of preserved vs re-recorded work, bounded termination when both
  a capability and its alternate are dead (no repair livelock), and policy
  inertness without surprises.
- `TestD4BoundedSearch` (6): search is pure overhead in a clean world; beam
  10/10 vs one-shot 5/10 under the fault at a pinned 40 planning calls; one
  verifier error closes the uplift exactly (5/10); the naive K=4 generator
  explores only three distinct structures (the v1 control collapses onto v0 —
  measured, not assumed); the underprovisioned candidate never wins; the
  robust variant wins exactly where the fault bites.
- `TestD5MotifReuse` (5): one valid motif per family; matched-family reuse is
  structure-preserving and ties from-scratch synthesis on held-out Goals;
  cross-family transfer measurably destroys parallel structure (edit distance
  6, makespan 14 vs 8); stale motifs are caught, fail cleanly if executed,
  and repair converges to the surviving alternate.

Every pinned finding was checked against the mechanism that names it: the
numbered D3 tables (54/64/74 calls, 21300/25650/29150 tokens) and the D4
uplift triple (10, 5, 40) fail if the executor's accounting, the failpoint
semantics, or a policy's swap/replan behavior changes — the pins are the
regression net for the deterministic executor the five leaves share. Latency
is measured in deterministic ticks, never wall-clock, and no number here is
evidence about real models; the dispositions are WATCH pending real-model
experiments on the canonical seam.
