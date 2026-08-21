---
id: ADR-071
title: "General Task Planner & Orchestration — SuperPlanner waves as a Repertoire ensemble"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-05-30
substrate:
  - maistro-engine#ADR-070
  - maistro-engine#ADR-052
  - maistro-engine#ADR-062
implements: []
related:
  - maistro-engine#ADR-017
  - maistro-engine#ADR-038
  - maistro-engine#ADR-050
  - maistro-engine#ADR-054
  - maistro-engine#ADR-056
  - maistro-engine#ADR-058
  - maistro-engine#ADR-068
  - maistro-engine#ADR-069
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
---

# ADR-071: General Task Planner & Orchestration

**Status:** Proposed
**Date:** 2026-05-30
**Applies:** ADR-070 (the Repertoire pattern) to general task planning.

---

## Context

`orchestrator/planner.py::SuperPlanner` ("decomposes a high-level goal into parallel-safe work
waves", `plan() -> list[list[WorkItem]]`) and `orchestrator/master.py::MasterOrchestrator` (executes
the waves) exist in code but have **no ADR**. ADR-062 *executes* a graph and ADR-052 *runs* waves,
but nothing specifies **who builds the plan, how execution stays robust, or how planning improves**.
Several gap-analysis findings live in exactly this hole: no planner ADR, no cancellation/deadline
propagation, no deadlock/starvation/backpressure handling, deferred speculative execution.

This is distinct from the **Builders** pipeline (Frank→Mason→Auditor, spec→tests→code→audit), which
is the *code-specific self-improvement* DAG. This ADR is the **general** task planner/orchestrator
for any goal; it borrows Builders' best trait (Quartermaster's match-and-adapt reuse) via the
Repertoire pattern rather than reusing its engineering-specific stages.

## Decision

The general planner/orchestrator is the **Repertoire pattern (ADR-070) applied to task planning**,
realized as an ensemble. The four Repertoire movements map onto five mechanisms (each lifts a
proven idea — SuperPlanner/MasterOrchestrator/Quartermaster + Google distributed-systems ideas):

### Perform — template match (Quartermaster-style)
Match a **verified plan template** for the goal's class and adapt it (the Repertoire *recall*).
Most recurring goals are planned this way: cheap, fast, auditable. Templates are signed (ADR-069).

### Improvise — MCTS + Tree-of-Thoughts (on miss / high-stakes)
On a template miss or a high-stakes goal, **search over decompositions** instead of greedily
emitting one plan: expand a tree of candidate decompositions (Tree-of-Thoughts), run **cheap
rollouts** (dry-run / cheap-model cost+success estimate), **back up a value estimate**
(AlphaZero-style), and commit the best. The value function is **learned from ADR-017 outcomes +
maistro-evolve**; the nearest Repertoire templates seed the search as priors (the policy prior).
Plan scoring is **interpretable, glass-box** (per ADR-089/ADR-068): an explicit weighted function
over cost / success-estimate / risk / reuse-distance, whose weights are editable config (ADR-078)
and auditable — not a black-box value net. "Learned" means those weights and the rollout estimates
are tuned from outcomes, not that the score is opaque.

### Run — Pregel supersteps under a Borg-style reconciler
SuperPlanner emits **parallel-safe waves** (ADR-052); MasterOrchestrator executes them as
**BSP supersteps**: each wave runs in parallel, hits a **barrier**, and `WorkItem`s exchange results
as messages at the boundary. Each superstep is a **checkpoint** (free synergy with ADR-056 crash
recovery — resume at the last superstep). Execution is a **reconciliation control loop** (Borg/K8s):
the plan declares a **desired-state** (goal success conditions) and the loop drives actual→desired,
**re-planning on drift/failure (self-healing)**, with:
- **Priority + preemption** — urgent work preempts background (closes the starvation/fairness gap);
- **Budgets** — per-task cost/token/wall-clock/step ceilings (ADR-054) and SRE-style error budgets
  (ADR-038) decide when to stop retrying / degrade (closes backpressure);
