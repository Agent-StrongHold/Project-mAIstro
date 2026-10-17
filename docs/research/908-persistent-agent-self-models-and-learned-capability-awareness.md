# M8-I research plan — persistent Agent self-models and learned capability awareness

Epic: #908. Initiative: #879.

## Hypothesis

A persistent Workspace Master Agent that maintains an evidence-grounded model
of its own capabilities, failure modes, specialists, tools, and successful
strategies — held separately from Persona and from user/project memory — can
improve planning and delegation over an agent whose self-knowledge is only
implicit in its prompts. The null hypothesis the epic guards against: any
measured improvement whose mechanism requires the self-model to silently
redefine Persona, authorization, Goal truth, or memory ownership, or whose
"capabilities" are self-asserted claims that no Run evidence can check.

## The contract, operationalized (guardrails mapped to shipped seams)

The issue's contract sentence — "Self-model facts must derive from inspectable
evidence and may not silently redefine Persona, authorization, Goal truth, or
memory ownership" — is already half-built in the shipped tree:

| Contract clause | Shipped guardrail seam |
|---|---|
| Facts derive from inspectable evidence | Producer provenance (#709): `Learning`/`Outcome`/eval-workspace rows carry `run_id`/`node_run_id`/`attempt_id` from the ambient execution context; `eval_workspace` snapshots carry the same triple (`packages/maistro-core/src/maistro/eval_workspace/model.py`). The `OutcomeEvidenceGauntlet` refuses knowledge with no producer Run (`packages/maistro-core/src/maistro/memory/learnings/gauntlet.py`). |
| May not redefine Persona | Persona is the single live taste/style/purpose context for a Workspace — one per Workspace (`packages/maistro-core/src/maistro/personas/store.py`, ADR-060, ADR-081226-e626). A self-model is not a second Persona and must not write `persona_hints` without the user-model's revision path. |
| May not redefine authorization | ADR-057 / SPEC-249: every memory mutation passes `require_write_authority` at the store boundary; undeclared mode fails closed and the decision reads only mode + actor + block tag, never content (`packages/maistro-core/src/maistro/memory/exposure.py`). |
| May not redefine Goal truth | Self-model code may only read the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` ontology (e.g. `Run.success_rate()`, `packages/maistro-core/src/maistro/graph/run.py`); nothing in a self-model may write Goals, Runs, or NodeRuns. |
| May not redefine memory ownership | Scope filtering is one rule compiled twice (`maistro.memory.scopes`, ADR-013); promotion into the user model refuses cross-user self-consent (`CrossUserPromotionError` in `maistro.memory.user_model.promotion`, SPEC-242 consent) and tombstoned lineages stay dead. |
| Safe self-writes | ADR-070426-9f47 (Proposed) is the autonoetic self-model threat model: its audit found the source design's self-write path unwired to Warden (ADR-072/073) and defines guardrail invariants that must land before any self-model persistence. |

## Canonical seams (verified against the shipped tree at head 31d891a56)

The issue's eight candidate directions, each with status **exists** /
**partial** / **absent**, its seam, and its leaf question. Every leaf ends
GRADUATE / INCUBATE / REJECT / WATCH.

- **A. Empirical capability estimates by task class — partial.**
  `InMemoryOutcomeStore.get_task_completion_rate(task_type=...)` computes an
  empirical completion rate per task class from recorded `Outcome` rows, and
  `get_experience_context` renders failures into future prompts
  (`packages/maistro-core/src/maistro/memory/outcomes.py`). What does not
  exist is a per-`(agent, capability, intent_class)` profile: SPEC-278 and
  ADR-070426-c4b2 are both Proposed, and `maistro.capabilities.profile` does
  not exist anywhere in `packages/` (probe P8). Leaf question: do per-class
  empirical rates measurably improve self-execute/delegate/decline decisions
  over the no-profile baseline, without starving cold-start task classes?
  Baseline: completion-rate-blind routing. Metric: delegation precision/recall
  at matched Run budget.
- **B. Specialist/tool success-rate learning — partial.** `VariantSelector`
  already learns per-variant success rates by Thompson sampling over scored
  spawn outcomes (ADR-007,
  `packages/maistro-core/src/maistro/agents/spawner/variant_selector.py`);
  the learnings gauntlet refuses promoted knowledge whose recorded success
  rate is below 0.6 with fewer than 3 uses; `Run.success_rate()` and
  `NodePerformanceMetrics` give per-role graph signals. No per-tool or
  per-specialist-Agent stats store exists. Leaf question: does a
  specialist-level success model beat variant-level and gauntlet-level
  signals alone on delegation quality, or is it a second bookkeeping of the
  same evidence?
- **C. Recurring failure-pattern detection — partial.** The outcome store
  renders "Recent Failure Patterns" (error type + model) and thumbs-down
  patterns into experience context; `Learning` carries
  `rca_category`/`rca_prevention` fields. Cross-Run clustering of failure
  patterns into named recurring modes is absent. Leaf question: do clustered
  failure modes (vs the flat recent-failures list) change planner behavior on
  the next similar Run?
- **D. Confidence calibration from historical Runs — absent.** Zero
  calibration modules in `maistro-core` src (probe P8c). What exists is
  adjacent, not this: `maistro_evolve.benchmarks.calibration` calibrates
  benchmark judges, and hive-conductor's `preference_calibration` is ADR-060
  Tier-2 Bradley-Terry preference residuals with no wired pairwise data
  source. Calibration of the agent's own "can I do X" confidence against
  realized Run outcomes has no implementation. The M8-E uncertainty family
  (#904) is the sibling to reuse — a self-model calibration leaf must share
  that harness rather than fork a second one. Leaf question: does calibrated
  capability confidence reduce both overconfident self-execution and
  underconfident delegation?
- **E. Learned Graph/strategy preferences — partial.** `GraphOptimizer`
  extracts `OptimizationSignal`s (per-role success rate, run count,
  bottleneck score) from traces and proposes prompt revisions
  (`packages/maistro-core/src/maistro/graph/optimizer.py`); `VariantSelector`
  prefers prompt variants empirically. No persistent strategy-preference
  memory ("for this intent class, Graph shape B won") exists across Runs.
  Leaf question: does a strategy preference store improve Graph selection
  beyond what graph-level optimization signals already capture, and can it
  avoid becoming a second, ungoverned promotion path (it must ride
  `maistro.governance.promotion`)?
- **F. Self-model decay and contradiction handling — exists (for learnings
  and the user model; not for a self-model).** The learnings lifecycle ships
  reinforcement, weakening, contradiction records with unresolved-pair
  review, hourly decay with a floor and retirement threshold, supersession
  and consolidation (`maistro.memory.learnings.lifecycle`, SPEC-283); the
  user model ships corrections and tombstones (P7). A self-model must reuse
  this dynamics engine, not invent a second one. Leaf question: are
  confidence + decay parameters transferable from institutional knowledge to
  self-facts, or do self-facts need different dynamics?
- **G. Safe write/update policies — exists.** ADR-057/SPEC-249 exposure-mode
  gate is enforced at every memory store boundary and fails closed
  (P1, P2); learnings and outcomes stores refuse undeclared modes before any
  state changes; gauntlet validation stands between learning and repertoire;
  promotion authority is centralized (`maistro.governance.promotion`,
  ADR-100126-a9c4). ADR-070426-9f47's guardrail invariants (G1–G18) are the
  remaining, unlanded piece specific to self-writes. Leaf question: which
  exposure mode is correct for a self-model store, and what does an
  agent-actor self-write even mean under ADR-057 when the writer and the
  subject are the same agent?
- **H. Separating self-model facts from Persona and Workspace memory —
  partial.** The separations that exist today are clean: Persona (one per
  Workspace, taste/style/purpose), user model (evidence-grounded per-user
  facts with revision/correction/tombstone lineage, cross-user promotion
  refused and audited — P7b), learnings (org-scoped institutional knowledge
  in system prompts, ADR-015). The self-model has no home:
  `maistro_turing.self_model` ships value types only (probe P8b — no repo,
  activation graph, or store), and `maistro.integrations.turing` emits
  self-model *events* to an external runtime over HTTP. Leaf question: does a
  persistent self-model earn its own store identity, or should its facts be
  modeled as a scope/kind inside the existing memory substrate (ADR-080
  tiers) so ownership stays in one place?

## Executed probe record

Head 31d891a561, 2026-10-05. Procedure: in-process probe, no network —
constructing the shipped stores/lifecycle/gauntlet/selector directly against
`packages/maistro-core/src` and asserting their behavior. All 15 checks
passed:

- undeclared exposure mode fails closed (`MemoryUndeclaredModeError`) and an
  agent write under `SYSTEM_MANAGED` is denied (`MemoryWriteDenied`) — P1, P2;
- `OutcomeEvidenceGauntlet` refuses a 1/4 success rate (`success_rate`) and a
  zero-evidence learning (`min_uses`, `producer`) — P3, P3b;
- the learnings lifecycle records an unresolved contradiction between two
  learnings, and a 48 h decay sweep decays both tracked learnings (standing
  confidence held at the 0.1 floor, nothing retired) — P4, P4b;
- `get_task_completion_rate` returns the empirical 2/3 rate for a task class
  from three recorded outcomes — P5;
- `VariantSelector` cold-starts round-robin (`a,b,a,b`) and then learns
  per-variant success rates (a=1.00, b=0.00) — P6, P6b;
- a user-model fact lineage tombstones cleanly, and promoting another user's
  memory raises `CrossUserPromotionError` and audits exactly one `denied`
  entry — P7, P7b;
- absence scans: `maistro.capabilities.profile` unresolvable (P8);
  `maistro_turing/self_model/` contains only `__init__.py` + `types.py`
  (P8b); zero files matching "calibrat" in `maistro-core` src (P8c);
  `WorkspacePersonaAlreadyExists` enforces one Persona per Workspace (P9).

## Comparison dimensions

Every leaf reports all six, per the epic contract: planning/delegation
improvement, calibration quality (vs declared priors, scored on realized Run
outcomes), stale-belief risk (decay/retirement behavior), poisoning risk
(Warden-scanned self-writes per ADR-070426-9f47, ADR-057 write authority,
gauntlet producer requirement), storage cost (rows per agent per capability
class), and explainability (evidence links plus the append-only revision,
conflict, and audit ledgers the shipped dynamics engine already produces).
Negative findings are first-class results (initiative guardrail 3).

## Reproducible artifacts

- The probe above is re-runnable in-process against `packages/maistro-core/src`
  at this head; it constructs only shipped classes and needs no services.
- SPEC-278 fixes the `CapabilityProfile` schema, EMA updater, and surfacing
  rule as acceptance criteria (Proposed) — the natural vehicle for families
  A/B/D if they graduate toward a profile store.
- ADR-070426-9f47's guardrail invariants are the mandatory preconditions for
  any self-model persistence (family H).
- The learnings lifecycle and gauntlet test suites
  (`packages/maistro-core/tests/memory/learnings/`) are the dynamics
  reference implementation any self-model store would reuse (family F).

## Record

This note reports no experiment. No self-model, capability profile, or
calibration method has been evidenced against a canonical MAIstro seam under
the epic's comparison dimensions. What exists today — outcome accounting,
variant-level success learning, learnings dynamics, the write-authority gate,
the user model — is prior substrate, not an M8-I result. This change adds no
product code, no flag, and no store.

## Disposition

WATCH at epic level. The eight leaf questions above end individually in
GRADUATE / INCUBATE / REJECT / WATCH; any GRADUATE result routes production
adoption to the persistent-Agent, memory, and governance owners — through
`maistro.governance.promotion` for anything promotion-shaped, and only after
ADR-070426-9f47's guardrails land for anything self-write-shaped. A self-model
can never authorize its own activation, and the epic is done when every leaf
carries a documented disposition.
