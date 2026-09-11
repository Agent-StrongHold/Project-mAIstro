"""The configured Hive process consumes the schedule Runs its producer admits (#1243).

Failure mode under audit: `services/scheduler.py`'s canonical path hands due
occurrences to `ScheduleRunAdmitter`, which admits each one straight to QUEUED
(#251: "a schedule Run's admission IS its submission") and advances the
schedule cursor — while ADR-082826-b601 deliberately leaves the consumer tick
to the product, and no shipped process ever scheduled it. The producer's own
view said "fired" while every admitted Run sat QUEUED forever, and each further
tick grew the backlog.

These tests pin both halves: the stranded-admission shape is reproduced
end-to-end against a real Container, and the shipped consumer cadence
(`services/schedule_consumer.py`, started by `EngineService.start` beside the
legacy-DAG recovery cadence) is what drains it — through the canonical
`Container.execute_admitted_runs` / `Container.resume_parked_runs` seams, never
a second execution authority.
"""

from __future__ import annotations

import asyncio
import contextlib
import pathlib
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph.nodes import BaseNode, NodeContext, register_node

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


class _ScheduleTickIn(BaseModel):
    greeting: str = "hello"


class _ScheduleTickOut(BaseModel):
    text: str


class _ScheduleTickNode(BaseNode[_ScheduleTickIn, _ScheduleTickOut]):
    kind: ClassVar[str] = "test.hive.schedule_consumer"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _ScheduleTickIn
    output_schema: ClassVar[type[BaseModel]] = _ScheduleTickOut
    calls: ClassVar[int] = 0

    async def _execute(self, inputs: _ScheduleTickIn, ctx: NodeContext) -> _ScheduleTickOut:
        type(self).calls += 1
        return _ScheduleTickOut(text=inputs.greeting.upper())


with contextlib.suppress(ValueError):
    register_node(_ScheduleTickNode)


class _Row:
    """A `/v1/schedules` row, shaped like the live store's records."""

    def __init__(self, sid: str, template_id: str, *, project_id: str) -> None:
        self.id = sid
        self.user_id = "user-1"
        self.workspace_id = "ws-1"
        self.project_id = project_id
        self.name = f"schedule-{sid}"
        self.description = ""
        self.cron_expression = "0 * * * *"
        self.mission_template_id = template_id
        self.enabled = True
        self.timezone = "UTC"
        self.max_runs = None
        self.last_run = datetime(2026, 8, 21, 11, 0, tzinfo=UTC)
        self.last_run_id: str | None = None
        self.next_run: datetime | None = None
        self.created_at = datetime(2026, 8, 1, tzinfo=UTC)
        self.updated_at = self.created_at

    def model_copy(self, *, update: dict[str, Any]) -> _Row:
        clone = _Row(self.id, self.mission_template_id, project_id=self.project_id)
        clone.__dict__.update(self.__dict__)
        clone.__dict__.update(update)
        return clone


async def _wired_container() -> Any:
    """A real core Container with the scheduled template registered.

    This is what a configured Hive's bridge exposes — the same Container the
    scheduler's producer path resolves through `_canonical_container` and the
    consumer cadence resolves through the engine's AgentPort.
    """
    from maistro.container import create_container
    from maistro.graph.definitions import GraphTemplate, Node
    from maistro.types.config import AgentConfig

    container = await create_container(AgentConfig(router_api_key="test-key"))
    root = await container.project_scope_store.create_root("ws-1")
    await container.template_store.put(
        GraphTemplate(
            template_id="scheduled-template",
            workspace_id="ws-1",
            version=1,
            name="Scheduled template",
            nodes=[
                Node(
                    node_id="only",
                    node_type=_ScheduleTickNode.kind,
                    parameters={"greeting": "static"},
                )
            ],
            edges=[],
            metadata={"entry_node": "only"},
        )
    )
    return container, root


