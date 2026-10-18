# M8-M research note — multi-agent organization, delegation topology, and collective reasoning

Epic: #912. Initiative: #879. Milestone: M8. Status at this head: **no comparative
experiment has been run**; this note maps the epic's hypothesis space onto the real
canonical seams, records what is and is not evidenced today, and sets a terminal
disposition per direction. It adds no product code, no flag, and no second runtime.

## Research question

When does a team of specialized Agents outperform one capable Master Agent, and
which communication/delegation topology produces the best quality per unit of
cost and coordination overhead?

## Canonical seams (verified at this head)

Everything this epic could experiment on already exists as shipped, tested
machinery under one execution model, `Workspace/Project → Graph → Run → NodeRun
→ Attempt` (`packages/maistro-core/src/maistro/runs/admission.py` — work has
exactly one execution identity; direct submissions get a trivial one-node Graph,
and the kind is checked against the registry, fail-closed):

- **Master Agent (hub).** `orchestrator/master.py` is a compatibility API over
  canonical Graph execution — it translates planner waves into Graph structure
  and projects `Graph -> Run -> NodeRun -> Attempt` back onto WorkItems rather
  than maintaining a second execution lifecycle.
- **Peer delegation.** `maistro/a2a/` (ADR-058, Proposed): one delegation
  protocol behind `A2ABroker` with `DelegationBudget`/`DelegationRefused`,
  delegation modes, and guest-peer trust/audit. Phases 1–2 (export surface,
  budgets, local transport) are implemented; federated transport is Phase 3;
  `WorkerPool`/`TaskLifecycleManager` are explicitly experimental per ADR-058
  decision 2. Tests: `packages/maistro-core/tests/a2a/` (broker, budgets,
  delegation, guest peers, lifecycle, public surface),
  `packages/maistro-server/tests/api/test_a2a_api.py`.
