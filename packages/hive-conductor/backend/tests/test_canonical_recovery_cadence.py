"""Hive ticks the Container's canonical recovery seams in production (#62).

``recover_abandoned_attempts``, ``recover_stranded_chat_admissions`` and
``resume_parked_runs`` are operator-scheduled by design (ADR-019) and had no
production caller: a chat Attempt whose worker died stayed RUNNING forever, and
an elapsed ``RESUME_ON_ELAPSED`` pause never woke. These drive a real SQLite
Container through the engine lookup the cadence uses in production.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.container import Container, create_container
from maistro.graph import Graph, Node
from maistro.graph.nodes import BaseNode, NodeContext, register_node
from maistro.graph.nodes.base import (
    PAUSE_WAITING_ON_JIRA_SUBTASKS,
    pause_until,
    resumed_pause,
)
from maistro.runs.chat_execution import ChatAttemptExecutor
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.sources import ADMISSION_SOURCE, SCHEDULE_INPUTS_KEY, SCHEDULE_SOURCE
from maistro.types.config import AgentConfig

MESSAGES = [{"role": "user", "content": "hi"}]


class _In(BaseModel):
    marker: str = "m"


class _Out(BaseModel):
    text: str


class _PollingNode(BaseNode[_In, _Out]):
    """Parks on an elapsed poll reason, then completes once resumed."""

    kind: ClassVar[str] = "test.hive_canonical_recovery.polling"
    kind_category: ClassVar = "wait"
    input_schema: ClassVar[type[BaseModel]] = _In
    output_schema: ClassVar[type[BaseModel]] = _Out
    resumes: ClassVar[int] = 0

    async def _execute(self, inputs: _In, ctx: NodeContext) -> _Out:
        if resumed_pause(ctx):
            type(self).resumes += 1
            return _Out(text="resumed")
        pause_until(
            PAUSE_WAITING_ON_JIRA_SUBTASKS,
            resume_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        return _Out(text="unreachable")


with contextlib.suppress(ValueError):
    register_node(_PollingNode)


@pytest.fixture
async def container(tmp_path: Path) -> AsyncIterator[Container]:
    built = await create_container(
        AgentConfig(router_api_key="test-key", database_url=f"sqlite:///{tmp_path / 'hive.db'}")
    )
    yield built
    if built.db_pool is not None:
        with contextlib.suppress(Exception):
            await built.db_pool.close()


@pytest.fixture
def booted(monkeypatch: pytest.MonkeyPatch) -> Callable[[Any], None]:
    """Bind a Container to the running engine exactly where the bridge puts it."""
    from services.engine import get_engine

    def _bind(container: Any) -> None:
        monkeypatch.setattr(get_engine(), "_agent_port", SimpleNamespace(container=container))

    return _bind


@pytest.fixture(autouse=True)
async def _cadence_stopped() -> AsyncIterator[None]:
    import services.canonical_recovery as cadence

    await cadence.stop_canonical_recovery()
    yield
    await cadence.stop_canonical_recovery()


async def _eventually(check: Callable[[], Any], *, timeout: float = 5.0) -> None:
    async def _poll() -> None:
        while not await check():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_poll(), timeout=timeout)


async def _crashed_chat_attempt(container: Container) -> tuple[asyncio.Task[None], str, str]:
    """A chat turn whose worker stopped renewing a millisecond-TTL lease."""
    run = await container.chat_admitter.admit(MESSAGES)
    await container.run_store.transition_run(run.run_id, RunStatus.QUEUED)
    await container.run_store.transition_run(run.run_id, RunStatus.RUNNING)
    executor = ChatAttemptExecutor(container.run_store, lease_ttl=timedelta(milliseconds=50))
    arrived = asyncio.Event()

    async def _dispatch() -> dict[str, Any]:
        arrived.set()
        await asyncio.sleep(3600)
        raise AssertionError("the crashed dispatch never returns")

    async def _worker() -> None:
        with contextlib.suppress(BaseException):
            await executor.execute(run_id=run.run_id, messages=MESSAGES, dispatch=_dispatch)

    worker = asyncio.create_task(_worker())
    await arrived.wait()

    async def _dead(*_args: Any, **_kwargs: Any) -> Any:
        raise ConnectionError("worker is gone")

    container.run_store.renew_lease = _dead  # type: ignore[method-assign]
    await asyncio.sleep(0.15)
    (node_run,) = await container.run_store.list_node_runs(run.run_id)
    (attempt,) = await container.run_store.list_attempts(node_run.node_run_id)
    assert attempt.status is AttemptStatus.RUNNING
    return worker, node_run.node_run_id, attempt.attempt_id


async def test_cadence_reclaims_an_abandoned_chat_attempt(
    container: Container, booted: Callable[[Any], None]
) -> None:
    import services.canonical_recovery as cadence

    booted(container)
    worker, node_run_id, attempt_id = await _crashed_chat_attempt(container)

    cadence.start_canonical_recovery()

    # The sweep cancels the Attempt, then reconciles its NodeRun: wait for both,
    # or a read between the two writes sees a half-finished tick.
    async def _reclaimed_and_parked() -> bool:
        attempt = await container.run_store.get_attempt(attempt_id)
        node_run = await container.run_store.get_node_run(node_run_id)
        return (
            attempt is not None
            and attempt.status is AttemptStatus.CANCELLED
            and node_run is not None
            and node_run.status is RunStatus.WAITING
        )

    await _eventually(_reclaimed_and_parked)

    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)


async def _parked_schedule_run(container: Container) -> str:
    workspace = "hive-canonical-recovery"
    root = await container.project_scope_store.create_root(workspace)
    graph = Graph(
        workspace_id=workspace,
        project_id=root.project_id,
        name="scheduled poll",
        nodes=[Node(node_id="n1", node_type=_PollingNode.kind)],
    )
    run = await container.run_store.create_run(
        graph,
        provenance={ADMISSION_SOURCE: SCHEDULE_SOURCE, SCHEDULE_INPUTS_KEY: {"marker": "m"}},
        initial_status=RunStatus.QUEUED,
    )
    assert await container.execute_admitted_runs() == 1
    parked = await container.run_store.get_run(run.run_id)
    assert parked is not None and parked.status in {RunStatus.WAITING, RunStatus.PAUSED}
    (node_run,) = await container.run_store.list_node_runs(run.run_id)
    attempts = await container.run_store.list_attempts(node_run.node_run_id)
    assert attempts[-1].status is AttemptStatus.YIELDED
    return run.run_id


async def test_cadence_resumes_an_elapsed_poll_pause(
    container: Container, booted: Callable[[Any], None]
) -> None:
    import services.canonical_recovery as cadence

    booted(container)
    run_id = await _parked_schedule_run(container)
    _PollingNode.resumes = 0

    await cadence.tick_canonical_recovery()

    run = await container.run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.COMPLETED
    assert _PollingNode.resumes == 1


async def test_one_failing_half_does_not_silence_the_others_or_the_cadence(
    container: Container,
    booted: Callable[[Any], None],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import services.canonical_recovery as cadence

    booted(container)
    run_id = await _parked_schedule_run(container)
    calls = {"abandoned": 0, "chat": 0}
    real_chat = container.recover_stranded_chat_admissions

    async def _broken(**_kwargs: Any) -> int:
        calls["abandoned"] += 1
        raise RuntimeError("store outage")

    async def _chat(**kwargs: Any) -> int:
        calls["chat"] += 1
        return await real_chat(**kwargs)

    monkeypatch.setattr(container, "recover_abandoned_attempts", _broken)
    monkeypatch.setattr(container, "recover_stranded_chat_admissions", _chat)
    monkeypatch.setattr(cadence, "_INTERVAL_S", 0.001)

    with caplog.at_level(logging.INFO, logger="hive.canonical_recovery"):
        cadence.start_canonical_recovery()

        async def _looped() -> bool:
            return calls["abandoned"] >= 2 and calls["chat"] >= 2

        await _eventually(_looped)

    run = await container.run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.COMPLETED
    assert any("abandoned_attempts_tick_failed" in r.message for r in caplog.records)
    assert any("parked_runs=1" in r.message for r in caplog.records)
    assert cadence._task is not None and not cadence._task.done()


async def test_stop_drains_the_half_in_flight_instead_of_cancelling_it(
    booted: Callable[[Any], None],
) -> None:
    """A cancelled Attempt is a *requested* cancellation in core, which ends its
    NodeRun for good, so shutdown must let a resume finish, not cancel it."""
    import services.canonical_recovery as cadence

    entered = asyncio.Event()
    release = asyncio.Event()
    calls = {"abandoned": 0, "chat": 0}

    async def _slow(**_kwargs: Any) -> int:
        calls["abandoned"] += 1
        entered.set()
        await release.wait()
        return 0

    async def _chat(**_kwargs: Any) -> int:
        calls["chat"] += 1
        return 0

    booted(
        SimpleNamespace(recover_abandoned_attempts=_slow, recover_stranded_chat_admissions=_chat)
    )
    cadence.start_canonical_recovery()
    first = cadence._task
    cadence.start_canonical_recovery()
    assert cadence._task is first

    await asyncio.wait_for(entered.wait(), timeout=1.0)
    stopping = asyncio.create_task(cadence.stop_canonical_recovery())
    await asyncio.sleep(0.05)
    assert not stopping.done(), "stop must wait for the half in flight"
    release.set()
    await asyncio.wait_for(stopping, timeout=1.0)

    assert first is not None and first.done() and not first.cancelled()
    assert calls == {"abandoned": 1, "chat": 0}, "no half may start once stopping"
    assert cadence._task is None


async def test_stop_cancels_a_tick_that_outlives_the_grace(
    booted: Callable[[Any], None],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import services.canonical_recovery as cadence

    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def _hang(**_kwargs: Any) -> int:
        entered.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return 0

    monkeypatch.setattr(cadence, "_STOP_GRACE_S", 0.05)
    booted(SimpleNamespace(recover_abandoned_attempts=_hang))
    cadence.start_canonical_recovery()
    first = cadence._task

    await asyncio.wait_for(entered.wait(), timeout=1.0)
    with caplog.at_level(logging.WARNING, logger="hive.canonical_recovery"):
        await cadence.stop_canonical_recovery()

    assert cancelled.is_set()
    assert first is not None and first.cancelled()
    assert cadence._task is None
    assert any("cancelling it" in r.message for r in caplog.records)


async def test_cadence_compensates_a_stranded_chat_admission(
    container: Container,
    booted: Callable[[Any], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chat Run left RUNNING with no NodeRun (a crash between admission and
    the first Attempt) is cancelled by the cadence, not left RUNNING forever."""
    import services.canonical_recovery as cadence

    import maistro.container as container_mod

    booted(container)
    run = await container.chat_admitter.admit(MESSAGES)
    await container.run_store.transition_run(run.run_id, RunStatus.QUEUED)
    await container.run_store.transition_run(run.run_id, RunStatus.RUNNING)
    monkeypatch.setattr(container_mod, "DEFAULT_STRANDED_ADMISSION_AGE", timedelta(0))

    await cadence.tick_canonical_recovery()

    stranded = await container.run_store.get_run(run.run_id)
    assert stranded is not None and stranded.status is RunStatus.CANCELLED
    assert await container.run_store.list_node_runs(run.run_id) == []


async def test_without_a_container_the_cadence_is_a_noop(
    booted: Callable[[Any], None],
) -> None:
    import services.canonical_recovery as cadence

    booted(None)
    await cadence.tick_canonical_recovery()

    cadence.start_canonical_recovery()
    await asyncio.sleep(0.01)
    assert cadence._task is not None and not cadence._task.done()


async def test_engine_start_and_stop_bracket_the_cadence() -> None:
    import services.canonical_recovery as cadence
    import services.dag_recovery as dag_recovery
    from services.engine import EngineService

    class _Settings:
        maistro_router_api_key = ""
        maistro_base_url = "http://localhost:8000"
        hive_mode = "production"
        hive_default_workspace_id = "default"

    svc = EngineService()
    await svc.start(_Settings())  # type: ignore[arg-type]
    try:
        assert cadence._task is not None and not cadence._task.done()
    finally:
        await svc.stop()
    assert cadence._task is None
    await dag_recovery.stop_dag_recovery()
