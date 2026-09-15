"""A resumed scheduled Attempt keeps the same crash-recovery lease as first
reach (#1112, #1124).

`ScheduleAttemptExecutor` gives a first-reach Attempt a finite,
heartbeat-renewed lease through `AttemptExecutionService`. Its resume path
used to construct `RunExecutionService` without `lease_ttl`, so the fresh
Attempt a resume creates got the default `lease_ttl=None` -- no expiry, never
reclaimable. A scheduled Run was therefore crash-recoverable on its first
physical try and could be stranded RUNNING forever after any later
timer/HITL pause, even with #232's general recovery sweep operational.

Same crash-injection style `test_chat_attempt_recovery.py` uses for #1170's
analogous chat-Attempt-lease defect: death is renewals that stop while the
dispatch never returns, the exact shape of a SIGKILLed or partitioned worker,
never an orderly in-process stop.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from maistro.container import Container, create_container
from maistro.graph import Graph, Node
from maistro.graph.nodes import BaseNode, NodeContext, register_node
from maistro.graph.nodes.base import PAUSE_WAITING_ON_JIRA_SUBTASKS, pause_until, resumed_pause
from maistro.runs.consumption import (
    DEFAULT_SCHEDULE_LEASE_TTL,
    ScheduleAttemptExecutor,
    resumable_pause,
)
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.sources import ADMISSION_SOURCE, SCHEDULE_INPUTS_KEY, SCHEDULE_SOURCE
from maistro.types.config import AgentConfig

pytestmark = [pytest.mark.contract("behavioral")]


class _PauseIn(BaseModel):
    marker: str = "m"


class _PauseOut(BaseModel):
    text: str


class _SlowResumeNode(BaseNode[_PauseIn, _PauseOut]):
    """Pauses on first reach; on resume, hangs -- the crash window under test.

    Resumability comes from `PAUSE_WAITING_ON_JIRA_SUBTASKS`, the same
    `RESUME_ON_ELAPSED`-classified reason `test_parked_run_resume.py`'s
    `_PollingPauseNode` uses, so this fixture produces a pause the timer tick
    is willing to re-enter without borrowing that file's shared state.
    """

    kind: ClassVar[str] = "test.resume_lease.slow"
    kind_category: ClassVar = "wait"
    input_schema: ClassVar[type[BaseModel]] = _PauseIn
    output_schema: ClassVar[type[BaseModel]] = _PauseOut
    arrived: ClassVar[asyncio.Event | None] = None

    async def _execute(self, inputs: _PauseIn, ctx: NodeContext) -> _PauseOut:
        if resumed_pause(ctx):
            if type(self).arrived is not None:
                type(self).arrived.set()
            await asyncio.sleep(3600)
            raise AssertionError("the crashed resume never returns")  # pragma: no cover
        pause_until(
            PAUSE_WAITING_ON_JIRA_SUBTASKS,
            resume_at=datetime.now(UTC) - timedelta(seconds=1),
            metadata={},
        )
        return _PauseOut(text="unreachable")


with contextlib.suppress(ValueError):
    register_node(_SlowResumeNode)


async def _container() -> Container:
    return await create_container(AgentConfig(router_api_key="test-key"))


async def _paused_run(container: Container, *, workspace: str) -> tuple[str, Any]:
    """Admit a schedule Run and execute it once via the real first-reach path.

    Built by running the consumer, not by writing a parked row, so this suite
    exercises the actual `execute()` -> pause boundary the resume executor
    reads back.
    """
    root = await container.project_scope_store.create_root(workspace)
    graph = Graph(
        workspace_id=workspace,
        project_id=root.project_id,
        name="scheduled work",
        nodes=[Node(node_id="n1", node_type=_SlowResumeNode.kind)],
    )
    run = await container.run_store.create_run(
        graph,
        provenance={ADMISSION_SOURCE: SCHEDULE_SOURCE, SCHEDULE_INPUTS_KEY: {}},
        initial_status=RunStatus.QUEUED,
    )
    first_reach = ScheduleAttemptExecutor(container.run_store, lease_ttl=timedelta(seconds=30))
    await first_reach.execute(run)
    parked = await container.run_store.get_run(run.run_id)
    assert parked is not None and parked.status in (RunStatus.WAITING, RunStatus.PAUSED)
    return run.run_id, parked


async def _resumable(container: Container, run: Any) -> Any:
    (node_run,) = await container.run_store.list_node_runs(run.run_id)
    attempts = await container.run_store.list_attempts(node_run.node_run_id)
    pause = resumable_pause(node_run, attempts, now=datetime.now(UTC))
    assert pause is not None, "the fixture must produce a timer-resumable pause"
    return pause


class TestResumedAttemptsKeepTheConfiguredLease:
    async def test_a_resumed_attempt_carries_the_same_finite_lease_as_first_reach(self) -> None:
        """#1112/#1124's headline assertion, direct: before the fix, a resumed
        Attempt's lease never expired regardless of the executor's configured
        TTL. After it, the resume path's fresh Attempt carries the same
        finite, expiring lease first reach's does."""
        container = await _container()
        executor = ScheduleAttemptExecutor(container.run_store, lease_ttl=timedelta(seconds=30))
        run_id, parked = await _paused_run(container, workspace="ws-lease-1")
        pause = await _resumable(container, parked)
        _SlowResumeNode.arrived = asyncio.Event()

        worker = asyncio.create_task(executor.resume(parked, pause))
        await _SlowResumeNode.arrived.wait()

        (node_run,) = await container.run_store.list_node_runs(run_id)
        attempts = await container.run_store.list_attempts(node_run.node_run_id)
        resumed_attempt = attempts[-1]
        assert resumed_attempt.status is AttemptStatus.RUNNING
        lease = resumed_attempt.execution_lease
        assert lease is not None
        assert lease.expires_at is not None, (
            "a resumed Attempt must carry the same finite lease first reach "
            "does, or it can never be reclaimed after worker death"
        )

        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

    async def test_the_default_resume_lease_matches_the_configured_ttl(self) -> None:
        """The container's production wiring (`Container.resume_parked_runs`)
        passes no explicit `lease_ttl`, so the constructor default is what
        ships; the resume path must honour it too, not silently fall back to
        none."""
        assert timedelta(seconds=30) == DEFAULT_SCHEDULE_LEASE_TTL
        container = await _container()
        executor = ScheduleAttemptExecutor(container.run_store)
        run_id, parked = await _paused_run(container, workspace="ws-lease-2")
        pause = await _resumable(container, parked)
        _SlowResumeNode.arrived = asyncio.Event()

        worker = asyncio.create_task(executor.resume(parked, pause))
        await _SlowResumeNode.arrived.wait()

        (node_run,) = await container.run_store.list_node_runs(run_id)
        attempts = await container.run_store.list_attempts(node_run.node_run_id)
        lease = attempts[-1].execution_lease
        assert lease is not None and lease.expires_at is not None

        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