async def _project_id(container: Any) -> str:
    root = await container.project_scope_store.root_for_workspace("ws-1")
    return root.project_id


def _install_row(row: _Row) -> None:
    import stores

    stores.schedules._data[row.id] = row  # type: ignore[attr-defined]


def _remove_row(row: _Row) -> None:
    import stores

    stores.schedules._data.pop(row.id, None)  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
async def _no_cadence_left_behind():
    yield
    import services.schedule_consumer as cadence

    await cadence.stop_schedule_consumer()


async def test_admitted_schedule_runs_stranded_until_the_consumer_tick_drains_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The audited failure mode, end to end, then the fix.

    The configured producer path admits each due occurrence QUEUED and advances
    the schedule cursor — from the schedule's own point of view the work
    "fired". Nothing in the shipped process executed it: the node never ran,
    and a second tick grew the backlog. `tick_schedule_consumer` — the cadence
    `EngineService.start` now runs — is what drains exactly that backlog
    through the canonical Container seam.
    """
    from services.scheduler import _ScheduleRunner

    from maistro.runs.model import RunStatus
    from maistro.runs.sources import ADMISSION_SOURCE, SCHEDULE_SOURCE

    _ScheduleTickNode.calls = 0
    container, _root = await _wired_container()
    row = _Row("s-1243", "scheduled-template", project_id=await _project_id(container))
    _install_row(row)
    monkeypatch.setattr(_ScheduleRunner, "_canonical_container", staticmethod(lambda: container))

    stranded: list[str] = []
    try:
        await _ScheduleRunner()._evaluate_schedule(
            "s-1243", row, now=datetime(2026, 8, 21, 12, 5, tzinfo=UTC)
        )
        recorded = await container.schedule_store.get("s-1243")
        assert recorded is not None
        assert recorded.last_run_id is not None
        first = await container.run_store.get_run(recorded.last_run_id)
        assert first is not None
        assert first.provenance[ADMISSION_SOURCE] == SCHEDULE_SOURCE
        # The producer believes it fired (cursor advanced), yet the admitted
        # Run is exactly the state the audit names: QUEUED, never executed.
        assert first.status is RunStatus.QUEUED
        assert _ScheduleTickNode.calls == 0
        stranded.append(first.run_id)

        # A later tick does not grow the store here — but only because the
        # stranded QUEUED Run still reads as "active": under the default SKIP
        # overlap policy the 13:00 occurrence is dropped outright, so the
        # schedule silently stops working while its cursor keeps reporting
        # success. The undrained admission is suppressive, not just inert.
        await _ScheduleRunner()._evaluate_schedule(
            "s-1243", row, now=datetime(2026, 8, 21, 13, 5, tzinfo=UTC)
        )
        assert (await container.schedule_store.get("s-1243")).last_run_id == first.run_id
        assert len(container.run_store._runs) == 1  # type: ignore[attr-defined]
        assert _ScheduleTickNode.calls == 0

        # The consumer cadence is the missing half: it drains the producer's
        # stranded admission through the canonical tick.
        import services.schedule_consumer as cadence

        monkeypatch.setattr(cadence, "_wired_container", lambda: container)
        assert await cadence.tick_schedule_consumer() == (1, 0)
        assert _ScheduleTickNode.calls == 1
        for run_id in stranded:
            run = await container.run_store.get_run(run_id)
            assert run is not None
            assert run.status is RunStatus.COMPLETED
    finally:
        _remove_row(row)


async def test_engine_start_starts_and_stop_stops_the_consumer_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wiring the audit asked for: the configured lifespan's engine start
    runs the consumer cadence beside the legacy-DAG recovery cadence, and the
    engine's shutdown joins it."""
    import services.engine as engine_mod
    import services.schedule_consumer as cadence

    started: list[bool] = []
    stopped: list[bool] = []

    async def _fake_start() -> None:
        started.append(True)

    async def _fake_stop() -> None:
        stopped.append(True)

    monkeypatch.setattr(cadence, "start_schedule_consumer", _fake_start)
    monkeypatch.setattr(cadence, "stop_schedule_consumer", _fake_stop)

    class _Settings:
        maistro_router_api_key = ""
        maistro_base_url = "http://localhost:8000"
        hive_mode = "demo"
        hive_default_workspace_id = "default"

    import types

    class _Q:
        def __init__(self, *, admitter: Any = None) -> None:
            self.admitter = admitter

    class _R:
        def __init__(self, q: Any, executor: Any, attempts: Any = None) -> None:
            pass

        async def start(self) -> None:
            pass

    queue_mod = types.ModuleType("maistro.tasks.queue")
    queue_mod.TaskQueue = _Q  # type: ignore[attr-defined]
    runner_mod = types.ModuleType("maistro.tasks.runner")
    runner_mod.TaskRunner = _R  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.tasks.queue", queue_mod)
    monkeypatch.setitem(sys.modules, "maistro.tasks.runner", runner_mod)
    conductor_mod = types.ModuleType("maistro.agents.conductor")

    async def _stub_run_task(*a: Any, **kw: Any) -> Any:
        return None

    conductor_mod.run_task = _stub_run_task  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "maistro.agents.conductor", conductor_mod)

    prev_singleton = engine_mod._singleton
    engine_mod._singleton = None
    try:
        svc = engine_mod.EngineService()
        await svc.start(_Settings())  # type: ignore[arg-type]
        assert started == [True]
        await svc.stop()
        assert stopped == [True]
    finally:
        engine_mod._singleton = prev_singleton


