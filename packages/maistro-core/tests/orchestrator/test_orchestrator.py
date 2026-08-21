"""Tests for Master Orchestrator and Super Planner."""

from __future__ import annotations

import pytest

from maistro.orchestrator.master import (
    MasterOrchestrator,
    WorkItem,
    WorkItemStatus,
)
from maistro.orchestrator.planner import (
    PlanTemplate,
    SubsystemDef,
    SuperPlanner,
    _topological_sort,
)


async def _pass_handler(item: WorkItem) -> WorkItem:
    item.status = WorkItemStatus.PASSED
    item.result = "done"
    return item


async def _fail_handler(item: WorkItem) -> WorkItem:
    item.status = WorkItemStatus.FAILED
    item.result = "boom"
    return item


async def _flaky_handler(item: WorkItem) -> WorkItem:
    if item.metadata.get("attempt", 0) == 0:
        item.metadata["attempt"] = 1
        raise RuntimeError("transient failure")
    item.status = WorkItemStatus.PASSED
    item.result = "recovered"
    return item


class TestMasterOrchestrator:
    async def test_single_item_passes(self):
        orch = MasterOrchestrator()
        orch.register_handler("mason", _pass_handler)
        orch.load_plan([[WorkItem(task_id="T1", description="test", agent_role="mason")]])

        result = await orch.execute()
        assert result.total_items == 1
        assert result.completed == 1
        assert result.failed == 0

    async def test_single_item_fails(self):
        orch = MasterOrchestrator()
        orch.register_handler("mason", _fail_handler)
        orch.load_plan([[WorkItem(task_id="T1", description="test", agent_role="mason")]])

        result = await orch.execute()
        assert result.completed == 0
        assert result.failed == 1

    async def test_parallel_items_in_same_wave(self):
        orch = MasterOrchestrator()
        orch.register_handler("mason", _pass_handler)
        items = [
            WorkItem(task_id=f"T{i}", description=f"task {i}", agent_role="mason") for i in range(5)
        ]
        orch.load_plan([items])

        result = await orch.execute()
        assert result.completed == 5

    async def test_sequential_waves(self):
        orch = MasterOrchestrator()
        orch.register_handler("mason", _pass_handler)
        wave1 = [WorkItem(task_id="A1", description="first", agent_role="mason")]
        wave2 = [
            WorkItem(task_id="B1", description="second", agent_role="mason", depends_on=["A1"])
        ]
        orch.load_plan([wave1, wave2])

        result = await orch.execute()
        assert result.completed == 2
        assert result.waves_completed == 2

    async def test_blocked_dependency(self):
        orch = MasterOrchestrator(max_retries=0)
        orch.register_handler("mason", _fail_handler)
        wave1 = [WorkItem(task_id="A1", description="fails", agent_role="mason")]
        wave2 = [
            WorkItem(task_id="B1", description="blocked", agent_role="mason", depends_on=["A1"])
        ]
        orch.load_plan([wave1, wave2])

        result = await orch.execute()
        assert result.failed == 1
        assert orch._items["B1"].status == WorkItemStatus.BLOCKED

    async def test_retry_on_exception(self):
        orch = MasterOrchestrator(max_retries=1)
        orch.register_handler("mason", _flaky_handler)
        orch.load_plan([[WorkItem(task_id="T1", description="flaky", agent_role="mason")]])

        result = await orch.execute()
        assert result.completed == 1

    async def test_progress_tracking(self):
        orch = MasterOrchestrator()
        orch.register_handler("mason", _pass_handler)
        orch.load_plan([[WorkItem(task_id="T1", description="test", agent_role="mason")]])

        await orch.execute()
        progress = orch.get_progress()
        assert progress["total"] == 1
        assert progress["by_status"]["passed"] == 1

    async def test_missing_handler_fails(self):
        orch = MasterOrchestrator()
        orch.load_plan([[WorkItem(task_id="T1", description="test", agent_role="unknown")]])

        result = await orch.execute()
        assert result.failed == 1

    async def test_security_gate_blocks(self):
        async def security_block(item: WorkItem) -> WorkItem:
            item.status = WorkItemStatus.FAILED
            item.result = "security violation"
            return item

        orch = MasterOrchestrator(security_gate=security_block)
        orch.register_handler("mason", _pass_handler)
        orch.load_plan([[WorkItem(task_id="T1", description="test", agent_role="mason")]])

        result = await orch.execute()
        assert result.failed == 1


