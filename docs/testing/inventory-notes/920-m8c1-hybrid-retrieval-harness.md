---
inventory-delta:
  packages/maistro-core/tests: +38
---
# 920 M8-C1: hybrid vector + graph retrieval research harness (+38)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #920 (epic #901, initiative #879) asked for a benchmark comparing hybrid vector + graph
retrieval against vector-only Workspace memory, with a GRADUATE/INCUBATE/REJECT/WATCH
disposition and no second canonical memory store. No real Workspace-history experiment exists
in deterministic CI (no provider embeddings, no real histories), so the research record
(`docs/research/920-hybrid-vector-graph-retrieval.md`) registers WATCH and this change adds
the reproducible measurement machinery the issue's measure list demands, as one self-contained
test module in `packages/maistro-core/tests/memory/`
(`test_m8c1_hybrid_retrieval_research.py`, +38 node IDs).

The module is deliberately test-side and imports no maistro module (asserted by its own AST
contract test): it is research evidence, not product code, so no vulture/reachability identity
changes. The 38 cases validate the machinery on deterministic fixtures: the evidence-only
contract itself (advisory marker, no-maistro-import AST scan, frozen results, empty-corpus and
bad-config rejections, unknown-strategy refusal); hand-checked arithmetic on an explicitly
declared embedding table (orthogonal concept axes, every cosine a sum of 1/√2 terms) —
vector-only acing the direct family, structural impossibility of ranking textually-orthogonal
relational evidence, the anchored one-hop hybrid reaching it within budget with an exact
provenance chain, budget-0 degenerating exactly to vector-only, recall monotone in budget,
recency-blind cosine leading with a superseded fact that weight-x-recency and supersession
demotion each repair, a single false edge both losing the true hop and admitting a distractor,
exact graph-construction miss/spur set arithmetic, 100%-extraction-failure degenerating to the
baseline, exact storage accounting (6 vectors x 5 floats vs 424 graph bytes), and per-query
work bounded by the expansion budget; and a seeded 21-record/14-query corpus asserting only
what construction guarantees — hybrid relational recall 1.000 vs vector-only 0.2125 (the
next-hop record shares no token with the query, checked textually at build), the measured
direct-family cost of the same anchoring (recall 1.000 to 0.850), the stale-edge degradation
sweep (1.000 to <= 0.45 at full spur), provenance completeness 1.0 with the tight-window
witness orphaning defect (self-containment 0.0 at k=1), nearest-rank p95 work bounds, and a
finite, stable JSON report. Six mutation probes (inert fusion weight, age-blind recency,
unbounded budget, dropped provenance chains, no-op supersession, unanchored expansion) each
fail the suite.
