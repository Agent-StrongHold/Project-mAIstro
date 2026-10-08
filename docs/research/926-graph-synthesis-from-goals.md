# M8-D2 research note — automatic canonical Graph synthesis from Goals and constraints

Leaf: #926. Epic: #903 (M8-D — planning, Goal decomposition, Graph synthesis).
Initiative: #879.

## Hypothesis

A planner can synthesize valid, useful canonical Graphs directly from
Goal/rubric/capability constraints with fewer manual templates and better reuse
than ad hoc action loops.

## Canonical seams (verified against the shipped tree)

Everything the hypothesis needs already ships; the experiment reuses the seams,
it does not add any:

- **Planner input seam — `SynthRequest`** (`packages/maistro-core/src/maistro/graph/synth.py`):
  an objective, constraints, available kinds, and a max-nodes bound; the
  `DagSynthesizer` protocol already has a deterministic rule implementation
  (`RuleDagSynthesizer`) and an LLM implementation (`LLMDagSynthesizer`) with an
  injectable `llm_call`, wired through the `agent.synth_dag` node.
- **Candidate shape — the DAGFile dict** (`{nodes: [{id, kind, inputs|config}],
  edges: [{from_node, to_node}], entry_node, max_cycles}`), the shape the
  canonical validator consumes at save time (`PUT /v1/dags/{id}`) and again at
  run time (defense in depth).
- **The legality gate — `validate_dag`**
  (`packages/maistro-core/src/maistro/graph/dag_validator.py`): structure
  (endpoints, entry, cycles), kind registration, and per-edge schema
  compatibility (a downstream node's required inputs must be covered by the
  upstream output schema or its own static inputs). Admission is the registry's
  validate-then-register (`maistro.graph.dag_registry`, `dag:<id>` as a callable
  agent) behind its human gate.
- **The capability catalog — `maistro.graph.nodes`**: 19 registered kinds at
  this head, each with real `input_schema`/`output_schema`. This is what
  "available capabilities" concretely means for synthesis.
