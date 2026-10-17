"""ADR-018: TaskRecord upserts at the queue's submit/update_status boundaries.

The contract has three edges: no DB configured → the queue behaves exactly as
before; DB configured → submit and every status change upsert a snapshot; a
failing write is logged and swallowed, never surfaced to the caller.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import maistro.tasks.queue as queue_mod
from maistro.memory.store import TaskRecord
from maistro.observability.metrics import active_tasks
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.tasks.admission import TaskRunAdmitter
from maistro.tasks.models import TaskCreate, TaskProgress, TaskResponse, TaskResult, TaskStatus
from maistro.tasks.queue import TaskQueue


class _FakeSession:
    def __init__(self, sink: list[Any], *, fail: bool = False) -> None:
        self._sink = sink
        self._fail = fail

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def merge(self, record: Any) -> Any:
        if self._fail:
            raise RuntimeError("synthetic database outage")
        self._sink.append(record)
        return record

    async def commit(self) -> None:
        return None


def _install_factory(monkeypatch: pytest.MonkeyPatch, *, fail: bool = False) -> list[Any]:
    sink: list[Any] = []
    monkeypatch.setattr(
        queue_mod,
        "get_async_session_factory",
        lambda: lambda: _FakeSession(sink, fail=fail),
    )
    return sink


async def _drain(queue: TaskQueue) -> None:
    while queue._persist_writes:
        await asyncio.gather(*queue._persist_writes)


async def test_no_database_keeps_queue_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue_mod, "get_async_session_factory", lambda: None)
    queue = TaskQueue()
    task = await queue.submit(TaskCreate(description="offline"))
    assert await queue.update_status(task.task_id, TaskStatus.PLANNING)
    assert queue._persist_writes == set()


async def test_submit_and_status_changes_upsert_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = _install_factory(monkeypatch)
    queue = TaskQueue()

    task = await queue.submit(
        TaskCreate(description="persist me", workspace="ws"),
        user_id="alice",
        service_principal_id="conductor",
        delegation_id="delegation-1",
        actor_kind="user",
    )
    await queue.update_status(task.task_id, TaskStatus.PLANNING)
    await queue.update_status(task.task_id, TaskStatus.CODING)
    await queue.update_status(task.task_id, TaskStatus.COMPLETED)
    await _drain(queue)

    assert [record.status for record in sink] == [
        "queued",
        "planning",
        "coding",
        "completed",
    ]
    final = sink[-1]
    assert final.id == task.task_id
    assert final.description == "persist me"
    assert final.workspace == "ws"
    assert final.user_id == "alice"
    assert final.service_principal_id == "conductor"
    assert final.delegation_id == "delegation-1"
    assert final.actor_kind == "user"
    # Aware UTC, not naive wall-clock. The `_naive()` helper that stripped
    # tzinfo went away with #122: the columns are TIMESTAMPTZ now, and a naive
    # value written into one is interpreted in whatever the server's TimeZone
    # happens to be — correct on a UTC server and silently wrong elsewhere.
    assert final.started_at is not None and final.started_at.tzinfo is not None
    assert final.started_at.utcoffset() == timedelta(0)
    assert final.completed_at is not None and final.completed_at.tzinfo is not None
    assert final.completed_at.utcoffset() == timedelta(0)


async def test_rejected_transition_persists_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = _install_factory(monkeypatch)
    queue = TaskQueue()
    task = await queue.submit(TaskCreate(description="x"))
    await _drain(queue)
    submitted = len(sink)

    assert not await queue.update_status(task.task_id, TaskStatus.QUEUED)
    await _drain(queue)
    assert len(sink) == submitted


@pytest.mark.parametrize(
    "terminal", [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]
)
async def test_settle_terminal_receipt_persists_canonical_outcome_and_notifies(
    monkeypatch: pytest.MonkeyPatch, terminal: TaskStatus
) -> None:
    """An accepted redundant transition must not replace canonical timestamps.

    The fake session measures the queue's ordered write snapshots, not database
    durability or cross-replica convergence. The Run uses the real store and
    lifecycle; only the task receipt's clock differs from its authority.
    """
    sink = _install_factory(monkeypatch)
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    queue = TaskQueue(admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=root.project_id))
    task = await queue.submit(TaskCreate(description="canonical terminal projection"))
    assert await queue.update_status(task.task_id, TaskStatus.PLANNING)
    assert await queue.update_status(task.task_id, TaskStatus.CODING)
    assert task.run_id is not None
    running = await runs.get_run(task.run_id)
    assert running is not None and running.started_at is not None
    started = running.started_at
    finished = started
    run = await runs.transition_run(
        task.run_id,
        RunStatus(terminal.value),
        at=finished,
        result={"files_changed": ["hello.py"]} if terminal is TaskStatus.COMPLETED else None,
        error="canonical failure" if terminal is TaskStatus.FAILED else None,
    )
    queue.set_result(task.task_id, TaskResult(files_changed=["stale.py"], error="old outcome"))
    assert await queue.update_status(task.task_id, terminal)
    assert task.completed_at != run.finished_at
    gauge = sum(float(sample["value"]) for sample in active_tasks.collect())
    waiter = asyncio.create_task(queue.wait_for_update(task.task_id))
    await asyncio.sleep(0)

    queue.settle_terminal_receipt(task.task_id, run=run)

    await asyncio.wait_for(waiter, timeout=1)
    assert await queue.drain_persistence() == 0
    assert task.started_at == started
    assert task.completed_at == finished
    expected = (
        TaskResult(files_changed=["hello.py"])
        if terminal is TaskStatus.COMPLETED
        else TaskResult(error="canonical failure")
        if terminal is TaskStatus.FAILED
        else None
    )
    assert task.result == expected
    assert sink[-1].status == terminal.value
    assert sink[-1].started_at == started
    assert sink[-1].completed_at == finished
    assert sink[-1].result == (expected.model_dump() if expected is not None else None)
    assert sum(float(sample["value"]) for sample in active_tasks.collect()) == gauge
    queue.settle_terminal_receipt(task.task_id, run=run)
    assert await queue.drain_persistence() == 0
    assert sum(float(sample["value"]) for sample in active_tasks.collect()) == gauge


@pytest.mark.parametrize("missing", [False, True])
async def test_settle_terminal_receipt_does_not_create_or_terminalize_a_receipt(
    monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    sink = _install_factory(monkeypatch)
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    queue = TaskQueue(admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=root.project_id))
    task = await queue.submit(TaskCreate(description="still locally queued"))
    assert task.run_id is not None
    run = await runs.transition_run(task.run_id, RunStatus.CANCELLED)
    assert await queue.drain_persistence() == 0
    before = task.model_dump()
    written = len(sink)

    queue.settle_terminal_receipt("absent" if missing else task.task_id, run=run)

    assert await queue.drain_persistence() == 0
    assert task.model_dump() == before
    assert len(sink) == written
    assert queue.get("absent") is None


async def test_settle_terminal_receipt_rejects_a_different_canonical_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sink = _install_factory(monkeypatch)
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    queue = TaskQueue(admitter=TaskRunAdmitter(runs, workspace_id="w1", project_id=root.project_id))
    task = await queue.submit(TaskCreate(description="first canonical identity"))
    other = await queue.submit(TaskCreate(description="another canonical identity"))
    assert await queue.update_status(task.task_id, TaskStatus.CANCELLED)
    assert other.run_id is not None
    other_run = await runs.transition_run(other.run_id, RunStatus.CANCELLED, error="other outcome")
    assert await queue.drain_persistence() == 0
    before = task.model_dump()
    written = len(sink)

    queue.settle_terminal_receipt(task.task_id, run=other_run)

    assert await queue.drain_persistence() == 0
    assert task.model_dump() == before
    assert len(sink) == written


async def test_database_failure_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_factory(monkeypatch, fail=True)
    queue = TaskQueue()
    task = await queue.submit(TaskCreate(description="doomed write"))
    assert await queue.update_status(task.task_id, TaskStatus.PLANNING)
    await _drain(queue)
    # The queue's own state is authoritative and untouched by the DB outage.
    stored = queue.get(task.task_id)
    assert stored is not None and stored.status is TaskStatus.PLANNING


# --- review findings, locked ---------------------------------------------------


async def test_a_finished_task_persists_with_its_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner transitions to COMPLETED before attaching the result, so
    persisting only on status change stored every finished task with a NULL
    result — a durable row that answers neither an audit nor a recovery."""
    sink = _install_factory(monkeypatch)
    queue = TaskQueue()
    task = await queue.submit(TaskCreate(description="work"))
    await queue.update_status(task.task_id, TaskStatus.PLANNING)
    await queue.update_status(task.task_id, TaskStatus.CODING)
    await queue.update_status(task.task_id, TaskStatus.COMPLETED)
    queue.set_result(task.task_id, TaskResult(files_changed=["a.py"]))
    await _drain(queue)

    final = sink[-1]
    assert final.status == "completed"
    assert final.result is not None
    assert final.result["files_changed"] == ["a.py"]


