---
inventory-delta:
  packages/maistro-core/tests: +17
  packages/maistro-design/tests: +44
  tests/: +13
---

# Issue #987 governed design explore/judge (M7-A11)

The design package's explore and model-judge paths become governed Invocations
on the canonical Run spine, and the tests prove the seam rather than the
snapshot.

`test_explore_governed.py` (+8) drives a width=2 explore wave through the
canonical durable Graph walker against real InMemory Project/Run/NodeRun/Attempt
stores and the canonical effect context, with only the gateway HTTP faked at
the shared-client seam: two thesis NodeRuns on one Run, each accepting an
output that names its own Invocation id, with the Invocation rows correlated to
the exact NodeRun/Attempt that asked for them. Fail-closed paths cover a
foreign-Workspace Binding (BindingScopeDenied), an unregistered Binding, a
denying policy evaluator (the Sentinel posture — asserted to have actually
evaluated the call), a Warden-blocked hostile thesis payload, and malformed
model JSON: every one leaves failed Attempts, zero gateway effects and zero
thesis outputs, never a canned wave. A module-source check pins ADR-061 into
the wave path (no DesignEngine). The retry contract is proven rather than
asserted: a slot declares `EFFECT_KEY` replay semantics, so it exposes a
logical effect key, its Invocation carries that key as its effect scope (not
the NodeRun that executed it), and re-entering the slot with the same logical
work under a fresh Attempt/NodeRun replays the recorded Invocation instead of
dispatching a second physical model call (#1194).

`test_model_judge_governed.py` (+10) proves one Invocation per (thesis x
model_judge dimension), eval records naming Goal revision, Rubric revision,
NodeRun/Attempt, judge identity and Invocation, records persisted as the judge
NodeRun's Attempt evidence (no second eval lifecycle), deterministic dimensions
scoring in-process through the declarative vocabulary while still writing
records, `human` dimensions refused loudly (they wait on #794), missing Binding
refusing before any dimension runs, and a scoreless judge response never
completing. The records are also proven to be canonical `#792` Run evidence:
`RunEvalScore` rows persisted on the producing Run (naming the revisions, the
judge NodeRun/Attempt, the judge identity and the Invocation in
`evidence_pointers`), read back through `maestro.runs.eval.eval_summary` —
which is where `eval_complete` comes from, so it is a property of persisted
evidence and not of the node's intention. Two refusals keep that honest: a
judge whose inputs name a Goal revision the Run was not admitted for, and a
judge constructed without the canonical Run store, both fail instead of
reporting a score. The judge's own Invocations carry the wave's logical effect
scope, the same retry contract the thesis slots keep.

`test_governed_fail_closed_paths.py` (+12) pins the refusals the governed
path is made of, because a wave that fails closed in no observable way is a
wave that can quietly start succeeding. The wave's own prompt is asserted, not
assumed: the operator redirect and the rejected theses reach the model
(`Operator redirect (obey): ...`, `Do not repeat these rejected theses: ...`),
so steering the wave is not a promise. A model response with no choices, and a
response whose JSON is an array rather than an object, are failed slots
rather than empty theses. A whitespace-only binding id refuses with
`BindingNotFound` before any prompt is assembled and before any physical
effect exists, and a deployment with no gateway configured refuses outright
instead of failing obscurely inside an HTTP client. On the judge side, a
rubric dimension with no prompt is still judged (without an invented
`Assess:` instruction), while a non-integer score, a duplicated dimension
name, and a response with no choices are not scores. Three refusals keep the
`#792` evidence honest: a judge pointed at a store that does not hold the Run,
a judge on a Run admitted without a Goal binding, and a judge whose store
accepts the write and keeps nothing all fail instead of reporting evidence
they cannot show.

`tests/test_check_design_model_egress.py` (+13) is the CI gate's own
self-check. `scripts/check-design-model-egress.py` is what keeps design
explore/judge on the governed Invocation path, and a gate nobody exercises is
a gate that can rot: the module drives the shipped script on the shipped tree
(green) and on planted violations — a provider SDK import, a raw
model-completion HTTP call, a Design Studio page calling a model host, a
second occurrence of DeckBuilder's recorded governed-chat call, a renamed page
— and pins that each one fails with the breach named. It is also what makes
the gate file measurable: the root suite is the producer that measures
`scripts/`, so a gate no root-suite test executes is a file the diff-coverage
gate reports as "under a measured root but absent from the coverage report".

`test_design_nodes_on_canonical_spine.py` (+4) proves the production
reachability the contract asks for: importing `maistro_design` registers
`design.explore` / `design.thesis` / `design.judge` in the canonical node
registry, the production resolver (`maistro.container.build_node_resolver`,
which the Hive backend builds from the Container) constructs the judge from the
authorities the node declares, and a resolver without the canonical `run_store`
refuses the kind instead of building a judge that could not persist its eval
evidence.

`test_no_ungoverned_model_path.py` (+9, one parametrized ×3) is the
architecture-fitness proof: AST scans fail any provider SDK import or
raw-completion HTTP anywhere under `maistro_design`, positive controls pin
ModelChatEgress as the only model seam and DesignEngine's ADR-061 invariant,
and the Design Studio pages are scanned for model-host fetches with
DeckBuilder's pre-existing governed-chat caller recorded as a non-expandable
ratchet baseline. The same rules ship as `scripts/check-design-model-egress.py`
(wired into quality.yml beside the model-egress gate), so a raw explore/judge
chat completion fails CI even where the suite does not run.

Making the wave a production Graph node also moved the design kinds into the
canonical production registration universe, which the core graph guards
observe. `packages/maistro-core/tests/graph/nodes/test_idempotent_replay_conformance.py`
(+1) adds the `design.explore` conformance case the sweep demands of every
IDEMPOTENT kind: the coordinator authorizes the wave and emits the wave
envelope, and a replay under a fresh NodeRun produces the same envelope
without dispatching a model call. The sweep now loads the design registration
module itself, so the case set no longer depends on test collection order.

`packages/maistro-core/tests/graph/nodes/test_production_registration_universe.py`
(+1) keeps its guard and narrows it to what the guard was actually for: the
unreachable module `maistro_design.nodes` (`design.orchestrate`,
`design.consistency_eval`) stays unloaded, unreviewed and unregistered — the
reviewed `design-node` disposition still covers it. The blanket "no
`design.*` kind is production" assertion is replaced by the stronger, narrower
claim: the three governed wave kinds are production kinds attributed to their
own loaded registration modules, and the bare-import probe now proves that
loading the design package adds exactly the kinds the reconciled universe
attributes to it (the eleven creative kinds plus the wave kinds) instead of a
hard-coded count. The `packages/maistro-core/tests` count moves by +17 on this
branch, and every one of the seventeen is this change's: two new test
functions (one in each core guard file) plus the fifteen parametrized cases
the production-kind sweeps gained when `design.explore` / `design.thesis` /
`design.judge` joined the production registration universe —
`test_container_node_composition.py` (2 sweeps x 3 kinds = 6) and
`test_node_composition.py` (3 sweeps x 3 kinds = 9). `develop` itself is
consistent (16784 collected against 16784 expected), so there is no inherited
drift to disclaim. The shared baseline is not edited: the delta lives in this
note, which is where the ledger reads it from.