class TestACrashedResumeWorkerIsReclaimed:
    @staticmethod
    async def _crashed_mid_resume(container: Container) -> tuple[asyncio.Task[None], Any, Any]:
        """A resume whose worker stops proving it is alive, mid-dispatch.

        Returns the (still pending) worker task, the resumed Run's NodeRun,
        and its durably RUNNING resumed Attempt.
        """
        ttl = timedelta(seconds=0.06)
        executor = ScheduleAttemptExecutor(container.run_store, lease_ttl=ttl)
        run_id, parked = await _paused_run(container, workspace="ws-lease-crash")
        pause = await _resumable(container, parked)
        _SlowResumeNode.arrived = asyncio.Event()

        worker = asyncio.create_task(executor.resume(parked, pause))
        await _SlowResumeNode.arrived.wait()

        (node_run,) = await container.run_store.list_node_runs(run_id)
        attempts = await container.run_store.list_attempts(node_run.node_run_id)
        resumed_attempt = attempts[-1]
        assert resumed_attempt.status is AttemptStatus.RUNNING
        lease = resumed_attempt.execution_lease
        assert lease is not None and lease.expires_at is not None, (
            "the resume executor must opt its Attempt into a TTL, or nothing is reclaimable"
        )

        # Death: renewals stop while the dispatch never returns. The process
        # that could terminalize this Attempt is gone; its heartbeat is too.
        async def _dead(*_args: Any, **_kwargs: Any) -> Any:
            raise ConnectionError("worker is gone")

        container.run_store.renew_lease = _dead  # type: ignore[method-assign]
        await asyncio.sleep(0.15)  # past the TTL, with no successful renewal
        return worker, node_run, resumed_attempt

    async def test_death_during_resume_makes_the_attempt_reclaimable(self) -> None:
        """The full restart contract the issues ask for: pause -> resume ->
        worker dies -> lease expires -> canonical recovery settles/reclaims
        it -> the Run can proceed under the retry policy (here, parked for a
        retry decision, exactly as a first-reach crash parks it)."""
        container = await _container()
        worker, node_run, attempt = await self._crashed_mid_resume(container)

        still = await container.run_store.get_attempt(attempt.attempt_id)
        assert still is not None and still.status is AttemptStatus.RUNNING

        assert await container.recover_abandoned_attempts() == 1

        settled = await container.run_store.get_attempt(attempt.attempt_id)
        assert settled is not None
        assert settled.status is AttemptStatus.CANCELLED, (
            "reclaim is a cancellation, not a failure: the work did not fail, "
            "its worker stopped proving it was alive"
        )
        parked_node = await container.run_store.get_node_run(node_run.node_run_id)
        assert parked_node is not None and parked_node.status is RunStatus.WAITING
        run = await container.run_store.get_run(node_run.run_id)
        assert run is not None and run.status is RunStatus.WAITING

        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

    async def test_repeated_recovery_after_a_resumed_crash_is_idempotent(self) -> None:
        """Two ticks -- or two replicas ticking -- is normal operation. The
        second sweep finds nothing expired and rewrites nothing."""
        container = await _container()
        worker, _node_run, attempt = await self._crashed_mid_resume(container)

        assert await container.recover_abandoned_attempts() == 1
        first = await container.run_store.get_attempt(attempt.attempt_id)

        assert await container.recover_abandoned_attempts() == 0
        second = await container.run_store.get_attempt(attempt.attempt_id)
        assert first is not None and second is not None
        assert second.status is first.status
        assert second.error == first.error

        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