async def test_progress_updates_are_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    sink = _install_factory(monkeypatch)
    queue = TaskQueue()
    task = await queue.submit(TaskCreate(description="work"))
    queue.update_progress(task.task_id, TaskProgress(current="halfway"))
    await _drain(queue)
    assert sink[-1].progress["current"] == "halfway"


async def test_writes_for_one_task_commit_in_state_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Independent sessions can commit in any order. A slow `queued` merge
    landing after `completed` would regress the row to an older status, so
    each task's writes are chained."""
    commits: list[str] = []

    class _OrderedSession:
        def __init__(self, status_delays: dict[str, float]) -> None:
            self._delays = status_delays
            self._pending: Any = None

        async def __aenter__(self) -> _OrderedSession:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def merge(self, record: Any) -> Any:
            self._pending = record
            # The first write is slow; a later one would overtake it if the
            # writes were not chained.
            await asyncio.sleep(self._delays.get(record.status, 0.0))
            return record

        async def commit(self) -> None:
            commits.append(self._pending.status)

    delays = {"queued": 0.05}
    monkeypatch.setattr(
        queue_mod, "get_async_session_factory", lambda: lambda: _OrderedSession(delays)
    )

    queue = TaskQueue()
    task = await queue.submit(TaskCreate(description="racy"))
    await queue.update_status(task.task_id, TaskStatus.PLANNING)
    await queue.update_status(task.task_id, TaskStatus.CODING)
    await _drain(queue)

    assert commits == ["queued", "planning", "coding"]


