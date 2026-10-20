"""Harness timer re-entry through canonical Runs and durable Invocation evidence.

These use a fake remote provider, not a fake Invocation or Graph executor.
SQLite and PostgreSQL cases reconstruct both persistence and node collaborators;
that is store-reconstruction evidence, not an OS-process-kill claim.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import aiosqlite
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    binding_scope_policy,
    new_effect_context,
    new_postgres_effect_context,
    new_sqlite_effect_context,
)
from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
    SqliteGraphContinuationStore,
    resume_due_graph_runs,
    run_durable_graph,
)
from maistro.graph.durable_runs.pg_continuation import PgGraphContinuationStore
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.harness import HarnessHandle, HarnessRequest, HarnessResult
from maistro.graph.nodes.agent_spawn_harness import AgentSpawnHarnessNode
from maistro.projects.pg_scope_store import PgProjectScopeStore
from maistro.projects.scope_store import InMemoryProjectScopeStore, ProjectScopeStore
from maistro.runs import InMemoryRunStore, RunStatus
from maistro.runs.pg_store import PgRunStore
from maistro.runs.sqlite_store import SqliteRunStore
from maistro.runs.store import RunStore

pytestmark = pytest.mark.contract("behavioral")
_WORKSPACE = "ws-harness-timer"


@dataclass
class Clock:
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    value: datetime = field(init=False)

    def __post_init__(self) -> None:
        self.value = self.started_at


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    import maistro.capabilities.invocation as invocation
    import maistro.graph.durable_runs.attempt_executor as attempts
    import maistro.graph.nodes.agent_spawn_harness as harness_node

    clock = Clock()

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return (
                clock.value.astimezone(tz) if tz is not None else clock.value.replace(tzinfo=None)
            )

    monkeypatch.setattr(invocation, "datetime", FixedDateTime)
    monkeypatch.setattr(attempts, "datetime", FixedDateTime)
    monkeypatch.setattr(harness_node, "now_utc", lambda: clock.value, raising=False)
    return clock


@dataclass
class Remote:
    """Remote state outlives every freshly composed local adapter."""

    answers: list[HarnessResult | None] = field(default_factory=list)
    dispatches: list[HarnessRequest] = field(default_factory=list)
    polls: list[str] = field(default_factory=list)


class Adapter:
    def __init__(self, remote: Remote) -> None:
        self.remote = remote

    async def dispatch(self, request: HarnessRequest) -> HarnessHandle:
        self.remote.dispatches.append(request)
        return HarnessHandle(handle_id="durable-handle", harness_type="proof")

    async def poll(self, handle: HarnessHandle) -> HarnessResult | None:
        self.remote.polls.append(handle.handle_id)
        return self.remote.answers.pop(0) if self.remote.answers else None

    async def cancel(self, handle: HarnessHandle) -> None:
        raise AssertionError("local wait expiry does not prove or request remote cancellation")


@dataclass
class Spine:
    runs: RunStore
    graph_store: CanonicalDurableRunStore
    effects: CapabilityEffectContext
    project_id: str
    binding_id: str
    reconstruct: Callable[
        [], Awaitable[tuple[RunStore, CanonicalDurableRunStore, CapabilityEffectContext]]
    ]


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def spine(
    request: pytest.FixtureRequest, tmp_path: Any, pg_pool: Any
) -> AsyncIterator[Spine]:
    if request.param == "postgres" and pg_pool is None:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            pytest.fail("MAISTRO_REQUIRE_PG_LEGS is set but PostgreSQL is not configured")
        pytest.skip("PostgreSQL service is not configured")
    projects: ProjectScopeStore = (
        PgProjectScopeStore(pg_pool) if request.param == "postgres" else InMemoryProjectScopeStore()
    )
    project = await projects.create_root(_WORKSPACE)
    # The shared PostgreSQL fixture does not truncate capability Bindings.
    # Recomposition reuses this fixture's identity; other cases cannot collide.
    binding_id = f"harness-timer-binding-{uuid4().hex}"
    memory_runs = InMemoryRunStore(project_store=projects)
    memory_continuations = InMemoryGraphContinuationStore()
    memory_effects = new_effect_context(policy_evaluator=binding_scope_policy)
    async with AsyncExitStack() as stack:

        async def compose() -> tuple[RunStore, CanonicalDurableRunStore, CapabilityEffectContext]:
            if request.param == "sqlite":
                conn = await stack.enter_async_context(aiosqlite.connect(tmp_path / "harness.db"))
                runs: RunStore = SqliteRunStore(conn, project_store=projects)
                await runs.ensure_schema()  # type: ignore[attr-defined]
                continuations = SqliteGraphContinuationStore(conn)
                await continuations.ensure_schema()
                effects = await new_sqlite_effect_context(
                    conn, policy_evaluator=binding_scope_policy
                )
                return runs, CanonicalDurableRunStore(runs, continuations), effects
            if request.param == "postgres":
                runs = PgRunStore(pg_pool, project_store=projects)
                effects = await new_postgres_effect_context(
                    pg_pool, policy_evaluator=binding_scope_policy
                )
                return (
                    runs,
                    CanonicalDurableRunStore(runs, PgGraphContinuationStore(pg_pool)),
                    effects,
                )
            effects = new_effect_context(
                binding_store=memory_effects.bindings,
                invocation_store=memory_effects.invocation_store,
                event_store=memory_effects.event_store,
                policy_evaluator=binding_scope_policy,
            )
            return memory_runs, CanonicalDurableRunStore(memory_runs, memory_continuations), effects

        runs, graph_store, effects = await compose()
        await effects.bindings.put(
            Binding(
                binding_id=binding_id,
                workspace_id=_WORKSPACE,
                project_id=project.project_id,
                node_id="harness",
                capability="harness_runner",
                provider_name="proof",
            )
        )
        yield Spine(runs, graph_store, effects, project.project_id, binding_id, compose)


def _resolver(effects: CapabilityEffectContext, remote: Remote) -> Any:
    return lambda *_: AgentSpawnHarnessNode(
        adapters={"proof": Adapter(remote)}, effect_context=effects
    )


async def _start(spine: Spine, remote: Remote, *, timeout: int = 60) -> DurableRunRecord:
    graph = Graph(
        graph_id="harness-timer-graph",
        name="Harness timer recovery",
        workspace_id=_WORKSPACE,
        project_id=spine.project_id,
        nodes=[
            Node(
                node_id="harness",
                node_type="agent.spawn_harness",
                inputs={
                    "harness_type": "proof",
                    "binding_id": spine.binding_id,
                    "task": "bounded remote work",
                    "timeout_seconds": timeout,
                },
            )
        ],
    )
    admitted = await spine.runs.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id="test-operator"
    )
    return await run_durable_graph(
        graph,
        store=spine.graph_store,
        run_store=spine.runs,
        run_id=admitted.run_id,
        node_resolver=_resolver(spine.effects, remote),
        actor_principal_id="test-operator",
    )


async def _tick(
    spine: Spine, record: DurableRunRecord, remote: Remote, clock: Clock
) -> DurableRunRecord:
    runs, graph_store, effects = await spine.reconstruct()
    changed = await resume_due_graph_runs(
        store=graph_store,
        run_store=runs,
        now=clock.value,
        node_resolver_factory=lambda _: _resolver(effects, remote),
    )
    assert changed == 1
    loaded = await graph_store.get(record.run_id)
    assert loaded is not None
    return loaded


def _pause(record: DurableRunRecord) -> Any:
    return record.graph_state.metadata["pauses"]["harness"]["metadata"]


async def test_dispatch_checkpoints_first_poll_before_any_remote_read(
    spine: Spine, clock: Clock
) -> None:
    remote = Remote()
    parked = await _start(spine, remote)
    assert parked.status is RunStatus.WAITING
    assert parked.resume_at == clock.started_at + timedelta(seconds=10)
    assert _pause(parked)["observation_index"] == 0
    assert _pause(parked)["deadline_at"] == (clock.started_at + timedelta(seconds=60)).isoformat()
    assert len(remote.dispatches) == 1
    assert remote.polls == []


async def test_fresh_composition_polls_and_completes_without_redispatch(
    spine: Spine, clock: Clock
) -> None:
    remote = Remote(
        answers=[
            HarnessResult(handle_id="durable-handle", success=True, output="durable completion")
        ]
    )
    parked = await _start(spine, remote)
    clock.value += timedelta(seconds=10)
    completed = await _tick(spine, parked, remote, clock)
    assert completed.status is RunStatus.COMPLETED
    assert completed.node_runs[0].result["output"] == "durable completion"
    assert len(remote.dispatches) == 1
    assert remote.polls == ["durable-handle"]
    assert len(completed.attempts) == 2


async def test_pending_observation_advances_once_with_the_original_deadline(
    spine: Spine, clock: Clock
) -> None:
    remote = Remote(
        answers=[None, HarnessResult(handle_id="durable-handle", success=True, output="done")]
    )
    parked = await _start(spine, remote)
    original_deadline = _pause(parked)["deadline_at"]
    clock.value += timedelta(seconds=10)
    waiting = await _tick(spine, parked, remote, clock)
    assert waiting.status is RunStatus.WAITING
    assert _pause(waiting)["observation_index"] == 1
    assert _pause(waiting)["deadline_at"] == original_deadline
    assert waiting.resume_at == clock.started_at + timedelta(seconds=20)
    assert remote.polls == ["durable-handle"]
    clock.value += timedelta(seconds=10)
    completed = await _tick(spine, waiting, remote, clock)
    assert completed.status is RunStatus.COMPLETED
    assert remote.polls == ["durable-handle", "durable-handle"]
    assert len(remote.dispatches) == 1


async def test_elapsed_fixed_deadline_fails_locally_without_poll_or_remote_cancel(
    spine: Spine, clock: Clock
) -> None:
    remote = Remote()
    parked = await _start(spine, remote, timeout=5)
    assert parked.resume_at == clock.started_at + timedelta(seconds=5)
    clock.value += timedelta(seconds=5)
    expired = await _tick(spine, parked, remote, clock)
    assert expired.status is RunStatus.FAILED
    assert "HarnessWaitTimedOut" in (expired.run.error or "")
    assert remote.polls == []
    assert len(remote.dispatches) == 1


async def test_two_recovery_stores_cannot_poll_the_same_observation_twice(
    spine: Spine, clock: Clock
) -> None:
    remote = Remote(
        answers=[HarnessResult(handle_id="durable-handle", success=True, output="once")]
    )
    parked = await _start(spine, remote)
    clock.value += timedelta(seconds=10)
    first = await spine.reconstruct()
    second = await spine.reconstruct()

    async def recover(
        composed: tuple[RunStore, CanonicalDurableRunStore, CapabilityEffectContext],
    ) -> int:
        runs, store, effects = composed
        return await resume_due_graph_runs(
            store=store,
            run_store=runs,
            now=clock.value,
            node_resolver_factory=lambda _: _resolver(effects, remote),
        )

    outcomes = await asyncio.gather(recover(first), recover(second))
    completed = await first[1].get(parked.run_id)
    assert completed is not None and completed.status is RunStatus.COMPLETED
    assert sum(outcomes) >= 1
    assert len(remote.dispatches) == 1
    assert remote.polls == ["durable-handle"]
    assert len(completed.attempts) == 2
    assert await recover(second) == 0
    assert remote.polls == ["durable-handle"]


@pytest.mark.parametrize(
    "contender_window", ["after_claim", "after_initial_guard", "after_reactivation"]
)
async def test_waiting_claim_is_not_stolen_before_canonical_reactivation(
    spine: Spine, clock: Clock, monkeypatch: pytest.MonkeyPatch, contender_window: str
) -> None:
    """Hold real persisted claims at the three previously unguarded read windows.

    The PostgreSQL parameter uses the canonical stores. SQLite is only the
    existing race harness; neither case claims OS-process-kill evidence.
    """
    from maistro.graph.durable_runs import attempt_executor, recovery

    # Tick time is deliberately unrelated to the process wall clock. A
    # projection repair must not expire this tick's live claim on its own.
    clock.started_at = clock.value = datetime(2001, 1, 1, tzinfo=UTC)
    remote = Remote(
        answers=[HarnessResult(handle_id="durable-handle", success=True, output="once")]
    )
    parked = await _start(spine, remote)
    clock.value += timedelta(seconds=10)
    owner_spine = await spine.reconstruct()
    contender_spine = await spine.reconstruct()
    claimed = asyncio.Event()
    release_owner = asyncio.Event()
    initial_guard_passed = asyncio.Event()
    release_contender = asyncio.Event()
    original_reactivate = attempt_executor._reactivate_for_walk
    original_spine = attempt_executor.traversal._canonical_spine
    original_candidate = recovery._resume_due_candidate
    original_reconcile = attempt_executor._reconcile_orphaned_attempts
    reconciled_by: list[str] = []

    async def record_reconciler(*args: Any, **kwargs: Any) -> DurableRunRecord:
        task = asyncio.current_task()
        assert task is not None
        reconciled_by.append(task.get_name())
        return await original_reconcile(*args, **kwargs)

    async def hold_stale_listing(*args: Any, **kwargs: Any) -> bool:
        task = asyncio.current_task()
        if (
            contender_window != "after_initial_guard"
            and task is not None
            and task.get_name() == "claim-contender"
        ):
            initial_guard_passed.set()
            await release_contender.wait()
        return await original_candidate(*args, **kwargs)

    async def hold_owner(record: DurableRunRecord, run_store: Any) -> DurableRunRecord:
        task = asyncio.current_task()
        if task is not None and task.get_name() == "claim-owner":
            if contender_window == "after_reactivation":
                record = await original_reactivate(record, run_store)
            claimed.set()
            await release_owner.wait()
        return await original_reactivate(record, run_store)

    async def hold_contender(record: DurableRunRecord, run_store: Any) -> Any:
        task = asyncio.current_task()
        if (
            contender_window == "after_initial_guard"
            and not initial_guard_passed.is_set()
            and task is not None
            and task.get_name() == "claim-contender"
        ):
            initial_guard_passed.set()
            await release_contender.wait()
        return await original_spine(record, run_store)

    monkeypatch.setattr(attempt_executor, "_reactivate_for_walk", hold_owner)
    monkeypatch.setattr(attempt_executor.traversal, "_canonical_spine", hold_contender)
    monkeypatch.setattr(recovery, "_resume_due_candidate", hold_stale_listing)
    monkeypatch.setattr(attempt_executor, "_reconcile_orphaned_attempts", record_reconciler)

    async def recover(
        composed: tuple[RunStore, CanonicalDurableRunStore, CapabilityEffectContext],
    ) -> int:
        runs, store, effects = composed
        return await resume_due_graph_runs(
            store=store,
            run_store=runs,
            now=clock.value,
            node_resolver_factory=lambda _: _resolver(effects, remote),
        )

    contender = None
    owner = None
    try:
        async with asyncio.timeout(10):
            contender = asyncio.create_task(recover(contender_spine), name="claim-contender")
            await initial_guard_passed.wait()
            owner = asyncio.create_task(recover(owner_spine), name="claim-owner")
            await claimed.wait()
            before = await contender_spine[1].get(parked.run_id)
            expected_status = (
                RunStatus.RUNNING if contender_window == "after_reactivation" else RunStatus.WAITING
            )
            assert before is not None and before.status is expected_status
            assert before.resume_at == clock.value + attempt_executor.GRAPH_RECOVERY_CLAIM_TTL
            release_contender.set()
            assert await contender == 0
            assert "claim-contender" not in reconciled_by
            after = await contender_spine[1].get(parked.run_id)
            assert after == before
            assert remote.polls == []
    finally:
        release_contender.set()
        release_owner.set()
        results = await asyncio.gather(
            *(task for task in (owner, contender) if task is not None), return_exceptions=True
        )
    assert results[0] == 1
    completed = await owner_spine[1].get(parked.run_id)
    assert completed is not None and completed.status is RunStatus.COMPLETED
    assert len(remote.dispatches) == 1
    assert remote.polls == ["durable-handle"]
    assert len(completed.attempts) == 2


async def test_future_timer_is_not_a_claim_even_when_deadlines_match(
    spine: Spine, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-parking releases ownership without forbidding existing direct resumes."""
    from maistro.graph.durable_runs import attempt_executor, resume_durable_graph
    from maistro.graph.durable_runs.types import RECOVERY_CLAIM_UNTIL_KEY

    monkeypatch.setattr(attempt_executor, "GRAPH_RECOVERY_CLAIM_TTL", timedelta(seconds=10))
    remote = Remote()
    parked = await _start(spine, remote)
    assert parked.resume_at == clock.value + attempt_executor.GRAPH_RECOVERY_CLAIM_TTL
    assert RECOVERY_CLAIM_UNTIL_KEY not in parked.graph_state.metadata
    runs, store, effects = await spine.reconstruct()
    resumed = await resume_durable_graph(
        parked.run_id, store=store, run_store=runs, node_resolver=_resolver(effects, remote)
    )
    assert resumed.status is RunStatus.WAITING
    assert resumed.resume_at == parked.resume_at
    assert RECOVERY_CLAIM_UNTIL_KEY not in resumed.graph_state.metadata
    assert len(resumed.attempts) == 1
    assert remote.polls == []


