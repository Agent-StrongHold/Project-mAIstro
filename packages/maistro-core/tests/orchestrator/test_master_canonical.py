"""Acceptance coverage for MasterOrchestrator -> canonical Graph convergence (#548)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.graph.durable_runs import CanonicalDurableRunStore
from maistro.graph.nodes.base import NodeResult
from maistro.orchestrator.master import (
    _ROOT_NODE_ID,
    INVALID_TERMINAL_RESULT,
    WORK_ITEM_EXECUTION_FAILED_RESULT,
    MasterOrchestrator,
    Wave,
    WorkItem,
    WorkItemStatus,
    _outcome_key,
)
from maistro.orchestrator.output_security import (
    MAX_PROJECTED_XP,
    OUTPUT_SECURITY_ERROR_RESULT,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import (
    TERMINAL_RUN_STATUSES,
    AttemptStatus,
    NodeRun,
    RunStatus,
)
from maistro.runs.store import InMemoryRunStore


async def _pass(item: WorkItem) -> WorkItem:
    item.status = WorkItemStatus.PASSED
    item.result = f"done:{item.task_id}"
    return item


def _node_run(status: RunStatus, *, result: Any = None, error: str | None = None) -> NodeRun:
    finished_at = datetime.now(UTC) if status in TERMINAL_RUN_STATUSES else None
    return NodeRun(
        run_id="run-x",
        node_id="T1",
        ordinal=1,
        status=status,
        result=result,
        error=error,
        finished_at=finished_at,
    )


async def test_default_durable_state_projects_over_the_canonical_run_store() -> None:
    orch = MasterOrchestrator()
    orch.register_handler("mason", _pass)
    orch.load_plan([[WorkItem(task_id="T1", description="canonical", agent_role="mason")]])

    await orch.execute()

    assert isinstance(orch._durable_store, CanonicalDurableRunStore)
    assert orch.last_run_id is not None
    run = await orch._run_store.get_run(orch.last_run_id)
    record = await orch._durable_store.get(orch.last_run_id)
    assert run is not None
    assert record is not None
    assert record.run == run


async def test_work_item_execution_is_one_canonical_node_run_and_attempt() -> None:
    orch = MasterOrchestrator()
    orch.register_handler("mason", _pass)
    orch.load_plan([[WorkItem(task_id="T1", description="canonical", agent_role="mason")]])

    result = await orch.execute()

    assert result.plan_id == orch.last_run_id
    assert orch.last_run_id is not None
    run = await orch._run_store.get_run(orch.last_run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED

    node_runs = await orch._run_store.list_node_runs(orch.last_run_id)
    work_runs = [node_run for node_run in node_runs if node_run.node_id == "T1"]
    assert len(work_runs) == 1
    assert work_runs[0].status is RunStatus.COMPLETED

    attempts = await orch._run_store.list_attempts(work_runs[0].node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.COMPLETED


async def test_retry_is_a_new_node_run_with_its_own_attempt() -> None:
    orch = MasterOrchestrator(max_retries=2)
    calls = 0

    async def flaky(item: WorkItem) -> WorkItem:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")
        item.status = WorkItemStatus.PASSED
        item.result = "recovered"
        return item

    orch.register_handler("mason", flaky)
    orch.load_plan([[WorkItem(task_id="T1", description="flaky", agent_role="mason")]])

    result = await orch.execute()

    assert result.completed == 1
    assert calls == 2
    assert orch.last_run_id is not None
    node_runs = await orch._run_store.list_node_runs(orch.last_run_id)
    work_runs = [node_run for node_run in node_runs if node_run.node_id == "T1"]
    assert len(work_runs) == 2
    assert [node_run.ordinal for node_run in work_runs] == [2, 3]
    assert [node_run.status for node_run in work_runs] == [
        RunStatus.FAILED,
        RunStatus.COMPLETED,
    ]
    for node_run in work_runs:
        attempts = await orch._run_store.list_attempts(node_run.node_run_id)
        assert len(attempts) == 1
        assert attempts[0].ordinal == 1
        assert attempts[0].status is AttemptStatus.COMPLETED


async def test_parallel_sibling_success_survives_another_sibling_retry() -> None:
    orch = MasterOrchestrator(max_retries=1)
    flaky_calls = 0
    dependent_calls = 0

    async def flaky(item: WorkItem) -> WorkItem:
        nonlocal flaky_calls
        flaky_calls += 1
        if flaky_calls == 1:
            raise RuntimeError("retry me")
        return await _pass(item)

    async def dependent(item: WorkItem) -> WorkItem:
        nonlocal dependent_calls
        dependent_calls += 1
        return await _pass(item)

    orch.register_handler("mason", _pass)
    orch.register_handler("flaky", flaky)
    orch.register_handler("dependent", dependent)
    orch.load_plan(
        [
            [
                WorkItem(task_id="A", description="stable sibling", agent_role="mason"),
                WorkItem(task_id="B", description="retry sibling", agent_role="flaky"),
            ],
            [
                WorkItem(
                    task_id="C",
                    description="depends on stable sibling",
                    agent_role="dependent",
                    depends_on=["A"],
                )
            ],
        ]
    )

    result = await orch.execute()

    assert flaky_calls == 2
    assert dependent_calls == 1
    assert result.completed == 3
    assert result.failed == 0
    assert orch._items["A"].status == WorkItemStatus.PASSED
    assert orch._items["B"].status == WorkItemStatus.PASSED
    assert orch._items["C"].status == WorkItemStatus.PASSED


async def test_dependency_failure_blocks_only_dependent_work_and_graph_continues() -> None:
    orch = MasterOrchestrator(max_retries=0)
    blocked_handler_calls = 0

    async def fail(item: WorkItem) -> WorkItem:
        item.status = WorkItemStatus.FAILED
        item.result = "boom"
        return item

    async def should_not_run(item: WorkItem) -> WorkItem:
        nonlocal blocked_handler_calls
        blocked_handler_calls += 1
        return await _pass(item)

    orch.register_handler("failer", fail)
    orch.register_handler("blocked", should_not_run)
    orch.register_handler("mason", _pass)
    orch.load_plan(
        [
            [WorkItem(task_id="A", description="fails", agent_role="failer")],
            [
                WorkItem(
                    task_id="B",
                    description="blocked",
                    agent_role="blocked",
                    depends_on=["A"],
                ),
                WorkItem(task_id="C", description="independent", agent_role="mason"),
            ],
        ]
    )

    result = await orch.execute()

    assert result.failed == 1
    assert result.completed == 1
    assert orch._items["A"].status == WorkItemStatus.FAILED
    assert orch._items["B"].status == WorkItemStatus.BLOCKED
    assert orch._items["C"].status == WorkItemStatus.PASSED
    assert blocked_handler_calls == 0
    assert orch.last_run_id is not None
    run = await orch._run_store.get_run(orch.last_run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    node_runs = await orch._run_store.list_node_runs(orch.last_run_id)
    blocked_run = next(node_run for node_run in node_runs if node_run.node_id == "B")
    assert blocked_run.status is RunStatus.COMPLETED


async def test_canonical_item_reports_in_progress_during_handler() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_handler(item: WorkItem) -> WorkItem:
        started.set()
        await release.wait()
        item.status = WorkItemStatus.PASSED
        return item

    orch = MasterOrchestrator()
    orch.register_handler("mason", slow_handler)
    orch.load_plan([[WorkItem(task_id="T1", description="slow", agent_role="mason")]])

    execute_task = asyncio.create_task(orch.execute())
    await started.wait()

    progress = orch.get_progress()
    assert progress["by_status"].get(WorkItemStatus.IN_PROGRESS) == 1
    assert orch._items["T1"].status == WorkItemStatus.IN_PROGRESS

    release.set()
    result = await execute_task

    assert result.completed == 1
    assert orch._items["T1"].status == WorkItemStatus.PASSED


async def test_wave_parallelism_is_graph_structure_and_respects_configured_bound() -> None:
    orch = MasterOrchestrator(max_concurrent_per_wave=2)
    running = 0
    peak = 0
    lock = asyncio.Lock()

    async def observed(item: WorkItem) -> WorkItem:
        nonlocal running, peak
        async with lock:
            running += 1
            peak = max(peak, running)
        await asyncio.sleep(0.02)
        async with lock:
            running -= 1
        item.status = WorkItemStatus.PASSED
        return item

    orch.register_handler("mason", observed)
    orch.load_plan(
        [[WorkItem(task_id=f"T{i}", description="parallel", agent_role="mason") for i in range(5)]]
    )

    result = await orch.execute()

    assert result.completed == 5
    assert peak == 2
    assert orch.last_run_id is not None
    run = await orch._run_store.get_run(orch.last_run_id)
    assert run is not None
    graph = run.graph.materialize()
    assert graph.metadata["max_frontier_concurrency"] == 2
    work_nodes = [node for node in graph.nodes if node.node_type == "orchestrator.work_item"]
    assert len(work_nodes) == 5
    assert all(node.policies["max_attempts"] == 3 for node in work_nodes)
    assert all(node.policies["continue_on_failure"] is True for node in work_nodes)


async def test_security_gate_failure_is_domain_result_on_canonical_execution() -> None:
    async def security(item: WorkItem) -> WorkItem:
        item.status = WorkItemStatus.FAILED
        item.result = "policy"
        return item

    orch = MasterOrchestrator(max_retries=0, security_gate=security)
    orch.register_handler("mason", _pass)
    orch.load_plan([[WorkItem(task_id="T1", description="secure", agent_role="mason")]])

    result = await orch.execute()

    assert result.failed == 1
    assert orch._items["T1"].status == WorkItemStatus.FAILED
    assert orch.last_run_id is not None
    run = await orch._run_store.get_run(orch.last_run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    node_runs = await orch._run_store.list_node_runs(orch.last_run_id)
    node_run = next(node_run for node_run in node_runs if node_run.node_id == "T1")
    assert node_run.status is RunStatus.COMPLETED
    assert node_run.accepted_outcome is not None
    physical = NodeResult.model_validate(node_run.accepted_outcome.attempt_result.result)
    assert physical.success is True
    assert physical.status == "completed"
    attempts = await orch._run_store.list_attempts(node_run.node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.COMPLETED


async def test_security_gate_exception_is_projected_as_domain_failure() -> None:
    async def security(_: WorkItem) -> WorkItem:
        raise RuntimeError("gate unavailable with secret-value")

    orch = MasterOrchestrator(max_retries=0, security_gate=security)
    orch.register_handler("mason", _pass)
    orch.load_plan([[WorkItem(task_id="T1", description="secure", agent_role="mason")]])

    result = await orch.execute()

    assert result.failed == 1
    assert orch._items["T1"].status == WorkItemStatus.FAILED
    assert orch._items["T1"].result == OUTPUT_SECURITY_ERROR_RESULT
    assert "secret-value" not in orch._items["T1"].result


async def test_security_gate_that_accepts_leaves_the_result_untouched() -> None:
    """The two existing gate tests both make the gate fail the item. On the
    accepting path `_apply_security_gate` returns the handler's own status and
    message rather than the gate's -- the gate may only add metadata or refuse,
    never rewrite what the handler already decided."""

    async def security(item: WorkItem) -> WorkItem:
        item.metadata["scanned"] = True
        return item

    orch = MasterOrchestrator(max_retries=0, security_gate=security)
    orch.register_handler("mason", _pass)
    orch.load_plan([[WorkItem(task_id="T1", description="secure", agent_role="mason")]])

    result = await orch.execute()

    assert result.completed == 1
    assert orch._items["T1"].status == WorkItemStatus.PASSED
    assert orch._items["T1"].result == "done:T1"
    assert orch._items["T1"].metadata["scanned"] is True


def test_nonpositive_wave_concurrency_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_concurrent_per_wave"):
        MasterOrchestrator(max_concurrent_per_wave=0)


def test_negative_retry_budget_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_retries"):
        MasterOrchestrator(max_retries=-1)


def test_an_injected_run_store_without_scope_is_rejected() -> None:
    store = InMemoryRunStore(project_store=InMemoryProjectScopeStore())
    with pytest.raises(ValueError, match="workspace_id and project_id"):
        MasterOrchestrator(run_store=store)


async def test_an_injected_run_store_and_scope_are_used_as_given() -> None:
    """The constructor's default-construction branch is skipped when a store
    is supplied, and scope is given rather than minted -- `_scope_project_id`
    then returns the caller's id without ever touching a project store, which
    is why `_project_store` stays None here."""
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("ws-injected")
    run_store = InMemoryRunStore(project_store=project_store)
    orch = MasterOrchestrator(
        run_store=run_store, workspace_id="ws-injected", project_id=root.project_id
    )
    orch.register_handler("mason", _pass)
    orch.load_plan([[WorkItem(task_id="T1", agent_role="mason")]])

    await orch.execute()

    assert orch._project_store is None
    assert orch._run_store is run_store
    assert orch.last_run_id is not None
    run = await run_store.get_run(orch.last_run_id)
    assert run is not None
    assert run.project_id == root.project_id


async def test_scope_resolution_refuses_when_neither_id_nor_store_is_available() -> None:
    """Unreachable through the public constructor: supplying a run_store
    without a project_id is rejected there, so `_project_store` and
    `_project_id` can never both be unset at once through normal use. This
    exercises the defensive guard directly, the way a broken invariant
    earns its own test."""
    orch = MasterOrchestrator()
    orch._project_id = None
    orch._project_store = None

    with pytest.raises(RuntimeError, match="Project scope"):
        await orch._scope_project_id()


def test_a_blank_task_id_is_rejected() -> None:
    orch = MasterOrchestrator()
    with pytest.raises(ValueError, match="task_id"):
        orch.load_plan([[WorkItem(task_id="")]])


def test_duplicate_task_ids_are_rejected() -> None:
    orch = MasterOrchestrator()
    with pytest.raises(ValueError, match="unique"):
        orch.load_plan([[WorkItem(task_id="T1"), WorkItem(task_id="T1")]])


def test_the_reserved_root_task_id_is_rejected() -> None:
    orch = MasterOrchestrator()
    with pytest.raises(ValueError, match="reserved"):
        orch.load_plan([[WorkItem(task_id=_ROOT_NODE_ID)]])


async def test_a_dependency_on_an_unknown_task_is_rejected() -> None:
    orch = MasterOrchestrator()
    orch.register_handler("mason", _pass)
    orch.load_plan([[WorkItem(task_id="T1", agent_role="mason", depends_on=["ghost"])]])

    with pytest.raises(ValueError, match="ghost"):
        await orch.execute()


def test_projection_payload_is_none_when_the_result_is_not_a_mapping() -> None:
    node_run = _node_run(RunStatus.COMPLETED, result="not-a-dict")
    assert MasterOrchestrator._projection_payload(node_run) is None


def test_projection_payload_is_none_when_the_outcome_key_is_absent() -> None:
    node_run = _node_run(RunStatus.COMPLETED, result={"someone_elses_key": {}})
    assert MasterOrchestrator._projection_payload(node_run) is None


def test_projection_payload_is_none_when_the_outcome_shape_is_wrong() -> None:
    node_run = _node_run(
        RunStatus.COMPLETED,
        result={_outcome_key("T1"): {"status": 1, "result": "x", "metadata": {}}},
    )
    assert MasterOrchestrator._projection_payload(node_run) is None


def test_project_one_marks_a_never_dispatched_item_as_skipped() -> None:
    orch = MasterOrchestrator()
    item = WorkItem(task_id="T1", agent_role="mason")

    orch._project_one(item, None)

    assert item.status == WorkItemStatus.SKIPPED


def test_project_one_completed_without_a_payload_fails_closed() -> None:
    orch = MasterOrchestrator()
    item = WorkItem(
        task_id="T1",
        agent_role="mason",
        metadata={"stale_secret": "metadata-secret@example.com"},
    )
    node_run = _node_run(RunStatus.COMPLETED, result={"unrelated": True})

    orch._project_one(item, node_run)

    assert item.status == WorkItemStatus.FAILED
    assert item.result == INVALID_TERMINAL_RESULT
    assert item.metadata == {}


def test_project_one_projects_terminal_failure_statuses() -> None:
    orch = MasterOrchestrator()
    for status in (RunStatus.FAILED, RunStatus.TIMED_OUT, RunStatus.CANCELLED):
        item = WorkItem(task_id="T1", agent_role="mason")

        orch._project_one(item, _node_run(status, error="boom"))

        assert item.status == WorkItemStatus.FAILED
        assert item.result == WORK_ITEM_EXECUTION_FAILED_RESULT


def test_project_one_projects_in_flight_and_unstarted_statuses() -> None:
    orch = MasterOrchestrator()
    for status in (RunStatus.RUNNING, RunStatus.WAITING, RunStatus.PAUSED):
        item = WorkItem(task_id="T1", agent_role="mason")

        orch._project_one(item, _node_run(status))

        assert item.status == WorkItemStatus.IN_PROGRESS

    item = WorkItem(task_id="T1", agent_role="mason")

    orch._project_one(item, _node_run(RunStatus.QUEUED))

    assert item.status == WorkItemStatus.PENDING


def test_project_xp_skips_non_integer_awards() -> None:
    orch = MasterOrchestrator()
    passed = WorkItem(task_id="T1", agent_role="mason", status=WorkItemStatus.PASSED)
    passed.metadata["xp_earned"] = "ten"
    orch._items = {"T1": passed}

    orch._project_xp()

    assert orch._xp_earned == {}


@pytest.mark.parametrize("xp_earned", [-1, MAX_PROJECTED_XP + 1, True])
def test_project_xp_skips_out_of_range_awards(xp_earned: object) -> None:
    orch = MasterOrchestrator()
    passed = WorkItem(task_id="T1", agent_role="mason", status=WorkItemStatus.PASSED)
    passed.metadata["xp_earned"] = xp_earned
    orch._items = {"T1": passed}

    orch._project_xp()

    assert orch._xp_earned == {}


def test_project_waves_leaves_timestamps_unset_when_nothing_ran() -> None:
    orch = MasterOrchestrator()
    item = WorkItem(task_id="T1", agent_role="mason")
    wave = Wave(wave_number=0, items=[item])
    orch._waves = [wave]

    orch._project_waves()

    assert wave.started_at is None
    assert wave.completed_at is None


async def test_an_empty_plan_completes_with_nothing_to_do() -> None:
    """No waves means no work-item nodes, so the root has nothing to fan out
    to -- `_wave_edges` returns early rather than building edges to nothing."""
    orch = MasterOrchestrator()
    orch.load_plan([])

    result = await orch.execute()

    assert result.total_items == 0
    assert result.completed == 0
    assert result.failed == 0
