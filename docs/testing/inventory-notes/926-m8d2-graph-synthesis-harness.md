---
inventory-delta:
  packages/maistro-core/tests: +40
---
# 926 M8-D2: canonical Graph synthesis benchmark harness (+40)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #926 (epic #903, initiative #879) asked for an evaluation of automatic
canonical Graph synthesis from Goals and constraints, with a
GRADUATE/INCUBATE/REJECT/WATCH disposition and the binding constraint that
generated Graphs are candidates, never a parallel execution model. No
provider-backed planner experiment exists in deterministic CI (no credentials,
no representative Goal corpus with recorded Runs), so the research record
(`docs/research/926-graph-synthesis-from-goals.md`) registers WATCH and this
change adds the reproducible measurement machinery the issue's measure list
demands, as one self-contained test module in `packages/maistro-core/tests/graph/`
(`test_m8d2_graph_synthesis_research.py`, +40 node IDs).

Unlike the earlier M8 harnesses (which import no maistro module), this one
deliberately reuses the shipped read-only test seam (M8 guardrail 2): the
issue's core measure is validity *against canonical schema/legality*, so the
legality oracle is the real `maistro.graph.dag_validator.validate_dag`, the
real capability catalog (`maistro.graph.nodes.list_kinds`/`get_node` with real
input/output schemas), the real budget policy
(`maistro.graph.policies.resolve_max_cycles`, #1184), and the real shipped seed
(`maistro.graph.seeds.daily_status_seed`). The import surface is pinned by an
AST allowlist test to exactly those four pure/read-only surfaces — no executor,
no run store, no durable-run machinery — so the harness can emit candidates and
grade them but can never become a second execution model. The 40 cases validate
the machinery on deterministic, hand-checked fixtures: the evidence-only
contract itself (advisory marker, AST import allowlist, frozen report records,
empty-statement and empty-needs Goal rejection); seam realism (the real catalog
contains every fixture kind, the real seed passes the real gate, its declared
budget covers its five-wave depth, and the local schema predicate agrees with
the real validator on every reference edge); planner behavior (the synthesis
planner refuses Goals demanding catalog-absent kinds instead of hallucinating,
emits only catalog kinds, passes the real legality gate on every synthesizable
fixture, covers every needed kind, refuses when needs exceed the max-nodes
constraint, and the manual-template baseline serves exactly the two Goals its
one shipped template covers with byte-identical reuse); scripted LLM defect
modes flagged by the real gate (hallucinated kind → unknown_kind, back-edge →
cycle — the gate names only the first cycle its DFS meets, dangling edge →
edge_missing_endpoint, forgotten data wiring → schema_mismatch, undeclared
budget resolving to the one-wave floor under a deeper graph); the
validator-feedback repair loop (every defect mode repaired to real legality
with exact iteration counts — two back-edges cost exactly two iterations,
placeholder fills restore legality but are billed to review burden, repair
never invents kinds, the all-hallucinated candidate is unrepairable and
refused, the raw candidate is never mutated, and repairing a legal candidate is
a no-op); and the grid measures as hand-checked arithmetic (baseline coverage
ceiling 2/5, synthesis arm 4/4 fidelity with zero illegal dependencies, raw
stub arm 1/5 valid with 7 raw findings, repair restoring legality but not
always fidelity — the legal-but-extra review node keeps goal_success false —
repair iterations billed one planner call each (11 total vs 5 unrepaired),
exact planned-cost accounting (nodes/waves/LLM-backed/HITL), byte-identical
canonical-form reuse (baseline 2 hits, synthesis 1 content-addressed hit, stub
arms 0), and review burden (10 admission-time human touches raw, 3 after
repair, 0 for clean arms)); plus reference-decomposition sanity (the
human-signoff reference routes markdown from the format node, never through
review, and every synthesizable fixture has a legal, budget-covering
reference).

Two findings already recorded by the machinery at this head, both about the
catalog rather than the harness: the node catalog's output→required-input
schema graph is mostly disconnected (nothing consumes `llm.summarize`'s
`summary` or `human.review_and_edit`'s `verdict`), so faithful compositions
lean on Goal-supplied static parameters — which is exactly where synthesis
 burden and human review burden concentrate; and the shipped template library
is one DAG, so the manual-template baseline's coverage ceiling is structurally
low (2 of 5 fixture Goals). Both feed the WATCH disposition's next-evidence
list in the research note.
