---
inventory-delta:
  packages/maistro-core/tests: +45
---
# 920 M8-C1: hybrid vector + graph retrieval research harness (+45)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #920 (epic #901, initiative #879) asked for a benchmark comparing hybrid vector + graph
retrieval against vector-only Workspace memory, with a GRADUATE/INCUBATE/REJECT/WATCH
disposition and no second canonical memory store. No real Workspace-history experiment exists
in deterministic CI (no provider embeddings, no real histories), so the research record
(`docs/research/920-hybrid-vector-graph-retrieval.md`) registers WATCH and this change adds
the reproducible measurement machinery the issue's measure list demands, as one self-contained
test module in `packages/maistro-core/tests/memory/`
(`test_m8c1_hybrid_retrieval_research.py`, +45 node IDs).

The module is deliberately test-side and imports no maistro module (asserted by its own AST
contract test): it is research evidence, not product code, so no vulture/reachability identity
changes. The 45 cases validate the machinery on deterministic fixtures: the evidence-only
contract itself (advisory marker, no-maistro-import AST scan, frozen results, empty-corpus,
duplicate-query-id, ghost-dependency-endpoint and bad-config rejections, unknown-strategy
refusal); hand-checked arithmetic on an explicitly declared embedding table (orthogonal
concept axes, every cosine a sum of 1/√2 terms) — vector-only acing the direct family, the
baseline returning zero-similarity rows exactly as `find_similar`'s LIMIT does (no
positive-similarity predicate in the SQL), structural impossibility of *positively ranking*
textually-orthogonal relational evidence, the anchored one-hop hybrid reaching it within
budget with an exact provenance chain, budget-0 degenerating exactly to vector-only, recall
monotone in budget, recency-blind cosine leading with a superseded fact that the (hypothetical,
clearly labeled) weight-x-recency control and full-set-before-cut supersession demotion each
repair — demotion including the k=1 window, a single false edge both losing the true hop and
admitting a distractor, exact graph-construction miss/spur set arithmetic,
100%-extraction-failure degenerating to the baseline, exact storage accounting (6 vectors x 5
floats vs 168 graph bytes with supersession entries priced), expansion work charged exactly
(admissions + inspections) with a probe proving latency moves with graph size under a fixed
budget, anchoring proven to read the extracted graph's mentions rather than ground truth, and
expansion origin measured independently of chain integrity; and a seeded 21-record/14-query
corpus asserting only what construction guarantees — hybrid relational recall 1.000 vs
vector-only 0.625 under ROLE-labeled relevance (the impact chain's consumption statements, not
the membership predicate the strategy expands through; the next-hop record shares no token
with the query, checked textually at build), the measured direct-family cost of the same
anchoring (recall 1.000 to 0.850, sufficiency 1.000 to 0.400 at k=8), the stale-edge
degradation sweep (1.000 → 0.625 at spur 0.5 → 0.500 at spur 1.0 — below the vector-only
baseline, because misroutes displace weakly-ranked relevant rows), a guaranteed
spurious-mention rate (mention_spur = 1.0 injects exactly one outside mention per record),
provenance completeness 1.0 with the tight-window witness orphaning defect (self-containment
0.0 at k=1), per-query admissions staying budget-capped while inspections are charged, and a
finite, stable JSON report. Ten regression probes against the pre-review harness (zero-row
baseline, demotion-before-cut, admission-time origin, extracted-mention anchoring,
graph-size-dependent latency, duplicate query ids, ghost dependency endpoints, guaranteed
spur rate, priced supersession entries, role-labeled relational ground truth) each fail on
the old code and pass on this one.

Net +7 over the initial +38: eight cases are new (duplicate query ids, ghost dependency
endpoints, zero-similarity seam parity, exact expansion-work charging, latency-vs-graph-size
under a fixed budget, extracted-mention anchoring, origin-vs-chain independence, guaranteed
spurious-mention rate) and one was absorbed — the admissions-only budget-bound test was
replaced by the exact-charging versions it contradicted (its seeded counterpart and the
relational ground-truth test were rewritten in place, same node count).
