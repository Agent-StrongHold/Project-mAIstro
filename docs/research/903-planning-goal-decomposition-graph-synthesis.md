# M8-D research note — planning, Goal decomposition, and Graph synthesis strategies

Epic: #903. Leaves: #925 (D1), #926 (D2), #927 (D3), #928 (D4), #929 (D5).
Initiative: #879. Milestone: M8.

## Hypothesis (the epic's research question)

Which planning strategy best converts a Goal into reliable canonical Graph/Run work:
direct ReAct-style action, explicit plan-and-execute, synthesized DAG/Graph, hierarchical
decomposition, search over plans, or adaptive replanning? The epic's contract adds the
binding constraint this note operates under: **no research planner may become a parallel
execution authority**, and every candidate Graph is executed through the canonical runtime.

## Canonical seams

The execution model this epic must not disturb is `Goal -> Graph -> Run -> NodeRun ->
Attempt` (SPEC-177): `packages/maistro-core/src/maistro/graph/executor.py` owns execution,
`packages/maistro-core/src/maistro/graph/dag_validator.py` (`validate_dag`) owns Graph
legality, `packages/maistro-core/src/maistro/graph/synth.py` and `templates.py` own
canonical Graph material, and Goals bind into runs through `goal_id`/`goal_revision` on the
run records (`packages/maistro-core/src/maistro/runs/model.py`) with Rubrics as versioned
scored-acceptance objects (`maistro.ontology.rubric`). None of these files is touched by
this leaf; there is no research planner in the runtime path.

## Record

No provider experiment exists: the deterministic CI environment holds no model
credentials, and no representative Goal corpus with real model planners is in-tree.
Absent evidence is recorded rather than simulated (initiative guardrail). What this epic
adds is the reproducible **measurement machinery** each leaf's benchmark demands, as
evidence-only research code:
`packages/maistro-rsi/tests/test_m8d_planning_strategies_research.py` (43 checks,
ruff-clean). It imports no maistro module — enforced mechanically by
`test_module_has_no_maistro_imports` and the `ADVISORY_ONLY` marker — so it cannot become
an authority by accident (M8 guardrails 1–2).

The harness implements, for measurement only:

- a pinned corpus of **12 Goals across 4 decomposition families** (pipeline chain,
  fan-out/fan-in, repair, explore; 3 Goals each, difficulties 1–3) — the Goal's step list
  IS its decomposition, so strategy comparisons stay apples-to-apples;
- a capability registry (21 capabilities with token/tick costs and alternate bindings) and
  a **deterministic discrete-event executor** — the ONE `execute_plan` every strategy,
  repair policy, search winner, and reused motif executes through — with seeded failpoints
  (transient = first-f-calls-fail; permanent = failpoint 99) and per-(goal, capability)
  call counters matching "the provider's first f calls fail";
- the strategy/policy/search/reuse machinery: ReAct stand-in (declares nothing, blind
  in-place retry), plan-and-execute (declares a linear plan, replans the remainder),
  canonical Graph (declares the full DAG), synthesis + validate + bounded repair,
  no-replan / local-swap / full-replan(fresh | reuse) policies, bounded K=4 beam search
  with a rubric verifier, and motif mining/adaptation across task families;
- the metrics the contract lists: success, tool errors, unnecessary (duplicate) calls,
  token cost, p50/p95 makespan in ticks (never wall-clock), plan stability, declared-node
  inspectability, and artifact provenance.

All numbers below are **mechanism findings about policy shapes on a pinned corpus**. They
are NOT evidence about real models and must never be quoted as such.

### D1 — strategy benchmark (#925)

Clean world (12 Goals × 3 strategies):

| strategy | success | mean calls | mean tokens | p50 ticks | p95 ticks | declared |
|---|---|---|---|---|---|---|
| react | 1.00 | 5.167 | 1816.7 | 9 | 14 | 0 |
| plan_execute | 1.00 | 4.083 | 1491.7 | 9 | 14 | 4.083 |
| graph | 1.00 | 4.083 | 1491.7 | **8** | **10** | 4.083 |