async def test_wired_container_is_resolved_through_the_engine_seam() -> None:
    """The cadence reads the Container off the engine's AgentPort — the same
    bridge the scheduler's producer path resolves — never its own store handle."""
    import services.engine as engine_mod
    import services.schedule_consumer as cadence

    marker = object()
    singleton = engine_mod._singleton
    assert singleton is not None, "conftest installs a stub engine singleton"
    prev_port = singleton._agent_port
    singleton._agent_port = SimpleNamespace(container=marker)
    try:
        assert cadence._wired_container() is marker
    finally:
        singleton._agent_port = prev_port
    # The stub/demo port carries no Container: there is no canonical spine to
    # consume from, so the resolution answers None rather than inventing one.
    assert cadence._wired_container() is None


async def test_tick_is_a_noop_without_a_wired_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Standalone/demo Conductor keeps today's behavior: no bridge, no
    canonical spine, no fabricated consumption."""
    import services.schedule_consumer as cadence

    monkeypatch.setattr(cadence, "_wired_container", lambda: None)
    assert await cadence.tick_schedule_consumer() == (0, 0)


async def test_drain_failure_does_not_silence_the_wake_half(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two halves answer different questions about the same store; one
    failing is reported and the sibling still runs in the same tick."""
    import services.schedule_consumer as cadence

    calls: list[str] = []

    class _Container:
        async def execute_admitted_runs(self) -> int:
            calls.append("drain")
            raise RuntimeError("store briefly unavailable")

        async def resume_parked_runs(self) -> int:
            calls.append("wake")
            return 1

    monkeypatch.setattr(cadence, "_wired_container", lambda: _Container())
    assert await cadence.tick_schedule_consumer() == (0, 1)
    assert calls == ["drain", "wake"]


