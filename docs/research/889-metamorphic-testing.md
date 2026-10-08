# M8-A9 research note — metamorphic testing for retrieval, AI decisions, providers, and Graph semantics

Leaf: #889. Epic: #880 (advanced verification and assurance). Initiative: #879.

## Hypothesis

Where MAIstro lacks a single exact expected output, metamorphic relations can
still test semantic stability and catch regressions in retrieval, provider
selection, memory, and Graph behavior.

## Canonical seams

Three real subsystems whose output has no single exact oracle, all
deterministic in CI (no provider calls, no model nondeterminism):

* **Retrieval** — `WorkingMemoryRecall.recall`
  (`packages/maistro-core/src/maistro/memory/working/recall.py`): lexical
  matched-term-share scoring over the working set, a recency bonus of at most
  `0.01 * (position / total)`, digest-collapse of re-stated claims, and one hop
  of lineage expansion over shared `result_ref` / content digest. Writes reach
  a hot projection through `WorkingMemoryManager.observe`
  (`packages/maistro-core/src/maistro/memory/working/projection.py`); a
  raw-store write is only coherent after `dispose` (re-hydration). Workspace
  scoping is the store's `workspace_id` keying — the seam the "inaccessible
  Workspace" relation probes.
* **Provider selection** — `RouterEngine.select_with_usage`
  (`packages/maistro-core/src/maistro/router/selector.py`): filter (status,
  modality, tier band, quota/reserve) → `score_candidate`
  (`packages/maistro-core/src/maistro/router/scorer.py`, scores **rounded to
  4 decimals**, cost normalized against a fixed realistic band, no set-wide
  dependence) → stable descending sort. `_fallback` (degraded path) keeps the
  first maximum quality seen.
* **Graph identity** — `validate_dag`
  (`packages/maistro-core/src/maistro/graph/dag_validator.py`): structure
  (endpoints, entry, cycles) + per-edge schema compatibility over the Hive
  DAGFile shape, with id-bearing finding messages.

Baseline evidence before this leaf: the seams carry conventional
example/property tests (`packages/maistro-core/tests/memory/`,
`tests/router/`, `tests/graph/`) that pin specific inputs and outputs. None
states an input-transformation invariant, and none can: the "correct" ranking
for an arbitrary query has no exact expected value to assert.

## Relations (transformations → expected invariants)

