---
id: SPEC-253
title: "Tool approval gates — plan-level/escalation decision core (ADR-051)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#SPEC-252
  - maistro-engine#ADR-037
related:
  - maistro-engine#ADR-028
  - maistro-engine#ADR-054
  - maistro-engine#ADR-056
  - maistro-engine#ADR-068
implements:
  - maistro-engine#ADR-051
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/tools/test_approval_gate.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-253: Tool approval gates — plan-level/escalation decision core

> **Convergence note (2026-08-19).** This spec is marked `Implemented` over
> code with no path from any process entry point — see
> [#363](https://github.com/Agent-StrongHold/maistro-engine/issues/363). It
> tracks ADR-051, whose status is knowingly held pending the
> boundary-enforcement ADR.
>
> The status is left unchanged because the spec lifecycle has no way to
> express this. From `Implemented` a spec may only become `Superseded`, which
> requires a `superseded-by`, and no successor document exists. There is no
> `Deprecated` state for specs as there is for ADRs. Correcting this needs
> either the successor spec or a lifecycle change, so the note carries the
> truth in the meantime.


## Context

ADR-051 requires substrate to gate `irreversible` tool calls (per SPEC-252's taxonomy) through
plan-level preview approval and per-call impact-threshold escalation, collapsing repeated
threshold trips in the same window into one prompt. Nothing implementing this exists —
`security/sentinel` enforces allow/deny policy but has no human-approval surface. This SPEC
scopes the pure decision core: given a declared plan and a stream of tool calls with impact
estimates, decide which calls need a fresh `ApprovalGate.request_*` call versus which are already
covered by a standing plan approval or a collapsed-window threshold trip. Learned trust (ADR-051
layer 3) is explicitly out of scope here — it is superseded by ADR-068's RLPHD predictor
(SPEC-248), which is the correct home for that logic; this SPEC only builds layers 1 and 2.

## Goals

- Add `maistro/tools/approval/types.py`: `ApprovalTarget` (`Literal["plan", "call"]`),
  `ApprovalOutcome` (`Literal["approved", "denied", "timeout"]`), `ApprovalDecision` (frozen
  dataclass: `task_id: str`, `target: ApprovalTarget`, `outcome: ApprovalOutcome`,
  `latency_ms: int`, `decided_by: str`), `Impact` (frozen dataclass: `dimension: str`,
  `value: float`), `Threshold` (frozen dataclass: `dimension: str`, `gt: float`).
- Add `maistro/tools/approval/protocols.py`: `ApprovalGate` Protocol —
  `async def request_plan_approval(self, task_id: str, irreversible_calls: tuple[str, ...]) ->
  ApprovalDecision`, `async def request_escalation(self, task_id: str, call: str, impacts:
  tuple[Impact, ...]) -> ApprovalDecision`.
- Add `maistro/tools/approval/gate.py`: pure functions operating on an in-memory
  `PlanApprovalState` (frozen dataclass: `task_id: str`, `approved_calls: frozenset[str]`,
  `approved_at: datetime | None`):
  - `needs_plan_approval(state: PlanApprovalState | None) -> bool` — `True` iff no approval has
    been recorded yet for the task.
  - `is_declared(state: PlanApprovalState, call: str) -> bool` — whether `call` was part of the
    originally-approved plan bundle; an irreversible call appearing mid-task that was *not*
    declared always needs its own fresh gate per ADR-051's plan-level-preview rule, regardless of
    plan approval status.
  - `thresholds_tripped(impacts: tuple[Impact, ...], thresholds: tuple[Threshold, ...]) ->
    tuple[str, ...]` — names of dimensions whose impact value exceeds (`>`) the matching
    threshold's `gt`; dimensions with no configured threshold never trip.
  - `needs_escalation(call: str, impacts: tuple[Impact, ...], thresholds: tuple[Threshold, ...],
    *, plan_state: PlanApprovalState | None) -> bool` — `True` if the call is undeclared
    (`not is_declared(...)`, including the case `plan_state is None`) OR any threshold trips;
    `False` if the call was declared in an approved plan and no threshold trips.
  - `collapse_window(events: tuple[tuple[str, tuple[str, ...]], ...], *, window_seconds: float =
    0.0) -> tuple[tuple[str, ...], ...]` — given a sequence of `(timestamp_iso, tripped_dims)`
    escalation events, groups events whose timestamps fall within `window_seconds` of each other
    into a single collapsed tuple of tripped dimensions (union, de-duplicated, order-preserving),
    so callers raise one prompt per window instead of one per threshold per call.

## Non-goals

- A concrete `ApprovalGate` implementation (notification channel — chat/push/queue) — ADR-051
  explicitly defers channel choice to product level; this SPEC ships the Protocol only.
- Learned trust / promotion store (ADR-051 layer 3) — explicitly superseded by ADR-068's RLPHD
  predictor (SPEC-248); no counter-based trust logic is added here.
- Non-blocking parallel execution of the agent's plan DAG while a gate is pending — that's a
  task-runner/orchestrator scheduling concern (ADR-052/056), not a property of the decision
  functions themselves; this SPEC's functions are synchronous pure decisions the runner calls.
- `tool.compensator_invoked`/bubble-up integration with ADR-056 crash recovery's "retry/skip/
  mark-done" reuse of this gate surface — follow-up once ADR-056 lands.
- Recipe YAML parsing of `approval.escalation_thresholds`/`learned_trust` — `Threshold` tuples
  are constructed directly by the caller in this SPEC; recipe-overlay parsing (ADR-053) is a
  separate concern.
- `approval.gate.{raised,answered}` events and `approval.wait` span (ADR-037 wiring) — follow-up
  once an event-bus/tracer call site invokes this module.

## Decision

```python
# maistro/tools/approval/types.py
ApprovalTarget = Literal["plan", "call"]
ApprovalOutcome = Literal["approved", "denied", "timeout"]

@dataclass(frozen=True)
class ApprovalDecision:
    task_id: str
    target: ApprovalTarget
    outcome: ApprovalOutcome
    latency_ms: int
    decided_by: str

@dataclass(frozen=True)
class Impact:
    dimension: str
    value: float

@dataclass(frozen=True)
class Threshold:
    dimension: str
    gt: float

# maistro/tools/approval/gate.py
@dataclass(frozen=True)
class PlanApprovalState:
    task_id: str
    approved_calls: frozenset[str]
    approved_at: datetime | None

def needs_plan_approval(state: PlanApprovalState | None) -> bool: ...
def is_declared(state: PlanApprovalState, call: str) -> bool: ...
def thresholds_tripped(impacts, thresholds) -> tuple[str, ...]: ...
def needs_escalation(call, impacts, thresholds, *, plan_state=None) -> bool: ...
def collapse_window(events, *, window_seconds=0.0) -> tuple[tuple[str, ...], ...]: ...
```

## Acceptance criteria

- [x] `needs_plan_approval(None)` is `True`; with a recorded `PlanApprovalState` it is `False`.
- [x] A task with zero irreversible calls never calls `needs_escalation` (caller-side — the
      runner simply has no calls to check; no test needed beyond the functions being total).
- [x] An undeclared call (`is_declared` is `False`) always triggers `needs_escalation`, even with
      zero impacts and zero thresholds.
- [x] A declared call with all impacts below their thresholds does not trigger `needs_escalation`.
- [x] A declared call with one impact dimension exceeding its threshold triggers
      `needs_escalation`, and `thresholds_tripped` names exactly that dimension.
- [x] Multiple dimensions tripping simultaneously are all named by `thresholds_tripped` (order
      matches input `impacts` order).
- [x] `collapse_window` groups two escalation events within `window_seconds` of each other into
      one collapsed tuple containing the union of both events' tripped dimensions; events farther
      apart than `window_seconds` remain separate groups.
- [x] Property test (Hypothesis): for any threshold list and impact list, `thresholds_tripped`
      only ever names dimensions present in both `impacts` and `thresholds` whose value strictly
      exceeds `gt` — never names a dimension with no configured threshold.

## Testing

- `packages/maistro-core/tests/tools/test_approval_gate.py` (new) — plan-approval state checks,
  declared/undeclared escalation matrix, threshold-trip naming, window-collapse grouping, and the
  Hypothesis property test above.

## Open questions

- Whether `collapse_window` should live here or in `maistro.events` as a general debounce utility
  — kept local to this module for now since ADR-051 is its only caller; can be promoted later
  without changing its signature.

## References

- [ADR-051: Tool approval gates](../adr/ADR-051-tool-approval-gates.md)
- [ADR-050: Tool reversibility taxonomy](../adr/ADR-050-tool-reversibility-taxonomy.md) (SPEC-252)
- [SPEC-248: RLPHD predictive approval](SPEC-248-rlphd-predictive-approval.md)
