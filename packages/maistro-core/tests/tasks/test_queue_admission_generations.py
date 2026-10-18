"""Real queue/admitter/coordinator composition over the transactional PG double.

Dispatch hints here are process-local liveness only. These tests do not claim
canonical Attempt ownership or independent-replica physical-effect proof.
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime, timedelta

import pytest

import maistro.tasks.queue as queue_module
from maistro.observability.correlation import bind_execution_context
from maistro.runs.model import TERMINAL_RUN_STATUSES, Run, RunStatus
from maistro.tasks.admission import TaskRunAdmitter
from maistro.tasks.idempotency import InMemoryTaskIdempotencyStore
from maistro.tasks.models import TaskCreate, TaskResponse, TaskStatus
from maistro.tasks.queue import TaskQueue

# Pytest uses importlib mode; the checkout's hyphenated package directory
# cannot appear in a Python import statement. Reuse exactly one SQL double.
_harness = importlib.import_module(
    "packages.maistro-core.tests.tasks.test_pg_admission_generations"
)
Harness = _harness.Harness
admit = _harness.admit
claim = _harness.claim
make_harness = _harness.make_harness


class _Gauge:
    def __init__(self) -> None:
        self.value = 0

    def inc(self) -> None:
        self.value += 1

    def dec(self) -> None:
        self.value -= 1


@pytest.fixture
def gauge(monkeypatch: pytest.MonkeyPatch) -> _Gauge:
    value = _Gauge()
    monkeypatch.setattr(queue_module, "active_tasks", value)
    monkeypatch.setattr(queue_module, "get_async_session_factory", lambda: None)
    return value


def _queue(h: Harness) -> TaskQueue:
    admitter = TaskRunAdmitter(
        h.store, workspace_id="ws", project_id=h.project_id, coordinator=h.coordinator
    )
    return TaskQueue(admitter=admitter, idempotency_store=InMemoryTaskIdempotencyStore())


async def _submit(
    queue: TaskQueue, *, request_id: str = "request-original", **kwargs: object
) -> TaskResponse:
    with bind_execution_context(request_id=request_id):
        return await queue.submit(
            TaskCreate(description="original"),
            user_id="origin",
            workspace_id="ws",
            service_principal_id="service",
            delegation_id="delegation",
            actor_kind="service",
            idempotency_key="key",
            **kwargs,
        )


def _status(h: Harness, run_id: str, status: RunStatus) -> None:
    """Model an externally observed canonical lifecycle state, not a claim."""
    row = h.pool.runs[run_id]
    payload = row["payload"]
    payload["status"] = status.value
    payload["started_at"] = (
        _timestamp() if status not in {RunStatus.CREATED, RunStatus.QUEUED} else None
    )
    payload["finished_at"] = _timestamp() if status in TERMINAL_RUN_STATUSES else None
    payload["result"] = {"files_changed": ["out.py"]} if status is RunStatus.COMPLETED else None
    # Ensure the synthetic remote state is a valid canonical record.
    Run.model_validate(payload)
    row["status"] = status.value


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


async def test_submission_uses_generation_coordinator_without_touching_legacy_store(
    gauge: _Gauge,
) -> None:
    h = await make_harness()
    h.now = datetime.now(UTC) + timedelta(seconds=1)
    queue = _queue(h)
    first = await _submit(queue)
    replay = await _submit(queue, request_id="retry-request")
    assert first.task_id == replay.task_id and first.run_id == replay.run_id
    assert first.created_at == replay.created_at
    assert len(h.pool.runs) == len(h.pool.rows) == 1
    assert queue._idempotency._rows == {}
    assert queue._pending.qsize() == 1 and gauge.value == 1
    assert h.pool.runs[first.run_id]["payload"]["provenance"]["request_id"] == "request-original"


async def test_concurrent_same_key_submission_makes_one_run_receipt_and_local_hint(
    gauge: _Gauge,
) -> None:
    h = await make_harness()
    h.now = datetime.now(UTC) + timedelta(seconds=1)
    queue = _queue(h)
    results = await asyncio.gather(*(_submit(queue) for _ in range(8)))
    assert len({(r.run_id, r.task_id) for r in results}) == 1
    assert len(h.pool.runs) == len(h.pool.rows) == 1
    assert queue._pending.qsize() == 1 and gauge.value == 1


async def test_dequeued_hint_survives_gap_before_claim_without_duplicate_enqueue(
    gauge: _Gauge,
) -> None:
    h = await make_harness()
    h.now = datetime.now(UTC) + timedelta(seconds=1)
    queue = _queue(h)
    first = await _submit(queue)
    assert await queue.next_task() == first.task_id
    assert first.task_id not in queue._claimed
    await _submit(queue)
    assert queue._pending.empty() and gauge.value == 1
    async with queue.claim(first.task_id):
        await _submit(queue)
        assert queue._pending.empty() and gauge.value == 1


@pytest.mark.parametrize("parked", [RunStatus.PAUSED, RunStatus.WAITING, RunStatus.RUNNING])
async def test_nonrunnable_replay_is_passive_and_does_not_count_active(
    gauge: _Gauge, parked: RunStatus
) -> None:
    h = await make_harness()
    result = await admit(h, await claim(h))
    _status(h, result.run_id, parked)
    queue = _queue(h)
    receipt = await _submit(queue)
    assert receipt.run_id == result.run_id
    assert queue._pending.empty() and gauge.value == 0
    _status(h, result.run_id, RunStatus.COMPLETED)
    refreshed = await _submit(queue)
    assert refreshed.status is TaskStatus.COMPLETED
    assert refreshed.result.files_changed == ["out.py"]
    assert gauge.value == 0
    await _submit(queue)
    assert gauge.value == 0


@pytest.mark.parametrize("via_recover", [False, True])
async def test_passive_receipt_can_resume_to_exactly_one_runnable_hint(
    gauge: _Gauge, via_recover: bool
) -> None:
    h = await make_harness()
    result = await admit(h, await claim(h))
    _status(h, result.run_id, RunStatus.PAUSED)
    queue = _queue(h)
    receipt = await _submit(queue)
    assert queue._pending.empty() and gauge.value == 0
    _status(h, result.run_id, RunStatus.QUEUED)
    if via_recover:
        assert await queue.recover(h.store) == 1
        assert await queue.recover(h.store) == 0
    else:
        await _submit(queue)
        await _submit(queue)
    assert queue._pending.qsize() == 1 and gauge.value == 1
    assert await queue.next_task() == receipt.task_id
    assert await queue.update_status(receipt.task_id, TaskStatus.PLANNING)


@pytest.mark.parametrize("via_recover", [False, True])
async def test_warm_coding_receipt_resets_projection_when_canonical_run_resumes(
    gauge: _Gauge, via_recover: bool
) -> None:
    h = await make_harness()
    h.now = datetime.now(UTC) + timedelta(seconds=1)
    queue = _queue(h)
    receipt = await _submit(queue)
    await queue.next_task()
    async with queue.claim(receipt.task_id):
        assert await queue.update_status(receipt.task_id, TaskStatus.PLANNING)
        assert await queue.update_status(receipt.task_id, TaskStatus.CODING)
        _status(h, receipt.run_id, RunStatus.PAUSED)
    assert receipt.status is TaskStatus.CODING
    _status(h, receipt.run_id, RunStatus.QUEUED)
    if via_recover:
        assert await queue.recover(h.store) == 1
        assert await queue.recover(h.store) == 0
    else:
        await _submit(queue)
        await _submit(queue)
    assert receipt.status is TaskStatus.QUEUED and receipt.phase == "queued"
    assert queue._pending.qsize() == 1 and gauge.value == 1
    assert await queue.update_status(receipt.task_id, TaskStatus.PLANNING)


async def test_terminal_replay_refreshes_live_receipt_and_decrements_gauge_once(
    gauge: _Gauge,
) -> None:
    h = await make_harness()
    h.now = datetime.now(UTC) + timedelta(seconds=1)
    queue = _queue(h)
    first = await _submit(queue)
    _status(h, first.run_id, RunStatus.COMPLETED)
    second = await _submit(queue)
    assert second is first
    assert first.status is TaskStatus.COMPLETED
    assert first.result.files_changed == ["out.py"]
    assert gauge.value == 0
    await _submit(queue)
    assert gauge.value == 0 and len(h.pool.runs) == 1


async def test_replay_rejects_same_receipt_cache_pointing_at_another_run(gauge: _Gauge) -> None:
    h = await make_harness()
    h.now = datetime.now(UTC) + timedelta(seconds=1)
    queue = _queue(h)
    first = await _submit(queue)
    first.run_id = "wrong-cached-run"
    with pytest.raises((ValueError, RuntimeError)):
        await _submit(queue)
    assert len(h.pool.runs) == 1


async def test_optional_acknowledgement_cannot_timeout_a_committed_submission(
    gauge: _Gauge, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = await make_harness()
    h.now = datetime.now(UTC) + timedelta(seconds=1)
    monkeypatch.setattr(queue_module, "MAX_PENDING_POLLS", 1)
    monkeypatch.setattr(queue_module, "PENDING_POLL", 1.0)
    entered = asyncio.Event()

    async def blocked(*_args: object, **_kwargs: object) -> None:
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(h.coordinator, "complete", blocked)
    first = await _submit(_queue(h))
    assert not entered.is_set(), "optional evidence must not consume the success response budget"
    h.now += timedelta(seconds=31)
    replay = await _submit(_queue(h), request_id="retry")
    assert first.run_id == replay.run_id and first.task_id == replay.task_id
    assert first.created_at == replay.created_at
    assert len(h.pool.runs) == 1 and h.prepared == 1
    assert next(iter(h.pool.rows.values()))["acknowledged_at"] is None


async def test_every_public_operation_receives_one_original_submission_deadline(
    gauge: _Gauge, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = await make_harness()
    h.now = datetime.now(UTC) + timedelta(seconds=1)
    deadlines: list[float] = []

    def instrument(name: str) -> None:
        method = getattr(h.coordinator, name)

        async def measured(*args: object, deadline: float, **kwargs: object) -> object:
            deadlines.append(deadline)
            return await method(*args, deadline=deadline, **kwargs)

        monkeypatch.setattr(h.coordinator, name, measured)

    for name in ("claim", "admit", "replay"):
        instrument(name)
    await _submit(_queue(h))
    assert len(deadlines) >= 3 and len(set(deadlines)) == 1


async def test_queue_second_outage_preserves_bound_generation_and_publishes_nothing(
    gauge: _Gauge,
) -> None:
    import asyncpg

    h = await make_harness()
    h.now = datetime.now(UTC) + timedelta(seconds=1)
    queue = _queue(h)
    h.pool.commit_faults = ["after"]
    h.pool.after_commit_fault = lambda pool: setattr(
        pool, "next_acquire_error", asyncpg.InterfaceError("resolver unavailable")
    )
    with pytest.raises(asyncpg.InterfaceError, match="resolver unavailable"):
        await _submit(queue)
    assert len(h.pool.runs) == len(h.pool.rows) == 1
    assert not queue._tasks and queue._pending.empty() and gauge.value == 0
    replay = await _submit(queue)
    assert replay.run_id in h.pool.runs
    assert h.prepared == 1 and gauge.value == 1


async def test_submission_timeout_preserves_owned_generation_without_legacy_fallback(
    gauge: _Gauge, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maistro.tasks.idempotency import IdempotencyPendingTimeout

    h = await make_harness()
    h.now = datetime.now(UTC) + timedelta(seconds=1)
    queue = _queue(h)
    monkeypatch.setattr(queue_module, "MAX_PENDING_POLLS", 1)
    monkeypatch.setattr(queue_module, "PENDING_POLL", 0.02)
    entered = asyncio.Event()

    async def blocked(_envelope: object) -> Run:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    h.coordinator._prepare = blocked
    with pytest.raises(IdempotencyPendingTimeout):
        await _submit(queue)
    assert entered.is_set() and len(h.pool.rows) == 1
    assert not h.pool.runs and not queue._tasks and gauge.value == 0
    assert not queue._idempotency._rows


@pytest.mark.parametrize("via_recover", [False, True])
async def test_cancelled_runner_lane_wait_releases_hint_for_same_queue_recovery(
    gauge: _Gauge, via_recover: bool
) -> None:
    from maistro.tasks.lanes import Lane, LaneGate
    from maistro.tasks.runner import TaskRunner

    h = await make_harness()
    h.now = datetime.now(UTC) + timedelta(seconds=1)
    queue = _queue(h)
    receipt = await _submit(queue)
    task_id = await queue.next_task()
    assert task_id == receipt.task_id

    async def executor(_request: TaskCreate) -> None:
        raise AssertionError("the worker must remain blocked before physical dispatch")

    runner = TaskRunner(queue, executor, max_workers=1)
    gate = LaneGate(1, live_reserved=0, background_reserved=0)
    runner._gate = gate
    await gate.acquire(Lane.BACKGROUND, "P2")  # Saturate the actual gate.
    worker = asyncio.create_task(runner._admit_and_run(task_id, Lane.BACKGROUND, "P2"))
    try:
        await asyncio.sleep(0)
        assert gate.stats()["waiting"] == 1
        assert task_id not in queue._claimed
        worker.cancel()
        await worker
    finally:
        if not worker.done():
            worker.cancel()
            await worker
        gate.release(Lane.BACKGROUND)
    assert receipt.status is TaskStatus.QUEUED
    assert gauge.value == 1 and queue._pending.empty()
    if via_recover:
        assert await queue.recover(h.store) == 1
        assert await queue.recover(h.store) == 0
    else:
        await _submit(queue)
    await _submit(queue)
    assert queue._pending.qsize() == 1 and gauge.value == 1
    assert await queue.next_task() == task_id
    assert len(h.pool.runs) == 1


async def test_dispatcher_worker_cancelled_before_first_step_does_not_strand_hint(
    gauge: _Gauge, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maistro.tasks.runner import TaskRunner

    h = await make_harness()
    h.now = datetime.now(UTC) + timedelta(seconds=1)
    queue = _queue(h)
    receipt = await _submit(queue)
    cancelled = asyncio.Event()
    real_start_dispatch = TaskRunner._start_dispatch

    def cancel_before_first_step(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        task = real_start_dispatch(self, *args, **kwargs)
        task.cancel()  # Cancellation before the worker can install its try/finally.
        cancelled.set()
        return task

    async def executor(_request: TaskCreate) -> None:
        raise AssertionError("pre-start cancellation must never execute work")

    monkeypatch.setattr(TaskRunner, "_start_dispatch", cancel_before_first_step)
    runner = TaskRunner(queue, executor, max_workers=1)
    await runner.start()
    try:
        await asyncio.wait_for(cancelled.wait(), timeout=1)
    finally:
        await runner.stop(drain_timeout=0)
    assert receipt.status is TaskStatus.QUEUED and not queue._claimed
    assert queue._pending.empty() and gauge.value == 1
    await _submit(queue)
    await _submit(queue)
    assert queue._pending.qsize() == 1 and gauge.value == 1
    assert len(h.pool.runs) == 1


async def test_started_worker_done_callback_cannot_clear_a_replacement_hint(
    gauge: _Gauge, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maistro.tasks.lanes import Lane
    from maistro.tasks.runner import TaskRunner

    h = await make_harness()
    h.now = datetime.now(UTC) + timedelta(seconds=1)
    queue = _queue(h)
    receipt = await _submit(queue)
    await queue.next_task()

    async def executor(_request: TaskCreate) -> None:
        raise AssertionError("helper-lifecycle test does not perform physical work")

    runner = TaskRunner(queue, executor, max_workers=1)

    async def finish_then_publish(task_id: str, _lane: Lane, _tier: str) -> None:
        async with queue.claim(task_id):
            queue.abandon_dispatch_hint(task_id)
            await _submit(queue)
            assert queue._pending.empty(), "abandon must not remove an actively claimed hint"
        # The prior dispatch has finished; a replay supplies its successor hint
        # before the worker-done callback is scheduled.
        await _submit(queue)
        assert queue._pending.qsize() == 1

    monkeypatch.setattr(runner, "_admit_and_run", finish_then_publish)
    worker = runner._start_dispatch(receipt.task_id, Lane.BACKGROUND, "P2")
    await worker
    await asyncio.sleep(0)
    assert worker not in runner._active_tasks
    await _submit(queue)
    assert queue._pending.qsize() == 1 and gauge.value == 1
    assert len(h.pool.runs) == 1