| id | Transformation T | Relation R (with stated tolerance) |
|---|---|---|
| MR-A1 | Append irrelevant observations (zero lexical overlap with the query) through the real write path | Top relevant hits keep their ids, order and matched terms; per-hit scores shift ≤ 0.01 (the seam's recency-bonus bound); injected entries rank nowhere. Domain: non-empty query. |
| MR-A2 | Write the same observation under a foreign Workspace id, then re-hydrate | Recall in the original Workspace is unchanged; the foreign entry is addressable only in its own Workspace (`get_result` cross-Workspace returns `None`). |
| MR-B1 | Add catalogue entries on every ineligibility axis (inactive provider, wrong modality, out-of-band tier, quota-exhausted without paygo), each with winning quality | The whole `ModelSelection` — winner, score, reason, candidate list — is unchanged. No tolerance. |
| MR-B2 | Permute catalogue insertion order | Winner changes only to a candidate tied at the same rounded score (the rounding window); candidate `(model_id, score)` multiset and the tied-at-max set are invariant. |
| MR-C1 | Apply a node-id bijection to a DAG (nodes, edge endpoints, `entry_node`) | `validate_dag` findings are equal as multisets of (code, severity, mapped node, edge index, field path, mapped message); the kind-labeled shape (node kinds, edge kind-pairs, entry kind) is invariant. |

All six candidate relations from the issue are covered by these five: the
"permutation of order-neutral inputs" relation is MR-B2 (catalogue order) and
the equal-score tier of MR-A1; "prompt/context normalization" was **not**
implemented — the structured-contract surface in deterministic CI is the DAG
validator and the selection record, both covered, and the remaining candidate
(prompt normalization tolerance) is a subjective model-quality assertion by
the issue's own distinction; it is recorded under exclusions below.

## Reusable pattern (the deliverable)

`packages/maistro-core/tests/research/test_m8a9_metamorphic_research.py`
(32 node IDs) ships the pattern as code:

1. **Pure relation oracles** — `check_ranking_stability`,
   `check_workspace_isolation`, `check_selection_invariance`,
   `check_permutation_tolerance`, `check_rename_isomorphism` — from baseline
   and transformed *observation records* to concrete violation strings, with
   each tolerance written into the code.
2. **Seam adapters** — `run_mr_a1_case` (writes through
   `manager.observe`, the production write path), the router catalogue
   builders, and the Graph rename adapter over real registered node kinds.
3. **Generated cases** — Hypothesis, `derandomize=True` for deterministic CI
   (68 generated cases across the three targets per run).
4. **Mutant probes** — every oracle must detect a seeded violation: 7
   record-level mutants, plus 2 production-path mutants applied to the real
   seams (a `score_entry` regression that lets irrelevant content match; a
   `filter_candidates` regression that drops the provider-status check). A
   regression in the named seam fails the harness; the oracles cannot rot
   into pass-only checks unnoticed.
5. **An evidence battery** — `run_evidence_battery()` records per-relation
   case counts, violations on the real seams (false positives), wall time
   (CI cost), cross-run determinism, and per-mutant detection, asserted by
   dedicated tests so the evidence cannot silently degrade.

## Evidence

* **Defect yield on current code: 0 live defects** in the three seams at this
  head (`28614700bd9a`): all relations hold across the generated and fixed
  cases, zero violations (`test_evidence_battery_zero_violations_on_real_
  seams`). The existing suites already cover these paths well — expected,
  and recorded as such rather than inflated.
* **Demonstrated detection power: 9/9 mutants caught** — the 7 record-level
  probes plus the 2 production-path regressions described above
  (`test_evidence_battery_detects_every_seeded_mutant`,
  `test_mr_a1_detects_ranking_regression_on_real_seam`,
  `test_mr_b1_detects_filter_regression_on_real_seam`). The relations fail
  when their seam regresses; they are not vacuous. In particular the MR-A1
  harness initially *was* vacuous — injections written via the raw store
  never reached a hot projection — and was rewritten to the `observe` write
  path exactly because the mutant probe could not fire otherwise. That
  failure mode (a metamorphic harness passing over a seam it never touches)
  is the main risk of this technique and the reason the production-path
  mutants are part of the pattern.
* **False-positive rate: 0** across all generated and fixed cases on the
  unmutated seams.
* **Tolerance-definition difficulty: three boundaries found and pinned.**
  (1) The empty query returns the whole working set, so MR-A1 needs an
  explicit non-empty-query domain restriction
  (`test_mr_a1_empty_query_excluded_from_relation_domain`). (2) The recency
  bonus makes MR-A1 approximate: score shifts up to 0.01 are legal, and the
  relation would need a narrower tolerance (or a no-bonus seam change) to
  reorder hits whose lexical scores differ by less than the bonus — with the
  seam's quantized match-share scores (≥ 1/k gaps for k query terms) this is
  unreachable for realistic k. (3) The router's `round(score, 4)` plus a
  stable sort means insertion order decides the winner inside a rounding
  window (`test_mr_b2_rounding_window_ties_are_the_documented_tolerance`);
  the oracle encodes this as the tolerance rather than reporting a defect.
* **Nondeterminism sensitivity: none observed.** All three seams produced
  byte-identical records across repeated runs (`determinism_across_runs` in
  the battery; derandomized generation). The relations separate cleanly from
  subjective model-quality assertions: nothing here requires a model, and the
  one candidate relation that would have (prompt-normalization tolerance) was
  excluded for exactly that reason.
* **CI cost: negligible.** The whole module runs in ~2s (`pytest ... -q`,
  measured 2.0–2.2s wall on this machine); the fixed battery alone is ~2 ms.
  Cost is asserted bounded (`test_evidence_ci_cost_measured_and_bounded`) as
  a smoke bound, not a performance contract.
* **Developer complexity / maintenance: low but non-zero.** The oracles are
  pure functions over records; the adapters are the maintenance surface —
  they follow the real seams' APIs (write paths and coherence rules matter,
  as the vacuity incident shows). The `test.m8a9_*` probe node kinds follow
  the repo's fixture-registration convention (the `test.` kind prefix the
  production-registration reconciliation excludes) and collide with nothing.