- **Deadlines + cooperative cancellation** — every wave/`WorkItem`/delegation carries a deadline;
  cancellation propagates to sub-agents (ADR-058) and fires compensators (ADR-050); deadlock/
  livelock is broken by deadline expiry rather than a bespoke cycle detector (closes
  cancellation/timeout/deadlock);
- **Speculative execution + backup tasks** — speculatively start the likely-next waves before
  upstream gates fully resolve, and dispatch a straggler `WorkItem` to a second worker
  (first-to-finish wins) for tail latency. Safe **only because** rollback is cheap (ADR-049 shadow
  git, ADR-050 compensators). This is the speculative-wave execution ADR-052 deferred.

### Rehearse — validate before run, verify after
The plan is **validated before execution**: cycle-free DAG (ADR-062), fits the budget (ADR-054),
and every `WorkItem`/delegation is within the requesting principal's authority (ADR-068; agents hold
a subset of their caller's authority, ADR-058). Outcomes are **verified against the goal's success
conditions** before the goal is declared done.

### Compose — distill successful plans
A verified successful plan is **distilled into a new signed Repertoire template** (ADR-069), so the
next similar goal hits the cheap *Perform* path; `maistro-evolve` improves templates over time.

### Authority envelope
Every wave, `WorkItem`, and delegation runs **inside the ADR-068 authorization envelope** — Sentinel
classifies/gates and Warden risk-scans — so no planned step can escalate privilege or bypass
approval/budget.

## Interface (sketch)

```python
class SuperPlanner:                                   # orchestrator/planner.py (formalized)
    def plan(self, goal: Goal) -> list[list[WorkItem]]: ...   # goal → parallel-safe waves
    # internally: Repertoire.recall(template) → adapt;  on miss → improvise(MCTS/ToT)

class MasterOrchestrator:                             # orchestrator/master.py (formalized)
    async def execute(self, waves: list[list[WorkItem]], *, budget: Budget) -> OrchestratorResult: ...
    # BSP supersteps + reconcile loop: priority/preemption, deadlines, speculative exec, self-heal

class ReconcileLoop(Protocol):
    def desired(self) -> SuccessConditions: ...
    async def step(self, actual: State) -> list[Action]: ...   # drive actual → desired
```

## Acceptance criteria

- [ ] A recurring goal class with a matching template is planned via *Perform* (no search) —
      property test: search (`improvise`) is not invoked on a template hit.
- [ ] A novel/high-stakes goal triggers *Improvise* (MCTS/ToT) seeded by nearest templates.
- [ ] Plans are validated before execution: cyclic plan, over-budget plan, or
      authority-exceeding `WorkItem` is rejected pre-run.
- [ ] Waves execute as supersteps with a checkpoint per barrier; a crash resumes at the last
      superstep (ADR-056).
- [ ] A deadline expiry cancels the wave cooperatively, propagates to sub-agents (ADR-058), and
      fires compensators (ADR-050); no orphaned in-flight work.
- [ ] Priority preemption: an urgent task preempts a background task under contention.
- [ ] Over-budget (ADR-054) halts/degrades per the reconciler; not bypassable by speculation.
- [ ] A verified successful plan composes a signed Repertoire template (ADR-069/ADR-070).
- [ ] Every `WorkItem`/delegation passes the ADR-068 `authorize()` envelope.

## Consequences

- The orchestration "white space" (no planner ADR; cancellation/deadlock/backpressure;
  speculative execution) is closed in one coherent design.
- SuperPlanner/MasterOrchestrator become the **reference instance** of the Repertoire pattern.
- The Builders pipeline (ADR-032 + `builders/`) remains the *engineering-specific* sibling; a
  separate ADR can formalize it and note it as another Repertoire instance.

## Out of scope

- The learned value-function / rollout-model training mechanics — follow-up SPEC.
- The Builders code-pipeline stage machine (Frank/Mason/Auditor) — its own ADR.
- Multi-conductor (HA) orchestration — single-conductor v0 (per ADR-056/046).
- Per-domain template authoring — product/recipe concern.