async def test_cadence_ticks_both_halves_and_stops(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The started cadence is one task that reports productive ticks and is
    joined — not leaked — on stop."""
    import logging

    import services.schedule_consumer as cadence

    ticked = asyncio.Event()

    async def _tick() -> tuple[int, int]:
        ticked.set()
        return (2, 1)

    await cadence.stop_schedule_consumer()
    monkeypatch.setattr(cadence, "tick_schedule_consumer", _tick)
    monkeypatch.setattr(cadence, "_interval_s", lambda: 3600)

    with caplog.at_level(logging.INFO, logger="hive.schedule_consumer"):
        await cadence.start_schedule_consumer()
        assert cadence._task is not None
        await asyncio.wait_for(ticked.wait(), timeout=1.0)
        await asyncio.sleep(0.05)  # let the loop body reach its log line
    assert any("drained=2 resumed=1" in r.getMessage() for r in caplog.records)

    await cadence.stop_schedule_consumer()
    assert cadence._task is None


async def test_cadence_survives_a_failing_tick(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One malformed tick must not kill the cadence: the loop reports the
    failure and keeps consuming on the next bounded tick."""
    import logging

    import services.schedule_consumer as cadence

    ticks = {"count": 0}
    recovered = asyncio.Event()

    async def _tick() -> tuple[int, int]:
        ticks["count"] += 1
        if ticks["count"] == 1:
            raise RuntimeError("engine not wired yet")
        recovered.set()
        return (3, 0)

    await cadence.stop_schedule_consumer()
    monkeypatch.setattr(cadence, "tick_schedule_consumer", _tick)
    monkeypatch.setattr(cadence, "_interval_s", lambda: 0.001)

    await cadence.start_schedule_consumer()
    with caplog.at_level(logging.INFO, logger="hive.schedule_consumer"):
        await asyncio.wait_for(recovered.wait(), timeout=5.0)

    assert any("schedule_consumer_tick_failed" in r.getMessage() for r in caplog.records)
    assert any("drained=3 resumed=0" in r.getMessage() for r in caplog.records)

    await cadence.stop_schedule_consumer()
    assert cadence._task is None


async def test_starting_the_cadence_twice_keeps_one_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`start` is idempotent: two starts must not leave two cadences ticking,
    or one shutdown join would strand the other."""
    import services.schedule_consumer as cadence

    ticked = asyncio.Event()

    async def _tick() -> tuple[int, int]:
        ticked.set()
        return (0, 0)

    await cadence.stop_schedule_consumer()
    monkeypatch.setattr(cadence, "tick_schedule_consumer", _tick)
    monkeypatch.setattr(cadence, "_interval_s", lambda: 3600)

    await cadence.start_schedule_consumer()
    first = cadence._task
    await cadence.start_schedule_consumer()
    assert cadence._task is first
    await cadence.stop_schedule_consumer()


async def test_disabled_interval_starts_nothing_and_says_so(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`SCHEDULE_CONSUMER_INTERVAL_S <= 0` is a loud degraded mode, not a
    silent one: the producer above it keeps admitting QUEUED Runs."""
    import logging

    import services.schedule_consumer as cadence

    await cadence.stop_schedule_consumer()
    monkeypatch.setattr(cadence, "_interval_s", lambda: 0)

    with caplog.at_level(logging.WARNING, logger="hive.schedule_consumer"):
        await cadence.start_schedule_consumer()

    assert cadence._task is None
    assert any("schedule_consumer_disabled" in r.getMessage() for r in caplog.records)


async def test_stop_cancels_a_tick_in_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cancel delivered while a tick is in flight must propagate as a
    cancellation, not be logged as another malformed tick."""
    import services.schedule_consumer as cadence

    in_tick = asyncio.Event()

    async def _tick() -> tuple[int, int]:
        in_tick.set()
        await asyncio.Event().wait()  # blocks until cancelled
        return (0, 0)  # pragma: no cover - unreachable once cancelled

    await cadence.stop_schedule_consumer()
    monkeypatch.setattr(cadence, "tick_schedule_consumer", _tick)
    monkeypatch.setattr(cadence, "_interval_s", lambda: 3600)

    await cadence.start_schedule_consumer()
    await asyncio.wait_for(in_tick.wait(), timeout=1.0)
    task = cadence._task

    await cadence.stop_schedule_consumer()

    assert cadence._task is None
    assert task is not None and task.cancelled()
