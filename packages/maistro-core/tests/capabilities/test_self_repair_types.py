"""self_repair slot types + protocol (SPEC-188)."""

from __future__ import annotations

from maistro.capabilities.protocols import CapabilityProvider
from maistro.capabilities.slots.infra import InfraHealth
from maistro.capabilities.slots.self_repair import (
    RepairCycleResult,
    RepairDecision,
    RepairProposal,
    RepairResult,
    SelfRepair,
)
from maistro.capabilities.types import ProviderHealth


def test_repair_proposal_fields() -> None:
    p = RepairProposal(
        resource="docker:litellm",
        symptom="container down",
        action="restart_container",
        params={"name": "litellm"},
        tier="reversible",
        rationale="container reported down",
    )
    assert p.action == "restart_container"
    assert p.params == {"name": "litellm"}
    assert p.tier == "reversible"


def test_proposal_with_no_action_is_allowed() -> None:
    # propose-only / undiagnosed proposals carry action=None.
    p = RepairProposal(
        resource="storage:dbpool", symptom="zpool degraded", action=None, params={}, tier=""
    )
    assert p.action is None


def test_repair_decision_values() -> None:
    assert {
        RepairDecision.ACTED,
        RepairDecision.PENDING_APPROVAL,
        RepairDecision.SUPPRESSED,
        RepairDecision.PROPOSE_ONLY,
        RepairDecision.UNDIAGNOSED,
        RepairDecision.FAILED,
    }


def test_cycle_result_acted_helper() -> None:
    p1 = RepairProposal("docker:a", "down", "restart_container", {"name": "a"}, "reversible")
    p2 = RepairProposal("storage:x", "degraded", None, {}, "")
    result = RepairCycleResult(
        ts="2026-05-30T00:00:00Z",
        results=[
            RepairResult(p1, RepairDecision.ACTED, "ok"),
            RepairResult(p2, RepairDecision.PROPOSE_ONLY, "escalated"),
        ],
    )
    assert [r.proposal.resource for r in result.acted] == ["docker:a"]
    assert len(result.results) == 2


def test_self_repair_protocol_is_runtime_checkable() -> None:
    class _Fake:
        @property
        def name(self) -> str:
            return "rule_based_repair"

        @property
        def slot(self) -> str:
            return "self_repair"

        @property
        def trust_tier(self) -> str:
            return "t0"

        def requires(self) -> tuple[str, ...]:
            return ()

        async def healthcheck(self) -> ProviderHealth:
            return ProviderHealth(healthy=True)

        async def evaluate(self, health: InfraHealth) -> list[RepairProposal]:
            return []

        async def run_once(self) -> RepairCycleResult:
            return RepairCycleResult(ts="", results=[])

    fake = _Fake()
    assert isinstance(fake, SelfRepair)
    assert isinstance(fake, CapabilityProvider)
