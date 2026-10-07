---
inventory-delta:
  packages/maistro-core/tests: +32
---
# 889-m8a9-metamorphic-harness

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #889 (epic #880, initiative #879) asked whether metamorphic relations can
test semantic stability where MAIstro has no single exact expected output —
retrieval, AI decisions, providers, and Graph semantics. Unlike the sibling M8
research harnesses (#919/#920, deliberately import-free measurement machinery),
this leaf's contract is to run **against the current implementations**, so the
+32 node IDs land as one module in
`packages/maistro-core/tests/research/test_m8a9_metamorphic_research.py` that
imports the real `maistro.memory.working.recall`,
`maistro.router.selector`, and `maistro.graph.dag_validator` seams (guarded by
its own `test_harness_targets_real_implementations`).

The module delivers the reusable pattern the issue's deliverable names: a pure
relation oracle per metamorphic relation (tolerance written in code, not
prose), a seam adapter producing observation records from the real
implementation, derandomized Hypothesis case generation, and seeded-mutant
probes separating false-positive rate (violations on unmutated seams: 0) from
detection power (7/7 fixture mutants, plus two production-path mutants applied
by monkeypatching the real `score_entry` and `filter_candidates` — an
irrelevant-content scoring regression and a dropped provider-status check —
both caught). The research record with the GRADUATE/INCUBATE/REJECT/WATCH
disposition is `docs/research/889-metamorphic-testing.md` (registers
**INCUBATE**).

Three tolerance boundaries were found while stating the relations and are
pinned as tests rather than prose: the empty-query domain restriction (an
empty query returns the whole working set, so the injection relation does not
apply there); the retrieval recency bonus (≤ 0.01 shift — the relation's
explicit tolerance); and the router's 4-decimal rounding window, inside which
insertion order legitimately decides the winner (stable sort over rounded
scores), with the same first-max order sensitivity documented for the
`_fallback` degraded path — routed to the router owner in the research record.
No production code changed; no vulture/reachability/egress identity moves.
