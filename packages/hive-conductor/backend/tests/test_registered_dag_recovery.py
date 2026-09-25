"""Recovery and timed wakeup for schedule-admitted registered-DAG Runs (#837).

`run_registered_dag` admits a canonical Run QUEUED with
``executor=durable_graph`` and the scheduler stamps
``admission_source=schedule`` on it. The Hive recovery cadence used to own
only ``hive_legacy_dag`` and Evolve Runs, and the schedule consumer leaves
multi-node QUEUED Runs to "the durable Graph traversal" -- so a scheduled
multi-node DAG lost before checkpoint 1, parked on an elapsed timer, or
answered after a HITL pause was never picked up again. These tests drive the
real admission path and the real canonical stores, then prove the cadence's
registered-DAG halves resume exactly that work and nothing else.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel
from services.dag_agents import get_registry, run_registered_dag

from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    HitlAuthorization,
    InMemoryGraphContinuationStore,
)
from maistro.graph.nodes import BaseNode, NodeContext, register_node
from maistro.graph.nodes.base import (
    PAUSE_AWAITING_HUMAN_ANSWER,
    PAUSE_WAITING_ON_JIRA_SUBTASKS,
    pause_until,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore

pytestmark = pytest.mark.contract("behavioral")


class _In(BaseModel):
    marker: str = "m"


class _Out(BaseModel):
    text: str


class _StepNode(BaseNode[_In, _Out]):
    kind: ClassVar[str] = "test.registered_recovery.step"
    kind_category: ClassVar = "transform"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        return _Out(text="done")


class _PollNode(BaseNode[_In, _Out]):
    """Parks on a timer-resumable reason whose instant has already elapsed.

    A timed wake re-enters the node, which re-polls, exactly as
    ``jira.wait_for_subtasks`` does; the second poll finds its condition met.
    """

    kind: ClassVar[str] = "test.registered_recovery.poll"
    kind_category: ClassVar = "wait"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out
    polled: ClassVar[set[str]] = set()

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        if ctx.run_id in type(self).polled:
            return _Out(text="polled")
        type(self).polled.add(ctx.run_id)
        pause_until(
            PAUSE_WAITING_ON_JIRA_SUBTASKS,
            resume_at=datetime.now(UTC) - timedelta(seconds=1),
            metadata={"first_seen": "t0"},
        )


class _AskNode(BaseNode[_In, _Out]):
    """Parks for a person; only an answer may move it on, never a timer."""

    kind: ClassVar[str] = "test.registered_recovery.ask"
    kind_category: ClassVar = "hitl"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        if (ctx.metadata or {}).get("hitl_answers", {}).get(ctx.node_id):
            return _Out(text="answered")
        pause_until(PAUSE_AWAITING_HUMAN_ANSWER, metadata={"question": "go?"})


for _kind in (_StepNode, _PollNode, _AskNode):
    with contextlib.suppress(ValueError):
        register_node(_kind)


def _descriptor(dag_id: str, first_kind: str, *, nodes: int = 2) -> dict[str, Any]:
    ids = [f"n{index}" for index in range(nodes)]
    kinds = [first_kind] + [_StepNode.kind] * (nodes - 1)
    return {
        "id": dag_id,
        "name": dag_id,
        "description": "registered-DAG recovery fixture",
        "entry_node": ids[0],
        "nodes": [
            {"id": node_id, "kind": kind, "config": {}}
            for node_id, kind in zip(ids, kinds, strict=True)
        ],
        "edges": [
            {"from_node": source, "to_node": target} for source, target in itertools.pairwise(ids)
        ],
    }


async def _allow_rdr_membership(_principal: str, _workspace_id: str) -> bool:
    return True


def _rdr_authorization() -> HitlAuthorization:
    """Typed effective-principal evidence for the test operator.

    HITL settlement is object-authorized at the canonical boundary: every
    answer must carry :class:`HitlAuthorization`, and the store re-checks
    Workspace membership inside the mutation. This fixture is the direct
    store-level equivalent of what the routes build from a verified session.
    """
    return HitlAuthorization(
        effective_principal="rdr-operator",
        workspace_ids=frozenset({"ws-rdr"}),
        membership_check=_allow_rdr_membership,
    )


_DAGS = {
    "rdr-steps": _descriptor("rdr-steps", _StepNode.kind),
    "rdr-poll": _descriptor("rdr-poll", _PollNode.kind),
    "rdr-ask": _descriptor("rdr-ask", _AskNode.kind),
    "rdr-single": _descriptor("rdr-single", _StepNode.kind, nodes=1),
    "rdr-poll-single": _descriptor("rdr-poll-single", _PollNode.kind, nodes=1),
}

_SCHEDULE = {"admission_source": "schedule", "schedule_id": "sched-1"}


@pytest.fixture(autouse=True)
def _registered_dags():
    registry = get_registry()
    for descriptor in _DAGS.values():
        registry.register(dict(descriptor))
    try:
        yield
    finally:
        for dag_id in _DAGS:
            registry.deregister(dag_id)


@pytest.fixture()
async def container(monkeypatch: pytest.MonkeyPatch) -> Any:
    import services.engine as engine_module

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-rdr")
    run_store = InMemoryRunStore(project_store=projects)
    providers = InMemoryProviderRegistry()
    built = SimpleNamespace(
        projects=projects,
        run_store=run_store,
        graph_run_store=CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore()),
        event_bus=None,
        a2a_delegator=None,
        guest_peers=None,
        capability_effects=new_in_memory_effect_context(),
        provider_registry=providers,
        llm_router=CostAwareRouter(providers),
        project_id=root.project_id,
    )
    port = SimpleNamespace(container=built)
    monkeypatch.setattr(engine_module, "get_engine", lambda: SimpleNamespace(_agent_port=port))
    return built


class _ProcessDied(BaseException):
    """The admitting process vanished after the canonical QUEUED write."""


async def _admit_then_die(
    container: Any,
    monkeypatch: pytest.MonkeyPatch,
    dag_id: str,
    *,
    provenance: dict[str, Any] | None = None,
) -> str:
    """Run the real admission, then lose the process before checkpoint 1."""
    import services.dag_agents as dag_agents

    admitted: dict[str, str] = {}

    async def _die(*args: Any, **kwargs: Any) -> Any:
        admitted["run_id"] = kwargs["run_id"]
        raise _ProcessDied

    with monkeypatch.context() as patched:
        patched.setattr(dag_agents, "run_durable_graph", _die)
        with pytest.raises(_ProcessDied):
            await run_registered_dag(
                dag_id,
                workspace_id="ws-rdr",
                project_id=container.project_id,
                provenance=provenance if provenance is not None else _SCHEDULE,
            )
    return admitted["run_id"]


async def _status(container: Any, run_id: str) -> RunStatus:
    run = await container.run_store.get_run(run_id)
    assert run is not None
    return run.status


@pytest.mark.asyncio
async def test_a_scheduled_multi_node_run_lost_before_checkpoint_one_completes(
    container: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.registered_dag_recovery import recover_stranded_registered_dag_runs

    run_id = await _admit_then_die(container, monkeypatch, "rdr-steps")
    assert await _status(container, run_id) is RunStatus.QUEUED

    assert await recover_stranded_registered_dag_runs() == 1

    assert await _status(container, run_id) is RunStatus.COMPLETED
    assert await recover_stranded_registered_dag_runs() == 0


@pytest.mark.asyncio
async def test_a_multi_node_run_admitted_by_the_production_schedule_path_completes(
    container: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configured Hive fires schedules through `ScheduleRunAdmitter`, not
    `run_registered_dag`: its Run is QUEUED with no executor marker and nothing
    has traversed it. The consumer leaves it alone (multi-node), so only this
    half can ever carry it."""
    import stores
    from services.registered_dag_recovery import recover_stranded_registered_dag_runs
    from services.scheduler import fire_now

    from maistro.graph.templates import InMemoryGraphTemplateStore
    from maistro.scheduling.admission import ScheduleRunAdmitter
    from maistro.scheduling.store import InMemoryScheduleStore

    templates = InMemoryGraphTemplateStore()
    schedules = InMemoryScheduleStore()
    container.template_store = templates
    container.schedule_store = schedules
    container.schedule_admitter = ScheduleRunAdmitter(container.run_store, templates, schedules)
    container.project_scope_store = container.projects
    created = datetime(2026, 8, 1, tzinfo=UTC)
    row = SimpleNamespace(
        id="sched-prod",
        user_id="user-1",
        workspace_id="ws-rdr",
        project_id=container.project_id,
        name="production schedule",
        description="",
        cron_expression="0 * * * *",
        mission_template_id="rdr-steps",
        enabled=True,
        timezone="UTC",
        max_runs=None,
        last_run=None,
        last_run_id=None,
        next_run=None,
        created_at=created,
        updated_at=created,
    )
    row.model_copy = lambda *, update: SimpleNamespace(**{**vars(row), **update})
    monkeypatch.setitem(stores.schedules._data, row.id, row)

    run_id = await fire_now(row.id)
    run = await container.run_store.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.QUEUED
    assert "executor" not in run.provenance

    assert await recover_stranded_registered_dag_runs() == 1
    assert await _status(container, run_id) is RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_an_elapsed_timer_wait_wakes_and_a_human_pause_does_not(
    container: Any,
) -> None:
    from services.registered_dag_recovery import wake_due_registered_dag_runs

    _graph, waiting = await run_registered_dag(
        "rdr-poll", workspace_id="ws-rdr", project_id=container.project_id, provenance=_SCHEDULE
    )
    _graph, asking = await run_registered_dag(
        "rdr-ask", workspace_id="ws-rdr", project_id=container.project_id, provenance=_SCHEDULE
    )
    assert await _status(container, waiting.run_id) is RunStatus.WAITING
    assert await _status(container, asking.run_id) is RunStatus.PAUSED

    assert await wake_due_registered_dag_runs() == 1

    assert await _status(container, waiting.run_id) is RunStatus.COMPLETED
    assert await _status(container, asking.run_id) is RunStatus.PAUSED


