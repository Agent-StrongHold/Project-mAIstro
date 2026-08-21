"""Tests for the SuperPlanner/MasterOrchestrator pre-execution validation gate (SPEC-062126-a05f)."""

from __future__ import annotations

from maistro.orchestrator.master import WorkItem
from maistro.orchestrator.planner import (
    PlanTemplate,
    PlanValidationError,
    SubsystemDef,
    SuperPlanner,
)
from maistro.orchestrator.validation import validate_plan
from maistro.security.sentinel.authz_types import Principal, Tier
from maistro.security.sentinel.policy import Sentinel
from maistro.security.warden.detector import Warden


def _item(task_id: str, depends_on: list[str] | None = None, **metadata: float) -> WorkItem:
    return WorkItem(task_id=task_id, depends_on=depends_on or [], metadata=dict(metadata))


def _agent(principal_id: str) -> Principal:
    return Principal(id=principal_id, kind="agent", roles=(), scopes=(), owner="u1")


class TestCycleDetection:
    async def test_cyclic_plan_produces_cycle_finding(self) -> None:
        a = _item("A", depends_on=["B"])
        b = _item("B", depends_on=["A"])

        report = await validate_plan([[a, b]])

        assert report.is_valid is False
        assert any(f.code == "cycle" for f in report.findings)

    async def test_validate_plan_never_raises_on_cycle(self) -> None:
        a = _item("A", depends_on=["B"])
        b = _item("B", depends_on=["A"])

        report = await validate_plan([[a, b]])

        assert report is not None

    async def test_acyclic_plan_has_no_cycle_finding(self) -> None:
        a = _item("A")
        b = _item("B", depends_on=["A"])

        report = await validate_plan([[a], [b]])

        assert not any(f.code == "cycle" for f in report.findings)


class TestBudgetCheck:
    async def test_over_budget_plan_produces_finding(self) -> None:
        a = _item("A", estimated_cost=60.0)
        b = _item("B", estimated_cost=60.0)

        report = await validate_plan([[a, b]], max_total_cost=100.0)

        assert report.is_valid is False
        over_budget = [f for f in report.findings if f.code == "over_budget"]
        assert len(over_budget) == 1
        assert over_budget[0].task_id is None

    async def test_under_budget_plan_has_no_finding(self) -> None:
        a = _item("A", estimated_cost=10.0)

        report = await validate_plan([[a]], max_total_cost=100.0)

        assert not any(f.code == "over_budget" for f in report.findings)

    async def test_no_budget_ceiling_never_produces_finding(self) -> None:
        a = _item("A", estimated_cost=1_000_000.0)

        report = await validate_plan([[a]], max_total_cost=None)

        assert not any(f.code == "over_budget" for f in report.findings)


class TestAuthorityCheck:
    async def test_unauthorized_principal_produces_finding_naming_task(self) -> None:
        sentinel = Sentinel(warden=Warden(), permission_table={"deploy": frozenset({"deployer"})})
        principal = _agent("agent-1")
        a = _item("deploy")

        report = await validate_plan([[a]], principal=principal, sentinel=sentinel)

        findings = [f for f in report.findings if f.code == "authority_exceeded"]
        assert len(findings) == 1
        assert findings[0].task_id == "deploy"

    async def test_multiple_failing_items_all_aggregated(self) -> None:
        sentinel = Sentinel(
            warden=Warden(),
            permission_table={
                "deploy": frozenset({"deployer"}),
                "destroy": frozenset({"destroyer"}),
            },
        )
        principal = _agent("agent-1")
        a = _item("deploy")
        b = _item("destroy")

        report = await validate_plan([[a, b]], principal=principal, sentinel=sentinel)

        findings = [f for f in report.findings if f.code == "authority_exceeded"]
        assert {f.task_id for f in findings} == {"deploy", "destroy"}

    async def test_blocked_tier_produces_authority_finding(self) -> None:
        sentinel = Sentinel(
            warden=Warden(),
            permission_table={},
            tier_policy={("wipe_disk", "agent-1"): Tier.BLOCKED},
        )
        principal = Principal(id="agent-1", kind="agent", roles=(), scopes=("agent-1",), owner="u1")
        a = _item("wipe_disk")

        report = await validate_plan([[a]], principal=principal, sentinel=sentinel)

        assert any(
            f.code == "authority_exceeded" and f.task_id == "wipe_disk" for f in report.findings
        )

    async def test_authorized_principal_produces_no_finding(self) -> None:
        sentinel = Sentinel(
            warden=Warden(),
            permission_table={"deploy": frozenset({"deployer"})},
        )
        principal = Principal(
            id="agent-1", kind="agent", roles=("deployer",), scopes=(), owner="u1"
        )
        a = _item("deploy")

        report = await validate_plan([[a]], principal=principal, sentinel=sentinel)

        assert not any(f.code == "authority_exceeded" for f in report.findings)

    async def test_no_principal_or_sentinel_skips_authority_check(self) -> None:
        a = _item("deploy")

        report = await validate_plan([[a]])

        assert not any(f.code == "authority_exceeded" for f in report.findings)


class TestFullyValidPlan:
    async def test_fully_valid_plan_returns_empty_report(self) -> None:
        sentinel = Sentinel(
            warden=Warden(),
            permission_table={"A": frozenset({"builder"}), "B": frozenset({"builder"})},
        )
        principal = Principal(id="agent-1", kind="agent", roles=("builder",), scopes=(), owner="u1")
        a = _item("A", estimated_cost=10.0)
        b = _item("B", depends_on=["A"], estimated_cost=10.0)

        report = await validate_plan(
            [[a], [b]],
            max_total_cost=100.0,
            principal=principal,
            sentinel=sentinel,
        )

        assert report.findings == ()
        assert report.is_valid is True


class TestBuildOrchestratorRefusal:
    async def test_refuses_to_build_orchestrator_for_invalid_plan(self) -> None:
        template = PlanTemplate(
            name="cyclic-test",
            description="cyclic test template",
            subsystems=[
                SubsystemDef("A", "g", "task A", "mason", depends_on=["B"]),
                SubsystemDef("B", "g", "task B", "mason", depends_on=["A"]),
            ],
        )
        planner = SuperPlanner(template)

        try:
            await planner.build_validated_orchestrator()
            raised = False
        except PlanValidationError:
            raised = True

        assert raised is True

    async def test_builds_orchestrator_for_valid_plan(self) -> None:
        template = PlanTemplate(
            name="valid-test",
            description="valid test template",
            subsystems=[
                SubsystemDef("A", "g", "task A", "mason"),
                SubsystemDef("B", "g", "task B", "mason", depends_on=["A"]),
            ],
        )
        planner = SuperPlanner(template)

        orchestrator = await planner.build_validated_orchestrator()

        assert orchestrator is not None