## What failure class this catches that existing gates do not

Exact-output tests pin one input to one output; property tests pin algebraic
properties of pure functions. Neither states *"this transformation of the
input may not materially change the output"* for a subsystem whose correct
output is unknown. That is the class the metamorphic relations cover: ranking
regressions that keep every pinned example passing while re-ranking the top
hits for everything else; filter regressions that admit an ineligible
provider that then wins on quality; scoping regressions that leak one
Workspace's memories into another's recall; and identity edits that silently
change what a Graph definition validates to. The two production-path mutants
demonstrate the class concretely.

## Findings routed to canonical owners

* **Router (selection tie-break inside the rounding window; `_fallback`
  first-max order sensitivity)** — not live defects: the scored path's
  behavior is a documented consequence of `round(score, 4)` + stable sort,
  and the scorer's own comment records the history (pre-rounding
  saturation ties made insertion order the effective router). Routed here as
  a WATCH note for the router owner: if order-independent tie-breaking is
  wanted, the fix is a total order on `(score, model_id)` — a product change
  this research leaf deliberately does not make. Evidence:
  `test_mr_b2_rounding_window_ties_are_the_documented_tolerance`,
  `test_mr_b2_fallback_exact_tie_order_sensitivity_documented`.
* **Working-memory projection coherence** — the raw-store write path does not
  update a hot projection (by design; `dispose`/re-hydration is the
  documented boundary, and `observe` is the coherent path). Recorded because
  a future "write via store, read via manager" caller would see stale
  recalls; no change requested.

## Exclusions

* **Prompt/context normalization → structured contract outputs** (candidate
  relation 6): the deterministic-CI contract surfaces (DAG validation,
  selection record) are covered by MR-C1/MR-B*; the remaining surface is
  model-mediated and subjective. Excluded per the issue's own
  deterministic-vs-subjective distinction, not skipped silently.
* **Full Graph *execution* semantics under rename** — MR-C1 pins validation
  semantics and kind-labeled structure. Execution-level equivalence (same
  node outputs under renamed identities) needs the executor with model
  bindings and is a natural follow-up (below), not part of this bounded
  prototype.

## Disposition

**INCUBATE.**

* Not **REJECT**: the relations hold, cost ~nothing, caught 9/9 seeded
  regressions including two realistic production-path ones, and cover a
  failure class (transformation invariance over unknown-oracle outputs) that
  no existing gate states.
* Not yet **GRADUATE**: zero live defects found at this head, so there is no
  demonstrated yield on current code yet, and the pattern's maintenance
  surface (seam adapters) has aged zero days. Graduation would mean adopting
  the pattern for a specific seam family as a standing suite — an owner
  decision, not a research leaf's.
* Promotion criteria to GRADUATE: (a) a live defect caught by a metamorphic
  relation on current code, or (b) an owner adopting the pattern for one
  seam family with the production-path mutants kept as regression probes.

## Follow-ups (non-binding)

* Execution-level rename equivalence for Graph runs (needs executor +
  bindings; would complete the issue's Graph-semantics relation).
* A dialect of MR-A1 over the durable pgvector retrieval leg
  (`PgLearningStore.find_similar`) with a real embedding function — the
  hypothesis's "materially change" tolerance would need an embedding-domain
  statement, which deterministic CI cannot yet provide honestly.
* If the router owner wants order-independent tie-breaks, the one-line total
  order above closes the rounding-window sensitivity.