- **The budget policy — `resolve_max_cycles`**
  (`packages/maistro-core/src/maistro/graph/policies.py`, #1184): a declared
  cycle budget counts traversal waves and must cover the candidate's depth;
  undeclared budgets floor to one wave. A synthesizer that under-declares
  ships a graph that cannot run — a legality dimension beyond the validator.
- **Execution — the canonical runtime** (`Graph -> Run -> NodeRun -> Attempt`):
  accepted candidates execute through `run_durable_dag`/the graph executor like
  any saved DAG; nothing about synthesis changes execution.
- **Reuse — the template/seed surface**: exactly one shipped seed DAG exists
  (`daily_status_seed`, PM fleet), registered per use_case. The manual-template
  world's library is that small.

## Record

This note does not report a provider experiment. The deterministic CI
environment holds no provider credentials and no representative Goal corpus
with recorded Runs exists in-tree; manufacturing one was out of scope, and
absent evidence is recorded rather than simulated (M8 guardrail 3). This
change adds no product code, no flag, and touches no authority path.

What it adds is the reproducible measurement machinery the experiment demands,
as a separated research artifact:
`packages/maistro-core/tests/graph/test_m8d2_graph_synthesis_research.py`
(test suite only; 40 node IDs, delta in
`docs/testing/inventory-notes/926-m8d2-graph-synthesis-harness.md`). Unlike
the earlier M8 harnesses it imports four maistro surfaces deliberately — the
validator, the catalog, the budget policy, and the seed — because the leaf's
core measure is validity *against canonical schema/legality*, and a
re-implemented validator would grade candidates against a drift-prone copy
(benchmark theater, M8 guardrail 5). All four are pure/read-only; an AST
allowlist test pins the import surface so the harness cannot reach an
executor, a run store, or durable-run machinery — generated Graphs are
candidates, never a parallel execution model (the leaf's binding constraint).

The machinery implements, on a fixture grid of five representative Goals
(four synthesizable, one demanding catalog-absent capabilities) and four
planner arms:

- **Arms.** `manual-template` (the status quo: reuse the closest saved
  template, never synthesize); `synthesis` (rule-based, capability-driven:
  refuse catalog-absent needs loudly, emit one node per needed kind with the
  Goal's static parameters, wire each node from the latest upstream output
  that covers its uncovered required inputs, fan out from the entry when none
  does, declare a budget equal to the candidate's depth);
  `llm-stub-scripted` (deterministic stand-ins encoding one characteristic
  failure mode each — hallucinated kind, double back-edge, dangling edge,
  forgotten data wirings, and an everything-hallucinated answer for the
  unsynthesizable Goal); and the same stub arm wrapped in the repair loop.
  The stubs are fixtures for validating the machinery; they are not evidence
  about real models.
- **Measures** (the issue's list, per (arm, Goal) cell): graph validity (the
  real gate plus budget-covers-depth), goal success (valid AND every needed
  kind present AND nothing extra vs the reference decomposition), missing/extra
  nodes, illegal dependencies (validator error findings on the raw candidate),
  repair iterations (validator-feedback loop, billed one planner call each),
  planned execution cost (nodes, waves, LLM-backed kinds, HITL kinds),
  reuse (byte-identical canonical-form hits against the arm's accepted
  library), and human review burden (admission-time placeholder fills +
  residual findings + budget redeclarations).
- **Repair loop** (deterministic, documented per rule): drop unknown-kind
  nodes and their edges, drop the highest-index cycle-closing edge per
  iteration, drop dangling edges, write missing required inputs as
  admission-time placeholder statics, raise under-declared budgets to the
  resolved depth; unrepairable within three iterations is refused at
  admission with the residual named.

What the fixtures demonstrate (machinery validation on hand-checked
arithmetic, **not** evidence about real planners):

- **The manual-template world has a structural coverage ceiling**: one shipped
  template serves exactly 2 of 5 fixture Goals (both daily-status variants);
  the other three are refused for want of a template. Its reuse is real but
  bounded by what humans already authored (2 byte-identical hits).
- **Rule-based synthesis covers the representative Goals with zero illegal
  dependencies**: 4/4 synthesizable Goals valid and faithful (missing 0,
  extra 0), refusing the catalog-absent Goal before emission, 0 repair
  iterations, 0 admission-time human work — and 1 reuse hit: the repeated
  daily-status Goal synthesizes to a byte-identical, content-addressed
  candidate, so exact-shape reuse is available to synthesis, not just to
  manual templates.
- **Raw LLM-style output is measurably illegal**: the scripted stub arm ships
  7 validator findings across 5 goals (cycle, unknown kinds, dangling edge,
  schema mismatches), 3 budget violations, and 10 admission-time human
  touches; only its clean candidate (1/5) is valid.
- **Repair restores legality, not fidelity** — the recorded insight: after
  repair, 4/5 candidates pass the real gate, but the candidate carrying a
  legal-but-extra review node stays goal-success-false (extra node), and the
  all-hallucinated candidate is unrepairable (dropping its nodes leaves
  nothing to anchor) and is refused. Repair cost is visible: 6 extra planner
  calls (11 vs 5) and 3 residual human touches (2 placeholder fills + 1
  refusal residual).
- **The catalog's schema graph is mostly disconnected**: nothing consumes
  `llm.summarize`'s `summary` or `human.review_and_edit`'s `verdict`, and
  several required inputs (`text`, `document`, `markdown`) have no upstream
  producer at all. Faithful compositions therefore lean on Goal-supplied
  static parameters — exactly where synthesis burden and human review burden
  concentrate. Any real planner evaluation must score parameter sourcing, not
  just topology; a planner that "succeeds" by making everything static has
  not synthesized a graph, it has dressed a prompt chain in DAG syntax.
- **The budget policy is a first-class legality dimension**: 3 of 5 scripted
  candidates under-declare or omit `max_cycles` and cannot run at their own
  depth (one resolves to the one-wave floor). A synthesis evaluation that
  only runs the validator misses this.

Executed probe record (head af7996883, 2026-10-08):
`uv run pytest packages/maistro-core/tests/graph/test_m8d2_graph_synthesis_research.py -q`
→ 40 passed; the full graph suite (1920 passed, 120 skipped) is unaffected;
`uv run ruff check` and `uv run ruff format` clean on the module;
`scripts/check-suite-inventory.py --suite packages/maistro-core/tests` → ok
(15446 = 15406 baseline + 40 delta); the frozen report is byte-identical
across invocations (asserted by a test).

## Benchmark procedure (what a real experiment must do)

1. Build the Goal corpus: representative Workspace Goals with rubric/capability
   constraints (the `SynthRequest` fields: objective, constraints,
   available kinds from the live catalog, max_nodes), each with a reference
   decomposition a human accepts, and with execution recorded through the
   canonical runtime so *goal success* is a Run outcome, not a proxy.
2. Run candidate planners (at minimum: the shipped `RuleDagSynthesizer`, an
   LLM planner under the governed inference seam, and a retrieval-first
   planner that searches the accepted-DAG library before generating) over the
   corpus; every emission passes the real `validate_dag` + budget gate; every
   accepted candidate executes through the normal runtime.
3. Score the issue's measure list per (planner, Goal): validity, goal success
   (Run/rubric outcome), missing/extra nodes vs the reference, illegal
   dependencies, repair iterations, execution cost (recorded Attempt/token
   cost, not planned cost), reuse potential (library hit rate), and human
   review burden (admission findings + parameter fills + review time).
4. Compare against the manual-template baseline at equal review budget.
5. Update the disposition here. Generated Graphs remain candidates admitted
   through the canonical registry's human gate; no planner output executes
   outside the canonical runtime.

## Trust boundary

Synthesis research and execution/admission authority stay separate — this
leaf's own contract sentence and the epic's. Every number the harness produces
is advisory evidence: it writes no Goal, creates no Run, invokes no executor,
and touches no Warden/HITL/delegation control. The AST allowlist test pins the
harness to four pure/read-only maistro surfaces (validator, catalog, budget
policy, seed), so it cannot drift into an execution authority by accident
(M8 guardrails 1-2). A synthesis strategy that survives a real experiment
reaches production only as a change to the canonical planner seam
(`DagSynthesizer` implementations behind `agent.synth_dag`) and admission
flows the DAG registry already owns — never through this harness.

## Disposition

- #926 (automatic canonical Graph synthesis from Goals and constraints):
  **WATCH**.

Why not INCUBATE: the machinery works and the seam is real, but the
hypothesis's comparative claims (fewer manual templates, better reuse than ad
hoc action loops, acceptable human review burden) are exactly the parts no
in-tree evidence can support yet — they need provider-backed planners over a
representative Goal corpus with Runs, and today's catalog makes the
"capability constraints" input nearly vacuous (19 kinds, mostly disconnected
schema graph; faithful compositions degenerate toward statically parameterized
chains). Incubation would signal the prototype is waiting on a decision; it is
waiting on data that does not exist.

Next required evidence (triggers for reassessment):

1. A representative Goal corpus with reference decompositions and recorded
   Runs (the M8-D epic's shared corpus need).
2. At least one governed provider-backed planner scored on it, with repair
   iterations and admission burden recorded against the manual-template
   baseline at equal review budget.
3. A catalog whose schema graph is dense enough that synthesis is meaningfully
   constrained by capability legality (more composable transform outputs,
   or schema-typed blackboard passing between nodes); reassess when the node
   catalog materially changes.
4. Reuse evidence: whether content-addressed exact-shape reuse (already shown
   available in principle by the machinery) accrues at real corpus scale, or
   whether fuzzy/parameterized reuse is required (a different, harder design).