Findings pinned by tests: ReAct pays extra calls and tokens on *every* Goal (recap
re-derivation) and declares nothing (its trace is the plan after the fact); Graph wins
latency **exactly where parallelism exists** (fan-out families) and merely ties chains
otherwise; under transient faults (second step fails twice) ReAct's blind budget collapses
to 0.00 success while plan-and-execute and Graph recover identically (both 1.00, same
cost) — the declared plan, not the interaction style, is what survives faults.

### D2 — synthesis, validation, repair (#926)

Clean synthesis is legal on the first pass for all 12 Goals (0 repair iterations). The
validator distinguishes five defect classes with root-cause-clean diagnosis
(`test_each_injected_defect_yields_its_named_code`): cycle, missing_node, unknown_kind,
no_entry, and — by design decision — no derivative `unreachable`: a cycle suppresses the
reachability sweep (everything behind a cycle is unreachable only *because* of the cycle)
and dead dependencies are named once as `missing_node` (reachability runs over resolved
edges). Single defects repair within 1–2 bounded rounds; a compound defect (cycle + orphan)
takes strictly more rounds than either alone (`test_repair_rounds_grow_with_defect_count`).
Constraint-aware binding swaps to available alternates *before* validation
(`fix`→`patch` under a permanent fault, 0 repair rounds), and every accepted candidate
executes on the one shared executor.

### D3 — replanning policies (#927)

Permanent fault on `fix` (affects 5 of 12 Goals):

| policy | recovered | calls | duplicate calls | tokens | ticks | swaps | replans |
|---|---|---|---|---|---|---|---|
| none (attempt budget only) | 7/12 | 54 | 0 | 21300 | 124 | 0 | 0 |
| local swap | **12/12** | 64 | 0 | 25650 | 150 | 5 | 0 |
| full replan, reuse | **12/12** | 64 | 0 | 25650 | 150 | 0 | 5 |
| full replan, discard | **12/12** | 74 | 10 | 29150 | 171 | 0 | 5 |

Findings pinned by tests: local swap and reuse-replan tie exactly on cost here and both
dominate discard-replan (whose 10 duplicates are precisely the re-done work); provenance
is correct in both styles (local repair keeps the original producing node identity;
discard-replan re-records artifacts under the new generation's identity); policies are
inert without surprises (identical clean-world traces); and when both a capability and its
alternate are dead, every policy terminates bounded — swaps ≤ 4, replans ≤ 2, records ≤ 24
— no repair livelock (`test_oscillation_is_bounded_when_both_bindings_are_dead`).

### D4 — bounded search over candidate plans (#928)

Difficult slice (10 Goals, difficulty ≥ 2), permanent fault on `fix`, K=4 candidates:

- clean world: search is pure overhead — the beam picks the minimal candidate (ties break
  earliest) and executes identically to one-shot planning, 4 planning calls spent for
  nothing (`test_search_is_useless_in_a_clean_world`).
- faulted world: beam 10/10 vs one-shot 5/10 at 40 planning calls
  (`test_beam_uplift_under_permanent_fault`) — but the uplift is exactly conditional on
  verifier accuracy: one mis-ranked candidate (index 2 scored 0.0) closes it to 5/10
  (`test_verifier_error_closes_the_uplift_exactly`). Search pays only when the world
  invalidates the default plan AND the verifier can see it.
- diversity finding: the naive K=4 generator explores only **three** distinct structures —
  its v1 "canonical DAG" control collapses onto v0's shape (same bindings, same dataflow;
  `test_candidates_are_pairwise_structurally_distinct`), i.e. a quarter of the planning
  budget buys a duplicate. Real search needs diversity-aware candidate generation.

### D5 — motif induction and reuse (#929)

Mining successful runs yields one valid motif per family; matched-family reuse is
structure-preserving (edit distance 0 vs from-scratch synthesis on held-out `rep_3`/`exp_3`,
identical token/makespan) — so on this corpus reuse saves *nothing* over constraint-aware
synthesis. The measured risk is transfer loss: a pipeline motif adapted to a fan-out Goal
re-wires the joins into a chain (edit distance 6, makespan 14 vs 8 —
`test_cross_family_transfer_loses_parallel_structure`). Stale motifs (binding a retired
capability) are caught by validation as `unknown_kind`, fail cleanly if executed, and
repair converges to the surviving alternate (`test_stale_motif_is_caught_then_repaired_to_
an_alternate_binding`); constraint-aware synthesis binds the alternate on the first pass.

