---
inventory-delta:
  packages/maistro-rsi/tests: +33
---
# #928 M8-D4 bounded plan-search research harness (+33)

Evidence-only research harness for the M8-D4 leaf (epic #903): bounded beam/tree/MCTS-style
search over candidate plans. No product code changed — the module lives in
`packages/maistro-rsi/tests/test_m8d4_plan_search_research.py` (+33 node IDs) and reuses
the canonical candidate-compilation seam deliberately (`maistro.graph.types.GraphConfig`
plus the production validator `maistro.graph.dag_validator.validate_dag`), while importing
no execution or persistence authority (`maistro.runs`, `maistro.graph.executor`,
`maistro.graph.durable_runs`, `maistro.graph.harness*`, `maistro_server` are source-scanned
as forbidden imports — the search dispatches nothing and registers no node).

The 33 cases:

- `TestCompileGate` (5): a valid linear plan compiles to a canonical `GraphConfig`
  (entry `step0`, chained edges) behind the real validator; the hallucinated
  `auto.test` kind is rejected by the production registry (`unknown_kind`); mid-chain
  `human.ask_question` fails real schema compatibility while the same step validates at
  entry (its question text is goal-dependent, so the compiler cannot wire it); the empty
  plan has no entry and covers nothing; and the oracle/score independence pin — a
  coverage-complete but validator-defective candidate scores `None` and fails the oracle,
  so neither instrument substitutes for the other.
- `TestBoundedSearch` (6): caps respected exactly (calls ≤ 1+(depth−1)·width, distinct
  scored candidates ≤ cap); width=1/branching=1 is exactly one-shot with pinned
  accounting (4 calls, 640 tokens, 168 ms); beam accounting pinned per level (root bills
  one call, deeper levels bill per beam member); determinism (beam and MCTS reports
  byte-equal across runs); exhausted budget terminates cleanly at the cap; selection is
  never empty; a tight `max_scored_candidates` cap binds exactly (10 candidates compiled
  for cap 10) and reports the deepest prefixes actually searched — no fabricated plans.
- `TestUplift` (3): on the 10-goal difficult subset, one-shot success 0.20 → beam 1.00
  (uplift +0.80) at 3.5× planning tokens (2240 vs 640) and 3.75× latency (630 vs 168 ms);
  search strictly costs more planning than one-shot with the per-call economics pinned;
  a blind scorer earns no uplift (−0.20) at the identical token bill — uplift is a
  property of scorer discrimination, not of search alone.
- `TestSensitivity` (3): success non-decreasing in beam width; cost strictly increasing
  in branching; gains saturate before cost does (width 2 → 3: +0.00 success for +43%
  tokens).
- `TestDiversity` (3): a degenerate proposer collapses the beam to one distinct plan
  (no diversity, no gain over one-shot); normal search surfaces distinct executable
  candidates; mean-pairwise-Jaccard distance spans [0,1] and separates the degenerate
  candidate set from the normal one.
- `TestVerifierError` (4): calibrated scorer has zero top-1 regret on the subset; an
  adversarial ranker incurs real regret (2 cells) and drops success to 0.50; scorer↔oracle
  Kendall tau tracks scorer quality; tau identities on toy rankings (perfect, inverted,
  fully-tied).
- `TestMctsStyleSearch` (3): the MCTS-style variant respects iteration/budget caps,
  holds non-negative uplift (+0.10 at 12 iterations), and UCB1 provably spreads visits
  beyond the single greedy arm.
- `TestOverfitting` (2): honest tuning-split hyperparameters transfer to the interleaved
  eval split (tuning 0.6 / eval 0.8, gap 0.2); leaked per-goal tuning on the evaluation
  split itself inflates the measured uplift to 1.0 — the benchmark-theater trap the leaf
  asks to evidence.
- `TestEvidenceOnlyContract` (3): source scan proves the machinery imports no execution
  or persistence authority; the selected candidate is data (steps + canonical
  `GraphConfig` + score, no `run_id`/`execute`); the search registers no node kind and
  needs no store.

Every headline number is pinned at the fixed fixture seeds, so a change in the proposer,
scorer, accounting, or validator integration moves a named assertion. Mutation-checked
in work: bypassing the validator flips the compile-gate pins; disabling score-ranked
pruning drops beam success to 0.0; removing the ledger's exhaustion check runs 7 calls
against a cap of 2; the adversarial/blind scorers isolate verifier quality as the
uplift-carrying variable.