@pytest.mark.parametrize("reactivated", [False, True])
async def test_expired_marked_waiting_claim_recovers_without_redispatch(
    spine: Spine, clock: Clock, monkeypatch: pytest.MonkeyPatch, reactivated: bool
) -> None:
    from maistro.graph.durable_runs import attempt_executor
    from maistro.graph.durable_runs.types import RECOVERY_CLAIM_UNTIL_KEY

    class ProcessLost(BaseException):
        pass

    remote = Remote(
        answers=[HarnessResult(handle_id="durable-handle", success=True, output="once")]
    )
    parked = await _start(spine, remote, timeout=300)
    clock.value += timedelta(seconds=10)

    original_reactivate = attempt_executor._reactivate_for_walk

    async def lose_after_claim(record: DurableRunRecord, run_store: Any) -> DurableRunRecord:
        if reactivated:
            await original_reactivate(record, run_store)
        raise ProcessLost

    with monkeypatch.context() as patch:
        patch.setattr(attempt_executor, "_reactivate_for_walk", lose_after_claim)
        with pytest.raises(ProcessLost):
            await _tick(spine, parked, remote, clock)
    claimed = await spine.graph_store.get(parked.run_id)
    expected_status = RunStatus.RUNNING if reactivated else RunStatus.WAITING
    assert claimed is not None and claimed.status is expected_status
    assert claimed.resume_at is not None
    assert claimed.graph_state.metadata[RECOVERY_CLAIM_UNTIL_KEY] == claimed.resume_at.isoformat()
    clock.value = claimed.resume_at
    completed = await _tick(spine, parked, remote, clock)
    assert completed.status is RunStatus.COMPLETED
    assert len(remote.dispatches) == 1
    assert remote.polls == ["durable-handle"]
    assert len(completed.attempts) == 2