## Benchmark procedure (what a real experiment must do)

1. Export a representative Goal corpus from real runs (Session/Outcome traces, ADR-017),
   sliced by decomposition family and difficulty, with scored acceptance (Rubrics).
2. For each Goal class, run matched-budget planners: a real ReAct loop, an explicit
   plan-and-execute LLM planner, and Graph synthesis from the Goal + capability registry —
   all emitting candidate Graphs validated by `validate_dag` and executed only through the
   canonical executor.
3. Measure the contract's list per strategy: task success, recovery under injected
   provider/tool failures, p50/p95 wall-clock latency, token and tool-call cost, plan
   stability (re-plans per Goal), unnecessary work (duplicate calls), and inspectability
   (declared-before-execution nodes, human review minutes).
4. For D4/D5: repeat under verifier-error injection and held-out Goal splits; report the
   dominance frontier (success vs latency vs planning cost) and evidence of benchmark
   overfitting (corpus-swap sensitivity).
5. Update the dispositions below with the numbers; route any adoption to the canonical
   Goal/Graph/orchestrator owner (SPEC-177 machinery), never through M8.

## Trust boundary

The harness is test-only code that imports no maistro module: it cannot reach a Goal
store, Run authority, template store, or authorization surface (epic contract, enforced
by `test_module_has_no_maistro_imports`). All planners emit candidate Graph artifacts that
are validated for legality and executed by the one shared `execute_plan`; there is no
second runtime. No product code, flag, or model call is added. Any GRADUATE result must be
re-implemented by the canonical owners (`maistro.graph`), not transplanted.

## Dispositions

Per-leaf terminal dispositions (M8 contract: exactly one each):

- **D1 (#925) — WATCH.** The mechanism gradient is measured (declared plans survive
  faults; ReAct pays carry-cost; Graph wins only where parallelism exists), but every
  number is a policy-shape result on a pinned corpus, not model evidence. Escalate to
  INCUBATE when a real-model benchmark on representative Goals reproduces the gradient at
  matched budgets; REJECT if the gradient was a corpus artifact.
- **D2 (#926) — WATCH.** Synthesis→validate→repair is measured as a bounded, converging
  loop (0 clean-start repairs; 1–2 rounds per single defect), and the shipped
  `maistro.graph.dag_validator` already covers the check families. Nothing justifies a
  planner writing Graphs today. Escalate to INCUBATE when an LLM synthesizer's repair
  statistics on real Goals match the loop's assumptions (few, class-distinct findings).
- **D3 (#927) — WATCH.** Local repair ≈ reuse-replan > discard-replan is the headline,
  with bounded oscillation proven; but the policies here are rules, not model decisions.
  Escalate to INCUBATE with a real replanning agent that beats attempt-budget retry on
  recovery *and* duplicate-work accounting on the canonical executor.
- **D4 (#928) — WATCH.** Search uplift is real but exactly conditional on verifier
  accuracy and fault presence, and the naive generator spends 25% of its budget on
  duplicate candidates. Escalate to INCUBATE only with a verifier whose measured error
  rate on real plans is low enough to keep most of the 2× uplift, and diversity-aware
  candidate generation.
- **D5 (#929) — WATCH.** On this corpus, structure-preserving reuse ties synthesis at
  zero saving, while cross-family transfer measurably destroys parallelism — evidence
  that reuse needs family-aware retrieval to be net-positive. Escalate to INCUBATE when
  motif retrieval on real runs beats from-scratch planning latency at equal success.

Nothing here graduates: no real-model experiment, no representative workload, and the
canonical owners own every production change. The harness's pinned pins make each future
provider experiment a drop-in comparison against a reproducible baseline.

## Executed probe record (this head)

`uv run pytest packages/maistro-rsi/tests/test_m8d_planning_strategies_research.py -q`
→ 43 passed; `uv run ruff check` and `uv run ruff format --check` clean on the module.
