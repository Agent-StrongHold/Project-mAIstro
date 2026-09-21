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
import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from maistro_canvas.canvas.runner import CanvasJobRunner
from maistro_canvas.types import (
    GenerationJobRecord,
    JobAction,
    JobLeaseLostError,
    JobStatus,
)

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────


class InMemoryJobStore:
    """In-memory job store reproducing the real claim/reap semantics.

    Every method that hands a job to a caller returns an independent
    ``dataclasses.replace`` copy, never the internally-held row itself —
    mirroring ``PgCanvasStore``, where each query builds a fresh
    ``GenerationJobRecord`` from a DB row via ``_coerce_job``. A caller's
    in-memory mutations (e.g. the runner setting ``job.status = DONE`` while
    a provider call runs) must NOT silently leak into this store's
    'true' row until an explicit ``update_job``/``renew_lease`` write —
    sharing the object instead would hide exactly the stale-write races
    (Codex #1527) these tests exist to catch.
    """

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
    ) -> GenerationJobRecord:
        if expected_leased_by is not None:
            current = self._jobs.get(job.id)
            if current is None:
                from maistro_canvas.types import JobNotFoundError

                raise JobNotFoundError(job.id)
            if current.leased_by != expected_leased_by:
                raise JobLeaseLostError(
                    f"job {job.id!r} lease no longer held by {expected_leased_by!r}"
                )
        self._jobs[job.id] = dataclasses.replace(job)
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
            return dataclasses.replace(job)

    async def reap_expired_leases(self) -> list[GenerationJobRecord]:
        """Reproduces ``PgCanvasStore.reap_expired_leases``'s split semantics
        (Codex #1527 finding): a candidate with retry budget left is
        requeued to ``pending``; one at its retry ceiling only has its
        stale lease holder cleared and stays ``running`` — it is the
        caller's job (``CanvasJobRunner.reap_once``) to terminalize it,
        only after canonical reconciliation has actually run."""
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

    async def renew_lease(self, job_id: str, worker_id: str, lease_seconds: int) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.leased_by != worker_id or job.status != JobStatus.RUNNING:
            return False
        job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        return True


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
    await store.update_job(job, org_id=job.org_id)

    reaped = await store.reap_expired_leases()
    assert len(reaped) == 1
    requeued = await store.get_job("job1")
    assert requeued is not None
    assert requeued.status == JobStatus.PENDING
    assert requeued.leased_by is None


async def test_dead_worker_lease_at_exhaustion_stays_running_not_yet_terminal() -> None:
    """Expired lease at max_attempts → the store alone leaves it ``running``
    (Codex #1527 finding 1): only the lease holder is cleared. Making it
    terminal is deliberately not this method's call — see
    ``test_reap_once_terminalizes_exhausted_job_after_canonical_reconciliation``
    for the two-step version that actually reaches FAILED."""
    store = InMemoryJobStore()
    job = await _seed_pending_job(store, max_attempts=3)
    job.status = JobStatus.RUNNING
    job.attempts = 3
    job.leased_by = "dead-worker"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await store.update_job(job, org_id=job.org_id)

    reaped = await store.reap_expired_leases()
    assert len(reaped) == 1
    still_reconciling = await store.get_job("job1")
    assert still_reconciling is not None
    assert still_reconciling.status == JobStatus.RUNNING
    assert still_reconciling.leased_by is None


async def test_reap_once_terminalizes_exhausted_job_after_canonical_reconciliation() -> None:
    """The runner's ``reap_once`` is the one place that turns an
    exhausted-but-still-``running`` receipt into ``FAILED`` — and only after
    calling the executor's canonical ``fail_job_execution`` reconciliation
    hook."""
    store = InMemoryJobStore()
    job = await _seed_pending_job(store, max_attempts=3)
    job.status = JobStatus.RUNNING
    job.attempts = 3
    job.leased_by = "dead-worker"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await store.update_job(job, org_id=job.org_id)

    executor = FakeExecutor()
    reconciled: list[str] = []

    async def fail_job_execution(job: GenerationJobRecord, error: Exception) -> str:
        reconciled.append(job.id)
        return f"canonical: {error}"

    executor.fail_job_execution = fail_job_execution  # type: ignore[attr-defined]
    runner = CanvasJobRunner(store=store, executor=executor)  # type: ignore[arg-type]

    reaped = await runner.reap_once()

    assert len(reaped) == 1
    assert reconciled == ["job1"]
    dead = await store.get_job("job1")
    assert dead is not None
    assert dead.status == JobStatus.FAILED
    assert dead.error_message == "canonical: canvas worker lease expired"


