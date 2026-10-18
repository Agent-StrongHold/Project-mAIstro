---
inventory-delta:
  packages/maistro-core/tests: +45
---
# 984-explore-waves-thesis-provenance

**+45 in one suite** — explore waves (M7-A8) became contract-checked provenance
on the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` spine: one design
Run fans an explore node out to `width` thesis NodeRuns, each thesis durable on
its own NodeRun, scored by eval-on-Run against the wave's Rubric revision, with
losers queryable after a winner is named and a later wave on the *same* Run
forbidden from repeating a rejected thesis.

`packages/maistro-core/tests` (+45, `tests/runs/test_exploration_waves.py`;
12 behaviors on the three-backend `spine` fixture, one of them parametrized over
the three exploration policies, plus 3 source-level contracts):

- Wave 1 fan-out (+2) — a pack Graph emits wave 1 as exactly `width` (>= 2)
  child NodeRuns of ONE Run (no new Run identity per thesis), and each thesis
  NodeRun durably records thesis text, wave index, slot, policy, width, parent
  explore node, Goal revision and Rubric revision under
  `NodeRun.provenance["explore_wave"]`, read back through the store's payload.
- Eval-on-Run scoring (+1) — every thesis of a wave is scored against the same
  Rubric revision the wave was emitted under (a mismatch is
  `RubricRevisionMismatchError`); naming a winner marks the wave-mates losers
  and all three remain queryable off `list_node_runs`, with
  `rejected_thesis_texts` returning exactly the two losers.
- Wave 2 on the same Run (+1) — the rejected-thesis list is the next wave's
  forbidden input: repeating a rejected thesis (formatting aside) is
  `DuplicateThesisError` and persists nothing, an accepted wave 2 lands as
  later ordinals on the same `run_id`, and historical wave-1 provenance stays
  byte-for-byte immutable.
- Policies (+3 params + 2) — `wide-then-converge` / `tight` / `tournament` are
  one `ExplorationPolicy` enum (not three products), pack-declared on the Run
  via `Run.provenance["exploration"]` and readable per policy; tightening
  width per Run records a new plan without changing `goal_revision`, and the
  original Run keeps its own plan.
- Width/divergence guards (+4) — wave width must equal the thesis count
  (`ThesisWidthMismatchError`), intra-wave duplicates are refused without
  persisting, the parent explore node must exist in the Run Graph snapshot,
  a wave's winner can be named only once (re-naming another thesis is
  `WaveWinnerAlreadyNamedError`; re-naming the winner is idempotent), and a
  settled thesis can be neither re-scored nor have its identity rewritten
  (`ThesisSettledError` via `merge_thesis_record`).
- Source-level contracts (+3) — a static scan fails if the design loop
  (`maistro.runs`, `maistro.graph`, `maistro_design`) imports
  `maistro.orchestrator.waves` (the ADR-052/SPEC-255 island stays unreachable
  as the design-loop owner), fails if `DesignProject`/`CreativeBrief` grow
  candidate-storage fields (`variants`/`candidates`/`theses`/`waves` — the
  forbidden client-side system of record), and proves wave history is
  reconstructible from the Run store alone with no design-side state.
