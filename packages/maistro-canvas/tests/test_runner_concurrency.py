"""Concurrency semantics of ``CanvasJobRunner`` (#93).

The runner's queue mechanics (atomic claim, fencing, retry bounds) are covered
by ``test_job_runner_lifecycle.py``; this suite covers the *concurrency*
dimension the built-in worker deployment depends on:

- independent ready jobs progress **concurrently** inside one runner process
  (``concurrency > 1``) — unrelated artifact branches do not queue behind each
  other where the queue allows parallelism;
- ``stop()`` stops claiming and drains already-claimed jobs before ``start()``
  returns, so a stopped worker never abandons claimed physical work silently;
- bounded-shutdown cancellation of ``start()`` reaches the in-flight
  execution, leaving the receipt in its leased state for the reaper rather
  than faking a terminal status;
- with fewer pending jobs than concurrency slots, one job is still claimed
  exactly once (slots never double-claim);
- ``concurrency`` is validated like the other constructor bounds.

The store here reproduces the same claim/reap/renew semantics as the
``InMemoryJobStore`` in ``test_job_runner_lifecycle`` (kept local so this file
stays independently runnable), and the executors are real async callables so
the overlap proofs are behavioral, not structural.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from maistro_canvas.canvas.runner import CanvasJobRunner
from maistro_canvas.types import GenerationJobRecord, JobAction, JobStatus

pytestmark = pytest.mark.asyncio


class JobLeaseLostErrorFence(Exception):
    """Raised by the fake store when a fenced write loses its race."""


class InMemoryJobStore:
    """Minimal claim/reap/renew/update store matching PgCanvasStore semantics."""

    def __init__(self) -> None:
        self._jobs: dict[str, GenerationJobRecord] = {}
        self._claim_lock = asyncio.Lock()

    async def create_job(self, job: GenerationJobRecord) -> GenerationJobRecord:
        self._jobs[job.id] = job
        return dataclasses.replace(job)

    async def get_job(self, job_id: str) -> GenerationJobRecord | None:
        job = self._jobs.get(job_id)
        return dataclasses.replace(job) if job is not None else None

    async def update_job(
        self,
        job: GenerationJobRecord,
        *,
        org_id: str,
        expected_leased_by: str | None = None,
        expected_attempts: int | None = None,
        expected_status: str | None = None,
    ) -> GenerationJobRecord:
        from maistro_canvas.types import JobNotFoundError

        fences = {
            "leased_by": expected_leased_by,
            "attempts": expected_attempts,
            "status": expected_status,
        }
        if any(value is not None for value in fences.values()):
            current = self._jobs.get(job.id)
            if current is None:
                raise JobNotFoundError(job.id)
            for field, expected in fences.items():
                if expected is not None and getattr(current, field) != expected:
                    raise JobLeaseLostErrorFence(job.id, field)
        self._jobs[job.id] = dataclasses.replace(job)
        return job

    async def claim_next_pending(
        self, worker_id: str, lease_seconds: int
    ) -> GenerationJobRecord | None:
        async with self._claim_lock:
            pending = sorted(
                (
                    j
                    for j in self._jobs.values()
                    if j.status == JobStatus.PENDING and j.attempts < j.max_attempts
                ),
                key=lambda j: j.created_at,
            )
            if not pending:
                return None
            job = pending[0]
            job.status = JobStatus.RUNNING
            job.leased_by = worker_id
            job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
            job.attempts += 1
            return dataclasses.replace(job)

    async def reap_expired_leases(self) -> list[GenerationJobRecord]:
        now = datetime.now(UTC)
        reaped: list[GenerationJobRecord] = []
        for job in self._jobs.values():
            if (
                job.status == JobStatus.RUNNING
                and job.lease_expires_at is not None
                and job.lease_expires_at < now
            ):
                job.leased_by = None
                if job.attempts < job.max_attempts:
                    job.status = JobStatus.PENDING
                    job.lease_expires_at = None
                reaped.append(dataclasses.replace(job))
        return reaped

    async def renew_lease(
        self,
        job_id: str,
        worker_id: str,
        lease_seconds: int,
        *,
        expected_attempts: int | None = None,
    ) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.leased_by != worker_id or job.status != JobStatus.RUNNING:
            return False
        if expected_attempts is not None and job.attempts != expected_attempts:
            return False
        job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        return True


class BarrierExecutor:
    """Executes N claimed jobs only after all N have entered the call.

    No job can finish before every party has arrived, so reaching
    ``completions == parties`` is a behavioral proof that the runner executed
    that many jobs concurrently — not a structural assertion about tasks.
    """

    def __init__(self, parties: int, *, timeout: float = 5.0) -> None:
        self._parties = parties
        self._timeout = timeout
        self.arrivals = 0
        self.completions = 0
        self._release = asyncio.Event()

    async def _execute_claimed(self, job: GenerationJobRecord) -> None:
        self.arrivals += 1
        if self.arrivals >= self._parties:
            self._release.set()
        await asyncio.wait_for(self._release.wait(), timeout=self._timeout)
        job.result_paths = [f"image://result-{job.id}"]
        self.completions += 1


class SlowExecutor:
    """Completes after a fixed delay, recording which job ids it ran."""

    def __init__(self, delay: float) -> None:
        self._delay = delay
        self.executed: list[str] = []

    async def _execute_claimed(self, job: GenerationJobRecord) -> None:
        await asyncio.sleep(self._delay)
        self.executed.append(job.id)
        job.result_paths = [f"image://result-{job.id}"]


class CancelRecordingExecutor:
    """Sleeps until cancelled, recording that cancellation arrived."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.cancelled = 0

    async def _execute_claimed(self, job: GenerationJobRecord) -> None:
        self.entered.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise


