"""Approval gate decision core (SPEC-253 / ADR-051)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from maistro.tools.approval.types import Impact, Threshold


@dataclass(frozen=True)
class PlanApprovalState:
    task_id: str
    approved_calls: frozenset[str]
    approved_at: datetime | None


def needs_plan_approval(state: PlanApprovalState | None) -> bool:
    return state is None


def is_declared(state: PlanApprovalState, call: str) -> bool:
    return call in state.approved_calls


def thresholds_tripped(
    impacts: tuple[Impact, ...], thresholds: tuple[Threshold, ...]
) -> tuple[str, ...]:
    threshold_map = {t.dimension: t.gt for t in thresholds}
    return tuple(
        impact.dimension
        for impact in impacts
        if impact.dimension in threshold_map and impact.value > threshold_map[impact.dimension]
    )


def needs_escalation(
    call: str,
    impacts: tuple[Impact, ...],
    thresholds: tuple[Threshold, ...],
    *,
    plan_state: PlanApprovalState | None = None,
) -> bool:
    if plan_state is None or not is_declared(plan_state, call):
        return True
    return bool(thresholds_tripped(impacts, thresholds))


def collapse_window(
    events: tuple[tuple[str, tuple[str, ...]], ...],
    *,
    window_seconds: float = 0.0,
) -> tuple[tuple[str, ...], ...]:
    if not events:
        return ()

    groups: list[list[tuple[str, ...]]] = []
    group_start: datetime | None = None
    for timestamp_str, dims in events:
        timestamp = datetime.fromisoformat(timestamp_str)
        if group_start is None or (timestamp - group_start).total_seconds() > window_seconds:
            groups.append([])
            group_start = timestamp
        groups[-1].append(dims)

    collapsed: list[tuple[str, ...]] = []
    for group in groups:
        seen: list[str] = []
        for dims in group:
            for dim in dims:
                if dim not in seen:
                    seen.append(dim)
        collapsed.append(tuple(seen))
    return tuple(collapsed)
