# M8-D4 research note — bounded beam/tree/MCTS-style search over candidate plans

Leaf: #928. Epic: #903 (M8-D). Initiative: #879. Program: #878.

## Hypothesis

Generating and evaluating multiple candidate plans before execution improves
difficult-Goal success enough to justify the added planning model calls compared with
one-shot planning.

## Canonical seams

Candidate plans compile to **canonical Graph candidates**:
`maistro.graph.types.GraphConfig` (pydantic-validated), whose Hive DAGFile projection is
checked by the production validator `maistro.graph.dag_validator.validate_dag` —
registry-known node kinds, entry reachability, acyclicity, and per-edge schema
compatibility (`packages/maistro-core/src/maistro/graph/dag_validator.py`). This is the
same gate the DAG save/run paths apply as defense in depth, and the same shape of
artifact `agent.synth_dag` dispatches as a child Run after `evaluate_dag_shape`
(`packages/maistro-core/src/maistro/graph/nodes/agent_synth_dag.py`). NodeRun-level
candidate scoring already exists *inside* execution (SPEC-272 beam contracts); this leaf
is the different layer — search over **whole plans before** any Run exists.

**Search does not create a second runtime.** The prototype is a pure planner: it
dispatches nothing, records nothing, spawns no Run, registers no node, and needs no
store. A source-scan guard in the harness pins that it imports no execution or
persistence authority (`maistro.runs`, `maistro.graph.executor`,
`maistro.graph.durable_runs`, `maistro.graph.harness*`, `maistro_server`). A selected
candidate is a plan artifact (ordered kinds + compiled `GraphConfig` + score); it would
reach execution only through the existing canonical path — durable Run dispatch of the
compiled graph. Per the epic contract, production adoption routes to the existing
Goal/Graph/orchestrator owner.

## Record

No provider credentials exist in CI, so this note does not report a model experiment
(M8 guardrail 3: absent evidence is recorded, not simulated). What lands is the
reproducible measurement machinery the benchmark procedure needs, as a test-suite-only
artifact — `packages/maistro-rsi/tests/test_m8d4_plan_search_research.py` (+33 node IDs,
delta in `docs/testing/inventory-notes/928-m8d4-plan-search-harness.md`) — validated on
deterministic, hand-checked fixtures:

- **Difficult-Goal subset**: 10 Goals whose planner option pools mix required node
  kinds (all real registered kinds) with traps: a hallucinated `auto.test` kind the
  production registry rejects, filler kinds that crowd out required capabilities under
  the width cap, and the entry-only `human.ask_question` constraint (a mid-chain
  clarify fails real schema compatibility because the compiler cannot fabricate the
  question text). The planner is a seeded deterministic proposer billing tokens/latency
  per call; execution outcome is a fixture oracle (executable + required capability
  coverage + width cap), strictly separated from the independent rubric scorer.
- **Search variants**: bounded beam search over plan prefixes (width × branching ×
  depth, hard call and scored-candidate caps) and a bounded MCTS-style variant (UCB1
  selection, greedy rollouts, iteration cap, shared call budget). One-shot planning is
  the width-1/branching-1 degenerate: the planner never sees an alternative.

Fixture results at this head (machinery validation, **not** model evidence):

| Measure | One-shot | Beam (w=2, b=5) |
|---|---|---|
| Goal success (10-goal subset) | 0.20 | **1.00** (uplift +0.80) |
| Planning calls / tokens / latency | 4 / 640 / 168 ms | 7 / 2240 / 630 ms |

- **Planning compute/tokens**: search pays 3.5× the tokens and 3.75× the sequential
  latency of one-shot on this subset. The bill is invariant to scorer quality — a blind
  scorer pays it identically and lands at uplift **−0.20**: uplift is a property of the
  verifier's discrimination, not of searching alone.
- **Depth/branching sensitivity**: success is non-decreasing in width and saturates
  early — width 2 → 3 buys +0.00 success for +43% tokens (2240 → 3200) on this subset;
  cost strictly increases in branching.
- **Diversity**: a degenerate proposer (one option everywhere) collapses the beam to a
  single distinct plan with zero gain; the normal proposer's beam holds distinct,
  executable candidates (mean-pairwise-Jaccard separates the two regimes).
- **Verifier/ranker error**: the calibrated ranker takes zero top-1 regret on the
  subset; an adversarial ranker (rewards `clarify`, ignores required coverage) incurs
  regret on 2 of 10 goals and drops success to 0.50; scorer↔oracle Kendall tau tracks
  scorer quality.
- **Latency**: proposal calls are strictly sequential in the accounting (no parallelism
  credit); 630 ms vs 168 ms mean per Goal at the fixture rates.
- **Benchmark overfitting**: honest hyperparameter tuning on an interleaved tuning
  split transfers to the held-out split (tuning uplift 0.6, eval 0.8, gap 0.2), while
  per-goal tuning on the evaluation split itself inflates the measured uplift to 1.0 —
  the exact optimism the study protocol must design out.
- **MCTS-style variant**: non-negative uplift (+0.10 at 12 iterations) under the same
  scoring discipline; UCB1 demonstrably spreads visits beyond the greedy arm.

Key mechanisms are mutation-checked: bypassing the validator flips the compile-gate
pins; disabling score-ranked pruning drops beam success to 0.0; removing the call
budget's exhaustion check runs 7 calls against a cap of 2.

## Boundary the fixtures expose

Search pays only when two conditions hold simultaneously: the proposer's distribution
must be *repairable* (one-shot failures are recoverable from alternatives — the trap
density here), and the verifier must *discriminate* (blind ranker: strictly negative
net value at full cost; adversarial ranker: measurably worse than one-shot-informed
selection). A production design inherits both as hard prerequisites, plus the
saturation economics: past a small width, tokens grow while success plateaus.

## Cost estimate (adoption preview)

Planning-call multiplier of ~2–4× per difficult Goal at width 2; a model-based verifier
(which this fixture rubric stands in for) adds one scoring call per scored candidate —
the fixture's `max_scored_candidates` cap is the knob that bounds that second bill.
Maintenance burden is one test module; no product surface changes.

## Trust-boundary implications

None at this head: the search is inert (no authority imports, no node registration, no
store). If graduated, candidate scoring must consume only artifacts the principal may
read, and the width/branching caps must compose with `evaluate_dag_shape` (the
security-review-team gate), not bypass it — the synthesized candidate still goes
through the same shape review before any child Run.

## Disposition

**INCUBATE.** The machinery validates the search economics end to end against the
canonical compilation seam, and the fixture boundary (repairable proposer +
discriminating verifier ⇒ uplift; otherwise strictly negative net value) is exactly the
decision rule a real study needs. But the hypothesis itself — uplift on *real*
difficult Goals with *real* planners and verifiers — is unproven, and synthetic traps
are not evidence about models (M8 guardrail 5).

Next required evidence (in order):

1. A provider-backed A/B on a real difficult-Goal subset: one-shot `DagSynthesizer`
   vs bounded beam (width 2) over `LLMDagSynthesizer` samples, candidates validated by
   `validate_dag` + `evaluate_dag_shape`, scored by an independent model-based verifier,
   outcomes read from the executed child Runs' NodeRun/Attempt records.
2. The verifier-quality ablation on the same data (blind/weak ranker vs review-signal
   ranker) to locate the real discrimination threshold.
3. A cost frontier at production rates: success vs planning tokens/latency across
   widths {1, 2, 3}, to confirm the saturation point transfers off the fixtures.

Production changes, if evidence lands, route to the Goal/Graph/orchestrator owner per
the epic exit; the search itself stays a pre-Run planner with no execution authority.