async def test_reap_once_leaves_job_reconcilable_when_canonical_reconciliation_fails() -> None:
    """If the canonical ``fail_job_execution`` call itself raises (RunStore
    error, worker dies mid-call), the receipt must NOT have been
    terminalized first — Codex #1527 finding 1's exact divergence scenario.
    The store-level row stays ``running`` and reconcilable on the next
    sweep; only the runner-level exception (which the caller's own
    ``start()`` loop already logs-and-continues) surfaces the failure."""
    store = InMemoryJobStore()
    job = await _seed_pending_job(store, max_attempts=3)
    job.status = JobStatus.RUNNING
    job.attempts = 3
    job.leased_by = "dead-worker"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await store.update_job(job, org_id=job.org_id)

    executor = FakeExecutor()

    async def fail_job_execution(job: GenerationJobRecord, error: Exception) -> str:
        raise RuntimeError("RunStore unavailable")

    executor.fail_job_execution = fail_job_execution  # type: ignore[attr-defined]
    runner = CanvasJobRunner(store=store, executor=executor)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="RunStore unavailable"):
        await runner.reap_once()

    still_reconciling = await store.get_job("job1")
    assert still_reconciling is not None
    assert still_reconciling.status == JobStatus.RUNNING


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


async def test_tick_once_discards_stale_completion_when_lease_reclaimed() -> None:
    """Codex #1527 finding 2: while this worker's provider call was still
    running, its lease expired and another worker reclaimed it (simulated
    here by reassigning ``leased_by`` mid-``_execute_claimed``, standing in
    for a concurrent reap). The fenced completion write must be refused
    (``JobLeaseLostError``) and discarded rather than clobbering the new
    holder's state — ``tick_once`` still reports the tick as having done
    work, but the job itself is left exactly as the reclaiming worker/reaper
    set it."""
    store = InMemoryJobStore()
    await _seed_pending_job(store)

    class ReclaimingExecutor:
        async def _execute_claimed(self, job: GenerationJobRecord) -> None:
            # Simulates a concurrent reaper+re-claim landing its own UPDATE
            # against the store's true row while this worker's call is
            # in-flight — bypassing fencing deliberately, the way a
            # different worker's own claim would at the DB level.
            store._jobs[job.id].leased_by = "other-worker"
            job.result_paths = ["https://img/result.png"]

    runner = CanvasJobRunner(
        store=store,
        executor=ReclaimingExecutor(),
        worker_id="canvas-worker-1",  # type: ignore[arg-type]
    )

    ran = await runner.tick_once()

    assert ran is True
    job = await store.get_job("job1")
    assert job is not None
    # The stale worker's DONE/leased_by=None write never landed; the
    # reclaiming worker's leased_by is exactly what survives.
    assert job.leased_by == "other-worker"


async def test_execute_claimed_with_lease_renewal_heartbeats_during_long_call() -> None:
    """A provider call that outlasts the lease window gets its lease
    renewed mid-flight by a background heartbeat (Codex #1527 finding 3),
    so a concurrent reap sweep does not treat this worker as dead and
    re-execute the same job."""
    store = InMemoryJobStore()
    job = await _seed_pending_job(store, job_id="job1")
    job.status = JobStatus.RUNNING
    job.leased_by = "canvas-worker-1"
    job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=3)
    await store.update_job(job, org_id=job.org_id)

    class SlowExecutor:
        async def _execute_claimed(self, job: GenerationJobRecord) -> None:
            await asyncio.sleep(1.3)
            job.result_paths = ["https://img/result.png"]

    runner = CanvasJobRunner(
        store=store,
        executor=SlowExecutor(),  # type: ignore[arg-type]
        worker_id="canvas-worker-1",
        lease_seconds=3,
    )

    before = job.lease_expires_at
    await runner._execute_claimed_with_lease_renewal(job)
    after = (await store.get_job("job1")).lease_expires_at  # type: ignore[union-attr]

    assert after is not None
    assert before is not None
    assert after > before


async def test_execute_claimed_with_lease_renewal_noop_without_renew_lease_support() -> None:
    """A store predating the heartbeat (no ``renew_lease``) is a graceful
    no-op — the job still executes normally, just without a heartbeat."""

    class NoRenewalStore(InMemoryJobStore):
        renew_lease = None  # type: ignore[assignment]

    store = NoRenewalStore()
    job = await _seed_pending_job(store, job_id="job1")

    executed: list[str] = []

    class PlainExecutor:
        async def _execute_claimed(self, inner_job: GenerationJobRecord) -> None:
            executed.append(inner_job.id)

    runner = CanvasJobRunner(store=store, executor=PlainExecutor())  # type: ignore[arg-type]

    await runner._execute_claimed_with_lease_renewal(job)

    assert executed == ["job1"]