class TestSuperPlanner:
    def test_topological_sort_no_deps(self):
        items = [
            SubsystemDef("A", "g1", "a"),
            SubsystemDef("B", "g1", "b"),
        ]
        waves = _topological_sort(items)
        assert len(waves) == 1
        assert len(waves[0]) == 2

    def test_topological_sort_chain(self):
        items = [
            SubsystemDef(task_id="A", group="g1", description="a"),
            SubsystemDef(task_id="B", group="g1", description="b", depends_on=["A"]),
            SubsystemDef(task_id="C", group="g1", description="c", depends_on=["B"]),
        ]
        waves = _topological_sort(items)
        assert len(waves) == 3
        assert waves[0][0].task_id == "A"
        assert waves[1][0].task_id == "B"
        assert waves[2][0].task_id == "C"

    def test_topological_sort_diamond(self):
        items = [
            SubsystemDef(task_id="A", group="g1", description="a"),
            SubsystemDef(task_id="B", group="g1", description="b", depends_on=["A"]),
            SubsystemDef(task_id="C", group="g1", description="c", depends_on=["A"]),
            SubsystemDef(task_id="D", group="g1", description="d", depends_on=["B", "C"]),
        ]
        waves = _topological_sort(items)
        assert len(waves) == 3
        assert len(waves[0]) == 1  # A
        assert len(waves[1]) == 2  # B, C
        assert len(waves[2]) == 1  # D

    def test_plan_produces_waves(self):
        planner = SuperPlanner()
        waves = planner.plan()
        assert len(waves) > 0
        all_task_ids = [item.task_id for wave in waves for item in wave]
        assert "A1" in all_task_ids
        assert "L5" in all_task_ids

    def test_plan_dependencies_respected(self):
        planner = SuperPlanner()
        waves = planner.plan()
        task_wave = {}
        for i, wave in enumerate(waves):
            for item in wave:
                task_wave[item.task_id] = i

        for wave in waves:
            for item in wave:
                for dep in item.depends_on:
                    assert task_wave[dep] < task_wave[item.task_id], (
                        f"{item.task_id} (wave {task_wave[item.task_id]}) "
                        f"depends on {dep} (wave {task_wave[dep]})"
                    )

    def test_summary(self):
        planner = SuperPlanner()
        summary = planner.summary()
        assert summary["total_items"] > 0
        assert summary["total_waves"] > 0
        assert "foundation" in summary["groups"]
        assert "memory" in summary["groups"]
        assert "security" in summary["groups"]

    def test_build_orchestrator(self):
        planner = SuperPlanner()
        orch = planner.build_orchestrator()
        assert orch._items
        assert len(orch._waves) > 0

    def test_topological_sort_self_cycle_raises(self):
        # A depends on itself → must raise a clear error, not RecursionError.
        items = [SubsystemDef(task_id="A", group="g1", description="a", depends_on=["A"])]
        with pytest.raises(ValueError, match="cycle"):
            _topological_sort(items)

    def test_topological_sort_two_node_cycle_raises(self):
        # A → B → A. Must raise a clear ValueError naming the cycle, not RecursionError.
        items = [
            SubsystemDef(task_id="A", group="g1", description="a", depends_on=["B"]),
            SubsystemDef(task_id="B", group="g1", description="b", depends_on=["A"]),
        ]
        with pytest.raises(ValueError, match="cycle") as exc:
            _topological_sort(items)
        assert not isinstance(exc.value, RecursionError)

    def test_topological_sort_three_node_cycle_raises(self):
        items = [
            SubsystemDef(task_id="A", group="g1", description="a", depends_on=["C"]),
            SubsystemDef(task_id="B", group="g1", description="b", depends_on=["A"]),
            SubsystemDef(task_id="C", group="g1", description="c", depends_on=["B"]),
        ]
        with pytest.raises(ValueError, match="cycle"):
            _topological_sort(items)

    def test_custom_template(self):
        template = PlanTemplate(
            name="test",
            description="test",
            subsystems=[
                SubsystemDef(task_id="X1", group="g1", description="first"),
                SubsystemDef(task_id="X2", group="g1", description="second", depends_on=["X1"]),
            ],
        )
        planner = SuperPlanner(template=template)
        waves = planner.plan()
        assert len(waves) == 2
        assert len(waves[0]) == 1
        assert len(waves[1]) == 1
