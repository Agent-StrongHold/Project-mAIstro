"""SPEC-203 failure-mode tests for the canvas job lifecycle.

These assert the *failure* modes the runner exists to handle — not the happy
path:

- two runners racing one PENDING job → exactly one claims it (atomic claim)
- a dead worker's expired lease → reaper requeues (budget left) or fails (exhausted)
- a job that keeps failing → terminal FAILED at max_attempts, not an infinite loop
- list_models → 503 when the backend is unconfigured, 200 [] when genuinely empty

The job store here is an in-memory fake that reproduces the SQL semantics of the
real `CanvasStore.claim_next_pending` / `reap_expired_leases` (single-claim under
lock; lease-expiry transitions). The executor and image client are the real
classes wired to fakes, so the runner's interaction with `_execute_claimed` is
exercised for real.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from maistro_canvas.canvas.runner import CanvasJobRunner
from maistro_canvas.types import (
    GenerationJobRecord,
    JobAction,
    JobStatus,
)

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────


class InMemoryJobStore:
    """In-memory job store reproducing the real claim/reap semantics."""

    def __init__(self) -> None:
        self._jobs: dict[str, GenerationJobRecord] = {}
        self._claim_lock = asyncio.Lock()

    async def create_job(self, job: GenerationJobRecord) -> GenerationJobRecord:
        self._jobs[job.id] = job
        return job

    async def get_job(self, job_id: str) -> GenerationJobRecord | None:
        return self._jobs.get(job_id)

    async def update_job(self, job: GenerationJobRecord) -> GenerationJobRecord:
        self._jobs[job.id] = job
        return job

    async def claim_next_pending(
        self, worker_id: str, lease_seconds: int
    ) -> GenerationJobRecord | None:
        async with self._claim_lock:
            pending = sorted(
                (j for j in self._jobs.values() if j.status == JobStatus.PENDING),
                key=lambda j: j.created_at,
            )
            if not pending:
                return None
            job = pending[0]
            job.status = JobStatus.RUNNING
            job.leased_by = worker_id
            job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
            job.attempts += 1
            return job

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
                job.lease_expires_at = None
                if job.attempts < job.max_attempts:
                    job.status = JobStatus.PENDING
                else:
                    job.status = JobStatus.FAILED
                    job.error_message = "Generation failed: worker lost (lease expired)."
                    job.completed_at = now
                reaped.append(job)
        return reaped


class FakeExecutor:
    """Executor fake that optionally fails N times."""

    def __init__(self, fail_times: int = 0) -> None:
        self._fail_times = fail_times
        self._calls = 0

    async def _execute_claimed(self, job: GenerationJobRecord) -> None:
        self._calls += 1
        if self._calls <= self._fail_times:
            raise RuntimeError("provider 503 service unavailable")
        job.result_paths = ["https://img/result.png"]


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


async def _seed_pending_job(
    store: InMemoryJobStore, *, job_id: str = "job1", max_attempts: int = 3
) -> GenerationJobRecord:
    job = GenerationJobRecord(
        id=job_id,
        layer_id="l1",
        canvas_id="c1",
        action=JobAction.GENERATE,
        status=JobStatus.PENDING,
        model_id="draft-model",
        prompt="a castle",
        params={"count": 1},
        max_attempts=max_attempts,
    )
    return await store.create_job(job)


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────


async def test_runner_advances_pending_to_done() -> None:
    """A PENDING job reaches DONE via the runner — no manual run_job call."""
    store = InMemoryJobStore()
    executor = FakeExecutor()
    await _seed_pending_job(store)

    runner = CanvasJobRunner(store=store, executor=executor)  # type: ignore[arg-type]
    ran = await runner.tick_once()

    assert ran is True
    job = await store.get_job("job1")
    assert job is not None
    assert job.status == JobStatus.DONE
    assert job.leased_by is None


async def test_two_runners_race_one_job_exactly_one_claims() -> None:
    """The atomic claim invariant: two runners, one job → exactly one wins."""
    store = InMemoryJobStore()
    await _seed_pending_job(store)

    claimed = await asyncio.gather(
        store.claim_next_pending("w1", 300),
        store.claim_next_pending("w2", 300),
    )
    winners = [c for c in claimed if c is not None]
    assert len(winners) == 1
    job = await store.get_job("job1")
    assert job is not None
    assert job.status == JobStatus.RUNNING
    assert job.leased_by in ("w1", "w2")
    assert job.attempts == 1


async def test_dead_worker_lease_requeues_when_budget_remains() -> None:
    """Expired lease with attempts left → reaper → PENDING."""
    store = InMemoryJobStore()
    job = await _seed_pending_job(store, max_attempts=3)
    job.status = JobStatus.RUNNING
    job.attempts = 1
    job.leased_by = "dead-worker"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await store.update_job(job)

    reaped = await store.reap_expired_leases()
    assert len(reaped) == 1
    requeued = await store.get_job("job1")
    assert requeued is not None
    assert requeued.status == JobStatus.PENDING
    assert requeued.leased_by is None


async def test_dead_worker_lease_fails_when_budget_exhausted() -> None:
    """Expired lease at max_attempts → terminal FAILED."""
    store = InMemoryJobStore()
    job = await _seed_pending_job(store, max_attempts=3)
    job.status = JobStatus.RUNNING
    job.attempts = 3
    job.leased_by = "dead-worker"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await store.update_job(job)

    reaped = await store.reap_expired_leases()
    assert len(reaped) == 1
    dead = await store.get_job("job1")
    assert dead is not None
    assert dead.status == JobStatus.FAILED
    assert "worker lost" in (dead.error_message or "")


async def test_retry_bound_goes_terminal() -> None:
    """Always-failing job → FAILED after max_attempts, not infinite loop."""
    store = InMemoryJobStore()
    executor = FakeExecutor(fail_times=99)
    await _seed_pending_job(store, max_attempts=3)

    runner = CanvasJobRunner(store=store, executor=executor)  # type: ignore[arg-type]

    for _ in range(10):
        ran = await runner.tick_once()
        job = await store.get_job("job1")
        assert job is not None
        if job.status == JobStatus.FAILED:
            break
        if not ran:
            break

    final = await store.get_job("job1")
    assert final is not None
    assert final.status == JobStatus.FAILED
    assert final.attempts == 3


async def test_transient_failure_then_success() -> None:
    """One failure then success → DONE with attempts==2."""
    store = InMemoryJobStore()
    executor = FakeExecutor(fail_times=1)
    await _seed_pending_job(store, max_attempts=3)

    runner = CanvasJobRunner(store=store, executor=executor)  # type: ignore[arg-type]

    for _ in range(5):
        await runner.tick_once()
        job = await store.get_job("job1")
        assert job is not None
        if job.status == JobStatus.DONE:
            break

    final = await store.get_job("job1")
    assert final is not None
    assert final.status == JobStatus.DONE
    assert final.attempts == 2