async def test_recover_requeues_delegated_receipts_with_their_identity() -> None:
    """A restart rebuilds receipts from each Run's committed payload (#1114),
    keeping the originating-principal evidence (#1057) exactly as admitted:
    the same run_id, the same delegation, no invented user, and per-user
    visibility still isolating one user's task from another's."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    project = await projects.create(
        workspace_id="w1", parent_project_id=root.project_id, name="Tasks"
    )
    runs = InMemoryRunStore(project_store=projects)
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)

    async def admit_for(user: str, delegation: str, description: str) -> TaskResponse:
        receipt = TaskResponse(
            task_id=TaskResponse.new_id(),
            status=TaskStatus.QUEUED,
            description=description,
            workspace="/tmp/maistro-workspace",
            user_id=user,
            service_principal_id="conductor",
            delegation_id=delegation,
            actor_kind="user",
            tier=2,
            session_id=f"{user}-session",
            created_at=datetime(2026, 9, 8, tzinfo=UTC),
        )
        receipt.run_id = await admitter.admit(receipt, workspace_id="w1")
        return receipt

    alice = await admit_for("alice", "alice-delegation", "Alice's work")
    bob = await admit_for("bob", "bob-delegation", "Bob's work")

    # ...process death here: a bare restarted queue knows nothing but the store.
    restarted = TaskQueue()
    assert await restarted.recover(runs) == 2

    recovered = restarted.get(alice.task_id, user_id="alice")
    assert recovered is not None
    assert recovered.run_id == alice.run_id
    assert recovered.user_id == "alice"
    assert recovered.service_principal_id == "conductor"
    assert recovered.delegation_id == "alice-delegation"
    assert recovered.actor_kind == "user"

    # Service and user principals stay separately inspectable on the Run
    # itself, not just on the rebuilt receipt.
    run = await runs.get_run(alice.run_id or "")
    assert run is not None
    assert run.actor_principal_id == "alice"
    assert run.provenance["user_id"] == "alice"
    assert run.provenance["service_principal_id"] == "conductor"
    assert run.provenance["delegation_id"] == "alice-delegation"
    assert run.provenance["actor_kind"] == "user"

    # The restart admitted nothing new: exactly the two Runs admission wrote.
    still_queued = await runs.list_by_status(RunStatus.QUEUED, limit=10)
    assert {item.run_id for item in still_queued} == {alice.run_id, bob.run_id}

    # Two users behind one service bridge stay distinguishable after restart.
    assert restarted.get(alice.task_id, user_id="bob") is None
    assert restarted.get(bob.task_id, user_id="alice") is None

    # Dispatch intent is rebuilt for both receipts, and only those.
    dispatched = {await restarted.next_task() for _ in range(2)}
    assert dispatched == {alice.task_id, bob.task_id}
    assert restarted._pending.empty()


async def test_recover_skips_receipts_the_live_queue_still_holds() -> None:
    """A restart never double-counts a receipt the live queue still holds."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    project = await projects.create(
        workspace_id="w1", parent_project_id=root.project_id, name="Tasks"
    )
    runs = InMemoryRunStore(project_store=projects)
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    queue = TaskQueue(admitter=admitter)
    task = await queue.submit(TaskCreate(description="live"), user_id="alice")

    assert await queue.recover(runs) == 0
    assert queue.get(task.task_id, user_id="alice") is not None


