"""#41/#1176 regression: a durable TaskRecord row must not strand the replay.

The idempotency replay (``TaskQueue._replay_receipt``) answers a reconciling
retry from three sources: the live in-memory receipt, the durable TaskRecord
row (ADR-018), or the claim's stored request. An earlier round let the durable
row answer the replay outright — but a row only proves the receipt was once
persisted, not that any queue still holds the work. The row is written inside
``_enqueue`` *before* the queue entry lands, so a process death (or a replica
answering the retry) between the two left every later replay returning
"queued" for a canonical Run that no queue would ever run: stranded, and
invisible to recovery because recovery had already run.

These tests pin the repaired contract: the durable row stays the receipt's
identity source (#1057 principal evidence), and the resume gate —
``record_transition`` then ``_enqueue`` — still decides dispatch, exactly as
it already did for the reconstructed path. The first test fails against the
early-return (empty ``_tasks``, empty ``_pending``, Run QUEUED forever).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

import maistro.tasks.queue as queue_mod
from maistro.memory.store import TaskRecord
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore
from maistro.tasks.admission import TaskRunAdmitter
from maistro.tasks.idempotency import (
    TASK_SUBMIT_ACTION,
    AdmissionRecord,
    InMemoryTaskIdempotencyStore,
    admission_scope_key,
)
from maistro.tasks.models import TaskCreate, TaskResponse
from maistro.tasks.queue import TaskQueue


class _RowSession:
    """AsyncSession double over one shared dict: ``get`` reads, ``merge``
    upserts. Every ``factory()`` call sees the same dict, so a fire-and-forget
    receipt write is visible to the later replay read — the one property of a
    real database this path depends on."""

    def __init__(self, rows: dict[str, TaskRecord]) -> None:
        self._rows = rows

    async def __aenter__(self) -> _RowSession:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def get(self, model: Any, key: str) -> TaskRecord | None:
        return self._rows.get(key)

    async def merge(self, record: Any) -> Any:
        if record.created_at is None:
            # The real column is `server_default=func.now()`; without it the
            # rebuilt receipt fails validation and the replay would silently
            # exercise the reconstruction path instead of the row path.
            record.created_at = datetime.now(UTC)
        self._rows[record.id] = record
        return record

    async def commit(self) -> None:
        return None


def _install_row_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, TaskRecord]:
    rows: dict[str, TaskRecord] = {}

    def factory() -> _RowSession:
        return _RowSession(rows)

    monkeypatch.setattr(queue_mod, "get_async_session_factory", lambda: factory)
    return rows


async def _drain_persist(queue: TaskQueue) -> None:
    """Let the fire-and-forget TaskRecord upserts land before asserting."""
    while queue._persist_writes:
        await asyncio.gather(*queue._persist_writes)


@dataclass
class _Replica:
    """One admitted submission, its durable row, and the replica that
    answers the retry with empty memory — process A is gone."""

    rows: dict[str, TaskRecord]
    runs: InMemoryRunStore
    store: InMemoryTaskIdempotencyStore
    scope: str
    replica_a: TaskQueue
    replica_b: TaskQueue
    task: TaskResponse
    record: AdmissionRecord


async def _admitted_then_dead(monkeypatch: pytest.MonkeyPatch) -> _Replica:
    rows = _install_row_store(monkeypatch)
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    project = await projects.create(
        workspace_id="w1", parent_project_id=root.project_id, name="Tasks"
    )
    runs = InMemoryRunStore(project_store=projects)
    admitter = TaskRunAdmitter(runs, workspace_id="w1", project_id=project.project_id)
    store = InMemoryTaskIdempotencyStore()

    replica_a = TaskQueue(admitter=admitter, idempotency_store=store)
    task = await replica_a.submit(
        TaskCreate(description="strand me", workspace="w1"),
        user_id="alice",
        idempotency_key="key-1",
    )
    await _drain_persist(replica_a)
    assert task.run_id is not None
    # The durable row exists — the receipt was persisted, which is the whole
    # point: the old early-return stopped here and answered every replay.
    assert task.task_id in rows

    # Replica B: same durable facts (Run spine, claim store, TaskRecord row),
    # none of process A's memory.
    replica_b = TaskQueue(admitter=admitter, idempotency_store=store)
    scope = admission_scope_key(
        principal="alice",
        workspace_id="w1",
        project_id=project.project_id,
        action=TASK_SUBMIT_ACTION,
        key="key-1",
    )
    record = await store.get(scope)
    assert record is not None and record.task_id == task.task_id
    return _Replica(
        rows=rows,
        runs=runs,
        store=store,
        scope=scope,
        replica_a=replica_a,
        replica_b=replica_b,
        task=task,
        record=record,
    )


async def test_a_replay_with_only_a_durable_row_re_enqueues_the_stranded_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The strand itself: replica A persisted the receipt and died before the
    queue entry was worth anything; replica B reconciles the retry. The row
    answers identity, the resume gate re-materializes dispatch — ``_pending``
    and ``_tasks`` are populated and the QUEUED Run gains an executor."""
    scene = await _admitted_then_dead(monkeypatch)

    receipt = await scene.replica_b._replay_receipt(scene.record)

    assert scene.replica_b._pending.qsize() == 1
    assert scene.replica_b._pending._queue[0] == scene.task.task_id
    assert scene.replica_b._tasks[scene.task.task_id] is receipt
    # Identity comes from the durable row (#1057): the principal evidence the
    # claim's stored request does not carry authoritatively.
    assert receipt.user_id == "alice"
    assert receipt.run_id == scene.task.run_id
    # The resume confirms the Run's QUEUED state; it does not move it.
    run = await scene.runs.get_run(scene.task.run_id)
    assert run is not None and run.status is RunStatus.QUEUED