@pytest.mark.asyncio
async def test_a_single_node_timer_wait_is_woken_here_not_left_to_the_consumer(
    container: Any,
) -> None:
    """The consumer owns only QUEUED single-node Runs, and its resume tick
    matches YIELDED Attempts, never Graph pauses -- so the wake half is the only
    thing that can wake a single-node registered DAG parked on a timer."""
    from services.registered_dag_recovery import wake_due_registered_dag_runs

    _graph, waiting = await run_registered_dag(
        "rdr-poll-single",
        workspace_id="ws-rdr",
        project_id=container.project_id,
        provenance=_SCHEDULE,
    )
    assert await _status(container, waiting.run_id) is RunStatus.WAITING

    assert await wake_due_registered_dag_runs() == 1
    assert await _status(container, waiting.run_id) is RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_an_answered_scheduled_hitl_pause_resumes_on_the_next_tick(
    container: Any,
) -> None:
    from services.registered_dag_recovery import recover_stranded_registered_dag_runs

    _graph, asking = await run_registered_dag(
        "rdr-ask", workspace_id="ws-rdr", project_id=container.project_id, provenance=_SCHEDULE
    )
    assert await _status(container, asking.run_id) is RunStatus.PAUSED
    (paused_node,) = asking.graph_state.active_node_ids

    await container.graph_run_store.submit_hitl_answer(
        asking.run_id, paused_node, {"ok": True}, authorization=_rdr_authorization()
    )
    assert await _status(container, asking.run_id) is RunStatus.QUEUED

    assert await recover_stranded_registered_dag_runs() == 1
    assert await _status(container, asking.run_id) is RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_other_owners_runs_are_never_touched(
    container: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.registered_dag_recovery import (
        recover_stranded_registered_dag_runs,
        wake_due_registered_dag_runs,
    )

    legacy = await _admit_then_die(
        container, monkeypatch, "rdr-steps", provenance={"admission_source": "hive_legacy_dag"}
    )
    evolve = await _admit_then_die(
        container, monkeypatch, "rdr-steps", provenance={"admission_source": "evolution"}
    )
    single = await _admit_then_die(container, monkeypatch, "rdr-single")
    two_steps = Graph(
        workspace_id="ws-rdr",
        project_id=container.project_id,
        name="schedule, owned elsewhere",
        nodes=[
            Node(node_id="a", node_type=_StepNode.kind),
            Node(node_id="b", node_type=_StepNode.kind),
        ],
    )
    foreign_executor = (
        await container.run_store.create_run(
            two_steps,
            initial_status=RunStatus.QUEUED,
            provenance={**_SCHEDULE, "executor": "someone_else"},
        )
    ).run_id
    with_inputs = (
        await container.run_store.create_run(
            two_steps,
            initial_status=RunStatus.QUEUED,
            provenance={**_SCHEDULE, "schedule_inputs": {"marker": "configured"}},
        )
    ).run_id
    _graph, legacy_waiting = await run_registered_dag(
        "rdr-poll",
        workspace_id="ws-rdr",
        project_id=container.project_id,
        provenance={"admission_source": "hive_legacy_dag"},
    )

    assert await recover_stranded_registered_dag_runs() == 0
    assert await wake_due_registered_dag_runs() == 0

    for run_id in (legacy, evolve, single, foreign_executor, with_inputs):
        assert await _status(container, run_id) is RunStatus.QUEUED
    assert await _status(container, legacy_waiting.run_id) is RunStatus.WAITING


@pytest.mark.asyncio
async def test_a_foreign_prefix_longer_than_one_tick_is_crossed_across_ticks(
    container: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Single-node schedule Runs belong to the consumer and share the durable
    ``admission_source`` prefilter, so they are the realistic prefix a
    bounded scan must walk past to reach the one this half owns."""
    from services.registered_dag_recovery import recover_stranded_registered_dag_runs

    from maistro.graph.durable_runs.fair_scan import DEFAULT_MAX_INSPECTED

    single = Graph(
        workspace_id="ws-rdr",
        project_id=container.project_id,
        name="consumer-owned",
        nodes=[Node(node_id="only", node_type=_StepNode.kind)],
    )
    for _ in range(DEFAULT_MAX_INSPECTED + 1):
        await container.run_store.create_run(
            single,
            initial_status=RunStatus.QUEUED,
            provenance={**_SCHEDULE, "executor": "durable_graph"},
        )
    run_id = await _admit_then_die(container, monkeypatch, "rdr-steps")

    recovered = 0
    for _ in range(3):
        recovered += await recover_stranded_registered_dag_runs()
    assert recovered == 1
    assert await _status(container, run_id) is RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_both_halves_are_noops_without_a_container_graph_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.registered_dag_recovery as recovery

    monkeypatch.setattr(recovery, "_container", lambda: None)
    assert await recovery.recover_stranded_registered_dag_runs() == 0
    assert await recovery.wake_due_registered_dag_runs() == 0

    monkeypatch.setattr(
        recovery, "_container", lambda: SimpleNamespace(graph_run_store=None, run_store=object())
    )
    assert await recovery.recover_stranded_registered_dag_runs() == 0
    assert await recovery.wake_due_registered_dag_runs() == 0


@pytest.mark.asyncio
async def test_the_cadence_runs_both_registered_halves_and_survives_one_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.dag_recovery as cadence

    calls: list[str] = []

    async def _quiet() -> int:
        return 0

    async def _failing_recover() -> int:
        calls.append("recover")
        raise RuntimeError("registered-DAG listing unavailable")

    async def _waking() -> int:
        calls.append("wake")
        return 1

    monkeypatch.setattr(cadence, "recover_stranded_dag_runs", _quiet)
    monkeypatch.setattr(cadence, "wake_due_dag_runs", _quiet)
    monkeypatch.setattr(cadence, "recover_stranded_registered_dag_runs", _failing_recover)
    monkeypatch.setattr(cadence, "wake_due_registered_dag_runs", _waking)
    monkeypatch.setattr(cadence, "_INTERVAL_S", 0.01)

    await cadence.stop_dag_recovery()
    cadence.start_dag_recovery()
    try:
        await asyncio.wait_for(_observed(calls, ["recover", "wake", "recover", "wake"]), 5)
    finally:
        await cadence.stop_dag_recovery()


async def _observed(calls: list[str], expected: list[str]) -> None:
    while calls[: len(expected)] != expected:
        await asyncio.sleep(0.01)
