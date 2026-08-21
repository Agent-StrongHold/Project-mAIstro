---
id: SPEC-062126-a05f
title: "SuperPlanner + MasterOrchestrator pre-execution validation gate (ADR-071)"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-21
substrate:
  - maistro-engine#ADR-062
  - maistro-engine#ADR-068
  - maistro-engine#ADR-070
related:
  - maistro-engine#SPEC-258
  - maistro-engine#ADR-054
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/orchestrator/test_plan_validation.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-062126-a05f: SuperPlanner + MasterOrchestrator pre-execution validation gate

## Context

ADR-071 names `SuperPlanner` (plan-builder) and `MasterOrchestrator` (plan-executor) as a single
paired system — the *Run* and *Rehearse* movements of the Repertoire pattern (ADR-070) applied to
general task planning. They are deliberately a DAG: `SubsystemDef.depends_on` are edges,
`_topological_sort()` (`orchestrator/planner.py`) layers the DAG into topologically-ordered "waves"
(parallel-safe sets), and already raises on a dependency cycle. `MasterOrchestrator` enforces those
edges at runtime via `_check_dependencies()`.

This is a **different DAG domain** from `maistro.graph` (ADR-062): that module validates
Hive-Conductor-style workflow DAGs over a registered node-kind catalog (`jira_poll`,
`llm_summarize`, `human_approve_draft`, ...) with per-edge schema compatibility checks
(`dag_validator.py`). SuperPlanner/MasterOrchestrator's nodes are `WorkItem`s dispatched to builder
agent roles (frank/mason/auditor), not Hive node kinds — there is no node-kind registry or
input/output schema to check. **They are not the same DAG executor and should not be merged** — but
`maistro.graph.dag_validator`'s *shape* (a `ValidationReport` of structured `ValidationFinding`s,
rather than a bare raised exception) is worth reusing as a pattern, because ADR-071's acceptance
criteria require rejecting an invalid plan (cyclic, over-budget, or authority-exceeding) **before**
execution starts, with actionable, structured findings — not just a stack trace.