async def test_a_replay_with_a_durable_row_does_not_duplicate_a_running_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The row survives, but another replica's worker already claimed the Run
    (QUEUED -> RUNNING). The resume gate refuses, so replica B answers the
    retry from the row without enqueueing a second executor."""
    scene = await _admitted_then_dead(monkeypatch)
    assert scene.task.run_id is not None
    await scene.runs.transition_run(scene.task.run_id, RunStatus.RUNNING)

    receipt = await scene.replica_b._replay_receipt(scene.record)

    assert scene.replica_b._pending.qsize() == 0
    assert scene.task.task_id not in scene.replica_b._tasks
    # Answered — the caller is not stuck — but never re-dispatched.
    assert receipt.task_id == scene.task.task_id


async def test_a_replay_with_a_durable_row_does_not_rerun_a_terminal_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed Run behind a persisted receipt: the replay answers the
    original receipt and enqueues nothing — finished work is not re-run."""
    scene = await _admitted_then_dead(monkeypatch)
    assert scene.task.run_id is not None
    await scene.runs.transition_run(scene.task.run_id, RunStatus.RUNNING)
    await scene.runs.transition_run(scene.task.run_id, RunStatus.COMPLETED)

    receipt = await scene.replica_b._replay_receipt(scene.record)

    assert scene.replica_b._pending.qsize() == 0
    assert scene.task.task_id not in scene.replica_b._tasks
    assert receipt.task_id == scene.task.task_id


async def test_an_unreadable_row_falls_through_to_reconstruction_and_still_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row that cannot become a receipt (missing actor evidence) is not a
    dead end: the replay falls through to the claim's stored request, and the
    resume gate still re-materializes the stranded dispatch."""
    scene = await _admitted_then_dead(monkeypatch)
    row = scene.rows[scene.task.task_id]
    row.user_id = ""  # `_task_from_record` refuses ownerless work

    receipt = await scene.replica_b._replay_receipt(scene.record)

    # Reconstructed from the claim's stored request — which carries the owner
    # as admitted — and the strand is still resumed.
    assert receipt.user_id == "alice"
    assert scene.replica_b._pending.qsize() == 1
    assert scene.replica_b._tasks[scene.task.task_id] is receipt