- **Independent sampling then aggregation.** `orchestrator/waves/ensemble.py`
  (ADR-071, Proposed; ADR-052, Deprecated, is its lineage): parallel waves with
  isolated context, per-wave timeout, a `ResultComparator` that picks one best
  result, ADR-056 checkpoints for crash recovery. The Run-level fold is
  canonical and deterministic: `runs/aggregation.py` derives one parent Run
  status from the NodeRun frontier via `RUN_TERMINAL_PRECEDENCE` (#237).
  Tests: `packages/maistro-core/tests/orchestrator/waves/test_ensemble.py`.
- **Hierarchical delegation.** Graph `subgraph` node type
  (`graph/node_types.py`, `executor_strategy="subgraph"`);
  `graph/nodes/agent_delegate_remote.py` (pause while a peer session runs a
  subgraph; tests in `tests/graph/nodes/test_agent_delegate_remote*.py`);
  `graph/depth.py` root/orchestrator/leaf roles with a hard max-depth cap —
  `get_role`/`can_spawn` are wired into `graph/nodes/agent_synth_dag.py`, while
  `compute_subgraph_depths`/`validate_depth` are recorded unused
  (`quality/vulture-baseline.json`); `orchestrator/hierarchy.py` (ADR-101,
  Proposed) for spawning across *foreign* harnesses with waves
  (`spawn_wave_across_harnesses`) and ordered fallback
  (`spawn_with_fallback`). Tests: `tests/graph/test_depth.py`,
  `tests/orchestrator/test_hierarchy.py`.
- **Dynamic specialist selection.** `VariantSelector` Thompson sampling over
  prompt variants (ADR-007, Accepted; ≥20 samples before selection, success
  threshold 7.0) behind the single spawn funnel (`agents/spawner/spawner.py`,
  ADR-009, Accepted); the meta hyperagent matches capabilities to the **first
  roster-order agent that declares them** with no hardcoded names (#221,
  `agents/hyperagent.py`).
- **Adversarial review / debate.** `agents/tournament.py`: head-to-head Elo
  with judge scoring, promotion threshold 50, minimum 10 battles; the RSI/evolve
  packages reuse the tournament shape for genome tournaments (ADR-070126-6386,
  Proposed). Tests: `tests/agents/test_tournament.py`.
- **Communication compression / shared context.** `graph/compaction.py`
  `ContextCompactor` (compact above 8000 estimated tokens, keep ≤5 summaries);
  `collaboration/session_collab.py` (graded co-ownership, presence, bounded
  live event stream). Tests: `tests/graph/test_compaction.py`.
- **Stopping rules / when not to delegate.** `MAX_NODE_VISITS = 8` in
  `graph/durable_runs/executor.py`; ADR-100126-b118 (Proposed) makes declared
  DAG budgets canonical (`max_cycles` frontier-wave budget clamped 1–20
  fail-closed, per-node `timeout_s` clamped 1–600 s as the Attempt deadline);
  `security/dag_shape/` judges synthesized DAG *width* proportionality
  (advisory, degrades explicitly) while recursion *depth* stays the hard cap;
  `security/delegability/evaluator.py` translates Sentinel authorization into a
  planning-shaped answer (execute / what would unlock more).

## Contract for any experiment under this epic

One canonical Goal ownership/control model, canonical delegation/Graph/Run
semantics, and no parallel swarm runtime. Measured dimensions per run: task
success, cost, latency, coordination overhead, correlated failure, diversity,
inspectability, recovery. Baseline for every comparison: **the same workload on
one capable agent through the single spawn funnel** (`Spawner.spawn`, ADR-009),
same model tier and prompt budget. A GRADUATE result does not authorize adoption
inside M8; it routes to the Agent/orchestrator/delegation owners as a normal
implementation issue.

## Record

No experiment has been run. What exists today is *machinery with tests*, not
*evidence of superiority*: every seam above demonstrates safety, liveness, or
recovery properties (budgets, depth caps, deterministic aggregation, crash
checkpoints), and none of them has been measured against a single-agent
baseline on a representative MAIstro workload, which is what this epic's
research question requires. Initiative guardrail 5 ("no benchmark-only
adoption") and guardrail 3 ("negative findings are first-class") therefore both
resolve the same way at this head: nothing is evidenced, nothing graduates.

Per-direction hypothesis/baseline/metrics/cost/trust framing is inherited from
the Contract section above; a future leaf only needs to name its seam, its
workload, and its numbers.

## Dispositions

| Direction (leaf of #912) | Seam | Disposition |
|---|---|---|
| Specialist team size and composition | Recipes/personas through the single spawn funnel | **WATCH** — composition knobs exist (ADR-060 persona-as-seed, Proposed); no size/composition benchmark |
| Hub-and-spoke vs peer/debate topology | `orchestrator/master.py` vs `a2a/` broker | **WATCH** — both topologies shipped (ADR-058 Proposed); no head-to-head quality/cost comparison |
| Independent sampling then aggregation | `orchestrator/waves/ensemble.py` + `runs/aggregation.py` | **WATCH** — ensemble + deterministic fold shipped and tested; never measured against single-agent baseline |
| Adversarial review/debate | `agents/tournament.py` Elo; evolve genome tournaments | **WATCH** — selection substrate exists (ADR-070126-6386 Proposed); no evidence debate improves task quality |
| Hierarchical delegation | subgraph node type, `graph/depth.py`, `agent_delegate_remote`, `orchestrator/hierarchy.py` (ADR-101 Proposed) | **WATCH** — depth cap wired only via synth-DAG; `compute_subgraph_depths`/`validate_depth` unused; no depth-vs-quality evidence |
| Dynamic specialist selection | `VariantSelector` (ADR-007 Accepted), roster-first matching (#221) | **WATCH** — per-variant Thompson sampling shipped; no team-level selection evidence |
| Communication compression / shared context | `graph/compaction.py`, `collaboration/session_collab.py` | **WATCH** — compactor defaults unvalidated against multi-agent workloads |
| Redundant vs complementary roles | ensemble `ResultComparator` (redundant) vs DAG multi-node (complementary) | **WATCH** — no diversity or correlated-failure measurement exists |
| Delegation stopping rules / when not to delegate | `MAX_NODE_VISITS`, ADR-100126-b118 budgets, `dag_shape`, `delegability` | **WATCH** — the most developed direction: safety controls shipped; the *quality* question (when delegating helps) is unmeasured |

WATCH, not REJECT: the seams are real and tested, so an experiment can be run
without new product scaffolding; WATCH, not INCUBATE: nothing here outperformed
anything yet, and INCUBATE would imply a kept prototype, which does not exist.
The stopping-rules family is the most likely first leaf because its controls
and instrumentation (budgets, depth caps, run aggregation) already ship.

## Exit

Every direction is dispositioned. Any future GRADUATE routes to the
Agent/orchestrator/delegation owners as canonical-implementation work under the
earliest owning milestone — never as a parallel swarm runtime, and never by
promoting research code to a second execution authority alongside `Goal ->
Graph -> Run -> NodeRun -> Attempt`.