This SPEC scopes ADR-071's *Rehearse* movement only: validate a plan before `MasterOrchestrator`
executes it. It does not implement *Improvise* (MCTS/ToT plan search), *Compose* (signed template
distillation via SPEC-258's `Repertoire`), preemption, deadlines, or speculative execution — those
remain open ADR-071 follow-ups (see Non-goals).

## Goals

- Add `orchestrator/validation.py`: `PlanValidationFinding` (frozen dataclass: `code: str`,
  `severity: Literal["error", "warning"]`, `message: str`, `task_id: str | None = None`) and
  `PlanValidationReport` (`findings: tuple[PlanValidationFinding, ...]`, `is_valid: bool` property
  — `True` iff no `error`-severity finding) — same shape as `graph.dag_validator.ValidationReport`,
  reused as a pattern (not imported — different domain, see Context) so callers get one consistent
  validation-report shape across both DAG systems in the codebase.
- `validate_plan(waves: list[list[WorkItem]], *, max_total_cost: float | None = None, principal:
  Principal | None = None, sentinel: Sentinel | None = None) -> PlanValidationReport`:
  - **Cycle check**: reuses `_topological_sort`'s existing depth computation rather than
    duplicating it; a `ValueError` from a cycle becomes a `code="cycle"` error finding instead of
    propagating raw.
  - **Budget check** (ADR-054): if `max_total_cost` is given, sums each `WorkItem.metadata.get(
    "estimated_cost", 0.0)` across all waves; exceeding the ceiling is a `code="over_budget"` error
    finding. No cost-estimation model is added here — callers populate `estimated_cost` themselves.
  - **Authority check** (ADR-068): if `principal` and `sentinel` are given, calls
    `sentinel.authorize(item.task_id, principal, ...)` for every `WorkItem`; any `authorized=False`
    or `tier == Tier.BLOCKED` becomes a `code="authority_exceeded"` error finding naming the task.
- `MasterOrchestrator.load_plan()` gains an optional pre-flight: a plan whose `validate_plan()`
  report `is_valid is False` must not silently execute — callers (e.g. `SuperPlanner.
  build_orchestrator`) call `validate_plan` first and raise/refuse before `execute()`, per ADR-071's
  "validated before execution" acceptance criterion.

## Non-goals

- *Improvise* (MCTS/Tree-of-Thoughts plan search on a template miss) — separate follow-up SPEC;
  needs a learned value function this SPEC does not build.
- *Compose* (distilling a verified plan into a signed Repertoire template via SPEC-258) — follow-up
  once a concrete `Repertoire[Goal, Plan, PlanTemplate]` wrapper is written around SPEC-258's core.
- Deadlines, cooperative cancellation, priority preemption, speculative execution, BSP-superstep
  checkpointing — ADR-071's *Run* movement beyond what `MasterOrchestrator` already does
  (sequential wave execution); all deferred, tracked by ADR-071 directly.
- Reconciling or merging with `maistro.graph`'s DAG executor — established in Context as a
  deliberate non-goal; they serve different domains (Hive workflow nodes vs. builder `WorkItem`s).
- A cost-estimation model for `estimated_cost` — populating that metadata field is the caller's
  concern (e.g. a router/scoring-formula estimate), not this SPEC's.

## Decision

```python
# orchestrator/validation.py
@dataclass(frozen=True)
class PlanValidationFinding:
    code: Literal["cycle", "over_budget", "authority_exceeded"]
    severity: Literal["error", "warning"]
    message: str
    task_id: str | None = None

@dataclass(frozen=True)
class PlanValidationReport:
    findings: tuple[PlanValidationFinding, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)

async def validate_plan(
    waves: list[list[WorkItem]],
    *,
    max_total_cost: float | None = None,
    principal: Principal | None = None,
    sentinel: Sentinel | None = None,
) -> PlanValidationReport: ...
```

`validate_plan` is async (the authority check calls `Sentinel.authorize`, which is async) but the
cycle and budget checks are pure/sync internally — no `await` needed unless `sentinel` is supplied.

## Acceptance criteria

- [ ] A cyclic dependency graph (`A depends_on B`, `B depends_on A`) produces a `code="cycle"` error
      finding; `validate_plan` never raises — cycles surface as findings, not exceptions.
- [ ] A plan whose total `estimated_cost` exceeds `max_total_cost` produces a `code="over_budget"`
      error finding naming no specific task (plan-level).
- [ ] A plan under budget with `max_total_cost=None` never produces an `over_budget` finding
      (budget check is opt-in).
- [ ] A `WorkItem` whose principal lacks authorization (via injected `Sentinel`) produces a
      `code="authority_exceeded"` finding naming that `task_id`; other items are still checked
      (the report aggregates all findings, it does not short-circuit on the first authority
      failure).
- [ ] A fully valid plan (acyclic, under budget, all items authorized) returns
      `PlanValidationReport(findings=())` with `is_valid is True`.
- [ ] `MasterOrchestrator` building from `SuperPlanner.build_orchestrator()` refuses to execute a
      plan whose `validate_plan()` report `is_valid is False`.

## Testing

- `packages/maistro-core/tests/orchestrator/test_plan_validation.py` (new) — cycle detection,
  budget ceiling (under/over/unset), authority check (single + multiple failing items, aggregation
  not short-circuit), fully-valid plan, and the `build_orchestrator` refusal-to-execute regression.

## Open questions

- Whether `validate_plan` should also check `agent_role` has a registered handler before execution
  (today `MasterOrchestrator._execute_item` fails late, per-item, with `FAILED` status) — left for
  a follow-up since it's a runtime-registration concern, not a structural plan-validity one.

## References

- `packages/maistro-core/src/maistro/orchestrator/planner.py` (`_topological_sort`, cycle
  detection precedent)
- `packages/maistro-core/src/maistro/graph/dag_validator.py` (`ValidationReport` shape precedent —
  not imported, different domain)
- [ADR-071: General Task Planner & Orchestration](../adr/ADR-071-task-planner-orchestration.md)
- [ADR-068: Unified Authorization & Elevation](../adr/ADR-068-unified-authorization-and-elevation.md)
- [SPEC-258: The Repertoire Pattern](SPEC-258-repertoire-pattern-core.md)