async def test_a_corrupt_persisted_receipt_never_answers_a_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The durable-receipt replay path fails closed on an unreadable row:
    it returns None (falling through to stored-request reconstruction) rather
    than reviving a receipt with no attributable actor."""

    class _RowSession:
        async def __aenter__(self) -> _RowSession:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, model: Any, task_id: str) -> TaskRecord:
            return TaskRecord(
                id=task_id,
                run_id="some-run",
                user_id="",
                actor_kind="user",
                status="queued",
                description="ownerless row",
                workspace="/tmp/maistro-workspace",
            )

    monkeypatch.setattr(queue_mod, "get_async_session_factory", lambda: lambda: _RowSession())
    queue = TaskQueue()

    assert await queue._persisted_receipt("row-1") is None

    class _ForgedKindSession(_RowSession):
        async def get(self, model: Any, task_id: str) -> TaskRecord:
            return TaskRecord(
                id=task_id,
                run_id="some-run",
                user_id="alice",
                actor_kind="agent",
                status="queued",
                description="row with an impossible actor",
                workspace="/tmp/maistro-workspace",
            )

    monkeypatch.setattr(
        queue_mod, "get_async_session_factory", lambda: lambda: _ForgedKindSession()
    )
    assert await queue._persisted_receipt("row-1") is None

    class _MissingRowSession(_RowSession):
        async def get(self, model: Any, task_id: str) -> TaskRecord | None:
            return None

    monkeypatch.setattr(
        queue_mod, "get_async_session_factory", lambda: lambda: _MissingRowSession()
    )
    # A missing durable row is a fall-through to the stored-request
    # reconstruction, never an error the replay has to answer for.
    assert await queue._persisted_receipt("row-1") is None

    class _BrokenSession(_RowSession):
        async def get(self, model: Any, task_id: str) -> TaskRecord:
            raise RuntimeError("synthetic outage")

    monkeypatch.setattr(queue_mod, "get_async_session_factory", lambda: lambda: _BrokenSession())
    assert await queue._persisted_receipt("row-1") is None