class FlakyClaimStore(InMemoryJobStore):
    """Claim raises once, then behaves — a tick task that dies mid-loop."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_first_claim = True

    async def claim_next_pending(
        self, worker_id: str, lease_seconds: int
    ) -> GenerationJobRecord | None:
        if self.fail_first_claim:
            self.fail_first_claim = False
            raise RuntimeError("claim exploded")
        return await super().claim_next_pending(worker_id, lease_seconds)


async def _seed_job(store: InMemoryJobStore, job_id: str) -> GenerationJobRecord:
    return await store.create_job(
        GenerationJobRecord(
            id=job_id,
            layer_id="l1",
            canvas_id="c1",
            action=JobAction.GENERATE,
            status=JobStatus.PENDING,
            model_id="draft-model",
            prompt="a castle",
            params={"count": 1},
            max_attempts=3,
        )
    )


async def _wait_until(predicate: Callable[[], bool], *, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not reached before timeout")
        await asyncio.sleep(0.001)


async def _stop_runner(runner: CanvasJobRunner, task: asyncio.Task[None]) -> None:
    """Stop a running runner and bound its drain like the composition layer."""
    runner.stop()
    await asyncio.wait_for(asyncio.shield(task), timeout=5)


async def test_independent_jobs_progress_concurrently_in_one_runner() -> None:
    """Two ready jobs run overlapping inside one runner (concurrency=2).

    Both jobs must enter their provider call before either may leave it —
    a second runner slot is the only way this barrier can open.
    """
    store = InMemoryJobStore()
    await _seed_job(store, "job-a")
    await _seed_job(store, "job-b")
    executor = BarrierExecutor(parties=2)

    runner = CanvasJobRunner(
        store=store,
        executor=executor,  # type: ignore[arg-type]
        poll_interval=0.001,
        reap_interval=3600.0,
        concurrency=2,
    )
    task = asyncio.create_task(runner.start())
    try:
        await _wait_until(
            lambda: (
                store._jobs["job-a"].status == JobStatus.DONE
                and store._jobs["job-b"].status == JobStatus.DONE
            )
        )
    finally:
        await _stop_runner(runner, task)

    assert executor.arrivals == 2
    assert executor.completions == 2
    job_a = await store.get_job("job-a")
    job_b = await store.get_job("job-b")
    assert job_a is not None and job_a.status == JobStatus.DONE
    assert job_b is not None and job_b.status == JobStatus.DONE
    assert job_a.attempts == 1 and job_b.attempts == 1


async def test_stop_drains_claimed_jobs_before_start_returns() -> None:
    """stop() halts claiming; the job already claimed still completes DONE."""
    store = InMemoryJobStore()
    await _seed_job(store, "job-1")
    await _seed_job(store, "job-2")
    executor = SlowExecutor(delay=0.05)

    runner = CanvasJobRunner(
        store=store,
        executor=executor,  # type: ignore[arg-type]
        poll_interval=0.001,
        reap_interval=3600.0,
        concurrency=1,
    )
    task = asyncio.create_task(runner.start())
    await _wait_until(lambda: store._jobs["job-1"].status == JobStatus.RUNNING)
    await _stop_runner(runner, task)

    job_1 = await store.get_job("job-1")
    job_2 = await store.get_job("job-2")
    assert job_1 is not None and job_1.status == JobStatus.DONE
    # Claiming ceased with stop(): job-2 was never handed out.
    assert job_2 is not None and job_2.status == JobStatus.PENDING
    assert job_2.leased_by is None
    assert executor.executed == ["job-1"]


async def test_cancelled_start_cancels_in_flight_execution() -> None:
    """Cancelling start() (bounded shutdown) reaches the in-flight provider call."""
    store = InMemoryJobStore()
    await _seed_job(store, "job-1")
    executor = CancelRecordingExecutor()

    runner = CanvasJobRunner(
        store=store,
        executor=executor,  # type: ignore[arg-type]
        poll_interval=0.001,
        reap_interval=3600.0,
        concurrency=1,
    )
    task = asyncio.create_task(runner.start())
    await asyncio.wait_for(executor.entered.wait(), timeout=5)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert executor.cancelled == 1
    # No fake terminal status: the receipt stays leased/running for the
    # reaper to recover truthfully.
    job = await store.get_job("job-1")
    assert job is not None and job.status == JobStatus.RUNNING
    assert job.leased_by is not None


async def test_extra_concurrency_slots_do_not_double_claim_one_job() -> None:
    """More slots than ready jobs: the single job is claimed exactly once."""
    store = InMemoryJobStore()
    await _seed_job(store, "only-job")
    executor = BarrierExecutor(parties=1)

    runner = CanvasJobRunner(
        store=store,
        executor=executor,  # type: ignore[arg-type]
        poll_interval=0.001,
        reap_interval=3600.0,
        concurrency=4,
    )
    task = asyncio.create_task(runner.start())
    try:
        await _wait_until(lambda: store._jobs["only-job"].status == JobStatus.DONE)
    finally:
        await _stop_runner(runner, task)

    job = await store.get_job("only-job")
    assert job is not None
    assert job.status == JobStatus.DONE
    assert job.attempts == 1
    assert executor.completions == 1


async def test_start_loop_reaps_expired_leases_while_running() -> None:
    """The running loop schedules reaping: a dead worker's lease is reclaimed.

    A job left RUNNING by a worker that died is requeued by the loop's reap
    sweep and re-executed under its next attempt — the same recovery the
    serial loop provided, now on the concurrent schedule.
    """
    store = InMemoryJobStore()
    await _seed_job(store, "stuck")
    # Simulate the dead holder: RUNNING with an already-expired lease.
    stuck = store._jobs["stuck"]
    stuck.status = JobStatus.RUNNING
    stuck.leased_by = "dead-worker"
    stuck.attempts = 1
    stuck.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    runner = CanvasJobRunner(
        store=store,
        executor=SlowExecutor(delay=0.0),  # type: ignore[arg-type]
        poll_interval=0.001,
        reap_interval=0.002,
        concurrency=1,
    )
    task = asyncio.create_task(runner.start())
    try:
        await _wait_until(
            lambda: (
                store._jobs["stuck"].status == JobStatus.DONE and store._jobs["stuck"].attempts == 2
            )
        )
    finally:
        await _stop_runner(runner, task)

    job = await store.get_job("stuck")
    assert job is not None
    assert job.status == JobStatus.DONE
    assert job.attempts == 2


async def test_a_failing_tick_is_retrieved_and_the_loop_survives() -> None:
    """A tick task that raises is consumed (logged), not left unretrieved.

    The loop retires the finished unit and keeps claiming — one broken claim
    must not strand the worker or kill the service loop.
    """
    store = FlakyClaimStore()
    await _seed_job(store, "job-1")
    runner = CanvasJobRunner(
        store=store,
        executor=SlowExecutor(delay=0.0),  # type: ignore[arg-type]
        poll_interval=0.001,
        reap_interval=3600.0,
        concurrency=1,
    )
    task = asyncio.create_task(runner.start())
    try:
        await _wait_until(lambda: store._jobs["job-1"].status == JobStatus.DONE)
    finally:
        await _stop_runner(runner, task)

    job = await store.get_job("job-1")
    assert job is not None and job.status == JobStatus.DONE


async def test_consume_tick_silently_retrieves_a_cancelled_tick() -> None:
    """A cancelled tick has no exception to log; retrieval must not raise."""
    task = asyncio.create_task(asyncio.sleep(60))
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    CanvasJobRunner._consume_tick(task)


async def test_rejects_non_positive_concurrency() -> None:
    store = InMemoryJobStore()
    with pytest.raises(ValueError, match="concurrency"):
        CanvasJobRunner(
            store=store,
            executor=SlowExecutor(delay=0.0),  # type: ignore[arg-type]
            concurrency=0,
        )
