"""Pre-execution validation gate for SuperPlanner/MasterOrchestrator plans (SPEC-062126-a05f, ADR-071).

Validates a plan's waves before MasterOrchestrator executes them: cycle detection,
an opt-in budget ceiling, and an opt-in per-item authority check. Findings are
aggregated into a structured report rather than raised, mirroring the shape of
maistro.graph.dag_validator.ValidationReport (a different DAG domain — not reused
by import, see SPEC-062126-a05f Context).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from maistro.orchestrator.master import WorkItem

if TYPE_CHECKING:
    from maistro.security.sentinel.authz_types import Principal
    from maistro.security.sentinel.policy import Sentinel


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


def _check_cycles(waves: list[list[WorkItem]]) -> list[PlanValidationFinding]:
    items = [item for wave in waves for item in wave]
    item_map = {item.task_id: item for item in items}
    depths: dict[str, int] = {}
    visiting: set[str] = set()
    findings: list[PlanValidationFinding] = []

    def get_depth(tid: str) -> int:
        if tid in depths:
            return depths[tid]
        if tid in visiting:
            raise ValueError(f"Dependency cycle detected involving task {tid!r}")
        item = item_map.get(tid)
        if item is None or not item.depends_on:
            depths[tid] = 0
            return 0
        visiting.add(tid)
        try:
            max_dep_depth = max(get_depth(d) for d in item.depends_on)
        finally:
            visiting.discard(tid)
        depths[tid] = max_dep_depth + 1
        return depths[tid]

    for item in items:
        try:
            get_depth(item.task_id)
        except ValueError as exc:
            findings.append(
                PlanValidationFinding(
                    code="cycle",
                    severity="error",
                    message=str(exc),
                    task_id=item.task_id,
                )
            )
    return findings


def _check_budget(
    waves: list[list[WorkItem]], max_total_cost: float | None
) -> list[PlanValidationFinding]:
    if max_total_cost is None:
        return []
    total_cost = sum(item.metadata.get("estimated_cost", 0.0) for wave in waves for item in wave)
    if total_cost > max_total_cost:
        return [
            PlanValidationFinding(
                code="over_budget",
                severity="error",
                message=(f"Plan estimated cost {total_cost} exceeds ceiling {max_total_cost}"),
            )
        ]
    return []


async def _check_authority(
    waves: list[list[WorkItem]],
    principal: Principal | None,
    sentinel: Sentinel | None,
) -> list[PlanValidationFinding]:
    if principal is None or sentinel is None:
        return []

    from maistro.security.sentinel.authz_types import Tier

    findings: list[PlanValidationFinding] = []
    for wave in waves:
        for item in wave:
            decision = await sentinel.authorize(item.task_id, principal)
            if not decision.authorized or decision.tier == Tier.BLOCKED:
                findings.append(
                    PlanValidationFinding(
                        code="authority_exceeded",
                        severity="error",
                        message=(
                            f"Principal {principal.id!r} not authorized for task "
                            f"{item.task_id!r}: {decision.reason}"
                        ),
                        task_id=item.task_id,
                    )
                )
    return findings


async def validate_plan(
    waves: list[list[WorkItem]],
    *,
    max_total_cost: float | None = None,
    principal: Principal | None = None,
    sentinel: Sentinel | None = None,
) -> PlanValidationReport:
    findings: list[PlanValidationFinding] = []
    findings.extend(_check_cycles(waves))
    findings.extend(_check_budget(waves, max_total_cost))
    findings.extend(await _check_authority(waves, principal, sentinel))
    return PlanValidationReport(findings=tuple(findings))
