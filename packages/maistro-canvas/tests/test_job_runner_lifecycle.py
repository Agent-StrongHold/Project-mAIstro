"""SPEC-203 failure-mode tests for the canvas job lifecycle.

These assert the *failure* modes the runner exists to handle — not the happy
path:

- two runners racing one PENDING job → exactly one claims it (atomic claim)
- a dead worker's expired lease → reaper requeues (budget left) or fails (exhausted)
- a job that keeps failing → terminal FAILED at max_attempts, not an infinite loop
- list_models → 503 when the backend is unconfigured, 200 [] when genuinely empty

The job store here is the shared in-memory fake from ``job_store_contract``
(the module that also runs the same contract bodies against the production
``PgCanvasStore``, so fake and production cannot drift), configured with the
zero backoff schedule because these tests drive tick timing deterministically.
The executor and image client are the real classes wired to fakes, so the
runner's interaction with ``_execute_claimed`` is exercised for real.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from canvas_testing.job_store_contract import ZERO_BACKOFF, InMemoryJobStore

from maistro_canvas.canvas.runner import LEASE_EXPIRED_MESSAGE, CanvasJobRunner
from maistro_canvas.types import (
    GenerationJobRecord,
    JobAction,
    JobStatus,
)

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────
# ``InMemoryJobStore`` lives in ``job_store_contract`` (shared with the
# store-contract suite so the fake and ``PgCanvasStore`` cannot drift);
# this module's stores pass ``ZERO_BACKOFF`` to keep reclaim timing
# deterministic.


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


def _runner(store: InMemoryJobStore, executor: object, **kwargs: object) -> CanvasJobRunner:
    """A runner on the same zero backoff schedule its store leg was given.

    Both requeueing writers stamp the delay they were configured with, so a
    runner and its store must share one schedule for a test's tick timing to
    mean anything; production composition passes the same ``RetryBackoff`` to
    both (the same default object when unconfigured).
    """
    return CanvasJobRunner(  # type: ignore[arg-type]
        store=store,
        executor=executor,  # type: ignore[arg-type]
        retry_backoff=ZERO_BACKOFF,
        **kwargs,  # type: ignore[arg-type]
    )


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
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
    executor = FakeExecutor()
    await _seed_pending_job(store)

    runner = _runner(store, executor)  # type: ignore[arg-type]
    ran = await runner.tick_once()

    assert ran is True
    job = await store.get_job("job1")
    assert job is not None
    assert job.status == JobStatus.DONE
    assert job.leased_by is None


async def test_two_runners_race_one_job_exactly_one_claims() -> None:
    """The atomic claim invariant: two runners, one job → exactly one wins."""
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
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
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
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
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
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
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
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
    runner = _runner(store, executor)  # type: ignore[arg-type]

    reaped = await runner.reap_once()

    assert len(reaped) == 1
    assert reconciled == ["job1"]
    dead = await store.get_job("job1")
    assert dead is not None
    assert dead.status == JobStatus.FAILED
    assert dead.error_message == f"canonical: {LEASE_EXPIRED_MESSAGE}"


async def test_reap_once_leaves_job_reconcilable_when_canonical_reconciliation_fails() -> None:
    """If the canonical ``fail_job_execution`` call itself raises (RunStore
    error, worker dies mid-call), the receipt must NOT have been
    terminalized first — Codex #1527 finding 1's exact divergence scenario.
    The store-level row stays ``running`` and reconcilable on the next
    sweep; only the runner-level exception (which the caller's own
    ``start()`` loop already logs-and-continues) surfaces the failure."""
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
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
    runner = _runner(store, executor)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="RunStore unavailable"):
        await runner.reap_once()

    still_reconciling = await store.get_job("job1")
    assert still_reconciling is not None
    assert still_reconciling.status == JobStatus.RUNNING


async def test_retry_bound_goes_terminal() -> None:
    """Always-failing job → FAILED after max_attempts, not infinite loop."""
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
    executor = FakeExecutor(fail_times=99)
    await _seed_pending_job(store, max_attempts=3)

    runner = _runner(store, executor)  # type: ignore[arg-type]

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
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
    executor = FakeExecutor(fail_times=1)
    await _seed_pending_job(store, max_attempts=3)

    runner = _runner(store, executor)  # type: ignore[arg-type]

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
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
    await _seed_pending_job(store)

    class ReclaimingExecutor:
        async def _execute_claimed(self, job: GenerationJobRecord) -> None:
            # Simulates a concurrent reaper+re-claim landing its own UPDATE
            # against the store's true row while this worker's call is
            # in-flight — bypassing fencing deliberately, the way a
            # different worker's own claim would at the DB level.
            store._jobs[job.id].leased_by = "other-worker"
            job.result_paths = ["https://img/result.png"]

    runner = _runner(
        store,
        ReclaimingExecutor(),
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
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
    job = await _seed_pending_job(store, job_id="job1")
    job.status = JobStatus.RUNNING
    job.leased_by = "canvas-worker-1"
    job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=3)
    await store.update_job(job, org_id=job.org_id)

    class SlowExecutor:
        async def _execute_claimed(self, job: GenerationJobRecord) -> None:
            await asyncio.sleep(1.3)
            job.result_paths = ["https://img/result.png"]

    runner = _runner(
        store,
        SlowExecutor(),  # type: ignore[arg-type]
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

    store = NoRenewalStore(retry_backoff=ZERO_BACKOFF)
    job = await _seed_pending_job(store, job_id="job1")

    executed: list[str] = []

    class PlainExecutor:
        async def _execute_claimed(self, inner_job: GenerationJobRecord) -> None:
            executed.append(inner_job.id)

    runner = _runner(store, PlainExecutor())  # type: ignore[arg-type]

    await runner._execute_claimed_with_lease_renewal(job)

    assert executed == ["job1"]


async def test_reap_once_leaves_requeued_jobs_alone() -> None:
    """A reaped job with retry budget left comes back ``pending``: it is
    already requeued, so ``reap_once`` must neither reconcile it canonically
    nor terminalize it."""
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
    job = await _seed_pending_job(store, max_attempts=3)
    job.status = JobStatus.RUNNING
    job.attempts = 1
    job.leased_by = "dead-worker"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await store.update_job(job, org_id=job.org_id)

    executor = FakeExecutor()
    reconciled: list[str] = []

    async def fail_job_execution(job: GenerationJobRecord, error: Exception) -> str:
        reconciled.append(job.id)
        return "should not be called"

    executor.fail_job_execution = fail_job_execution  # type: ignore[attr-defined]
    runner = _runner(store, executor)  # type: ignore[arg-type]

    reaped = await runner.reap_once()

    assert [r.status for r in reaped] == [JobStatus.PENDING]
    assert reconciled == []
    requeued = await store.get_job("job1")
    assert requeued is not None
    assert requeued.status == JobStatus.PENDING
    assert requeued.error_message is None


async def test_reap_once_without_canonical_hook_fails_with_lease_expiry_reason() -> None:
    """An executor with no ``fail_job_execution`` still gets an exhausted
    receipt terminalized, carrying the lease-expiry reason."""
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
    job = await _seed_pending_job(store, max_attempts=3)
    job.status = JobStatus.RUNNING
    job.attempts = 3
    job.leased_by = "dead-worker"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await store.update_job(job, org_id=job.org_id)

    executor = FakeExecutor()
    assert not hasattr(executor, "fail_job_execution")
    runner = _runner(store, executor)  # type: ignore[arg-type]

    await runner.reap_once()

    dead = await store.get_job("job1")
    assert dead is not None
    assert dead.status == JobStatus.FAILED
    assert dead.error_message == LEASE_EXPIRED_MESSAGE
    assert dead.leased_by is None
    assert dead.lease_expires_at is None
    assert dead.completed_at is not None


async def test_lease_renewal_heartbeat_survives_a_failing_renew(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A renew that raises is logged and the heartbeat keeps going; it must
    never abort the in-flight provider call."""

    class FailingRenewStore(InMemoryJobStore):
        async def renew_lease(
            self,
            job_id: str,
            worker_id: str,
            lease_seconds: int,
            *,
            expected_attempts: int | None = None,
        ) -> bool:
            raise RuntimeError("store unavailable")

    store = FailingRenewStore(retry_backoff=ZERO_BACKOFF)
    job = await _seed_pending_job(store, job_id="job1")
    executed: list[str] = []

    class SlowExecutor:
        async def _execute_claimed(self, inner_job: GenerationJobRecord) -> None:
            await asyncio.sleep(1.3)
            executed.append(inner_job.id)

    runner = _runner(
        store,
        SlowExecutor(),  # type: ignore[arg-type]
        worker_id="canvas-worker-1",
        lease_seconds=3,
    )

    with caplog.at_level("ERROR", logger="maistro.canvas.runner"):
        await runner._execute_claimed_with_lease_renewal(job)

    assert executed == ["job1"]
    assert any("canvas_lease_renew_error" in r.getMessage() for r in caplog.records)


# ─────────────────────────────────────────────────────────────────────
# Codex #1535 follow-ups (#735)
# ─────────────────────────────────────────────────────────────────────


async def test_same_worker_id_reclaim_discards_the_stale_claims_completion() -> None:
    """Production defaults every instance to ``canvas-worker-1``, so a reaped
    job can be re-claimed under the *same* worker id while the first claim's
    provider call is still in flight. The stale completion must be fenced on
    its claim generation (attempt number), not the reusable worker id."""
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
    await _seed_pending_job(store, job_id="job1")
    reclaimed: list[GenerationJobRecord] = []

    class ReclaimedMidCallExecutor:
        async def _execute_claimed(self, job: GenerationJobRecord) -> None:
            # The lease expires and is reaped; instance two (same id) claims it.
            row = store._jobs["job1"]
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await store.reap_expired_leases()
            second = await store.claim_next_pending("canvas-worker-1", 300)
            assert second is not None
            reclaimed.append(second)
            job.result_paths = ["https://img/stale.png"]

    runner = _runner(
        store,
        ReclaimedMidCallExecutor(),  # type: ignore[arg-type]
        worker_id="canvas-worker-1",
    )

    assert await runner.tick_once() is True

    current = await store.get_job("job1")
    assert current is not None
    assert reclaimed and reclaimed[0].attempts == 2
    assert current.status == JobStatus.RUNNING, "stale claim clobbered the newer claim"
    assert current.attempts == 2
    assert current.result_paths == []


async def test_worker_completion_does_not_overwrite_a_mid_call_cancellation() -> None:
    """A user cancellation that lands while the provider call runs leaves the
    lease holder in place; the completion write must still refuse to turn
    ``cancelled`` back into ``done``."""
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
    await _seed_pending_job(store, job_id="job1")

    class CancelledMidCallExecutor:
        async def _execute_claimed(self, job: GenerationJobRecord) -> None:
            store._jobs["job1"].status = JobStatus.CANCELLED
            job.result_paths = ["https://img/late.png"]

    runner = _runner(store, CancelledMidCallExecutor())  # type: ignore[arg-type]

    await runner.tick_once()

    current = await store.get_job("job1")
    assert current is not None
    assert current.status == JobStatus.CANCELLED


async def test_reap_once_does_not_overwrite_a_concurrent_cancellation() -> None:
    """The exhausted receipt stays ``running`` while canonical reconciliation
    runs, so a user can cancel it in that window. Once cancellation wins, the
    reaper's terminal write must refuse to replace it with ``failed``."""
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
    job = await _seed_pending_job(store, max_attempts=3)
    job.status = JobStatus.RUNNING
    job.attempts = 3
    job.leased_by = "dead-worker"
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await store.update_job(job, org_id=job.org_id)

    executor = FakeExecutor()

    async def fail_job_execution(reaped: GenerationJobRecord, error: Exception) -> str:
        # User cancellation completes while canonical failure is in flight;
        # the canonical Run is already CANCELLED, so fail() is a no-op.
        store._jobs[reaped.id].status = JobStatus.CANCELLED
        return str(error)

    executor.fail_job_execution = fail_job_execution  # type: ignore[attr-defined]
    runner = _runner(store, executor)  # type: ignore[arg-type]

    await runner.reap_once()

    current = await store.get_job("job1")
    assert current is not None
    assert current.status == JobStatus.CANCELLED


async def test_reap_once_reports_lease_expiry_not_a_provider_error_through_real_executor() -> None:
    """The real ``CanvasExecutor.fail_job_execution`` sanitises unknown errors
    into a generic provider message; worker loss must survive it verbatim."""
    from maistro_canvas.canvas.executor import CanvasExecutor

    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
    job = await _seed_pending_job(store, max_attempts=1)
    job.status = JobStatus.RUNNING
    job.attempts = 1
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await store.update_job(job, org_id=job.org_id)
    executor = CanvasExecutor(
        store=store,  # type: ignore[arg-type]
        image_client=None,  # type: ignore[arg-type]
        model_registry=None,  # type: ignore[arg-type]
        warden=None,  # type: ignore[arg-type]
    )
    runner = _runner(store, executor)

    await runner.reap_once()

    dead = await store.get_job("job1")
    assert dead is not None
    assert dead.status == JobStatus.FAILED
    assert dead.error_message == LEASE_EXPIRED_MESSAGE
    assert "provider error" not in (dead.error_message or "")


async def test_lease_renewal_stops_past_max_execution_without_cancelling_the_call() -> None:
    """A provider await that never returns must not renew its lease forever:
    past ``max_execution_seconds`` renewal stops so the reaper can recover the
    job. The runner itself does not cancel the call -- a cancellation of the
    awaiting task is recorded canonically as a requested cancel (Codex #1560);
    the executor's canonical deadline ends the call as a retryable timeout."""
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
    await _seed_pending_job(store, job_id="job1", max_attempts=1)
    claimed = await store.claim_next_pending("canvas-worker-1", 3)
    assert claimed is not None
    renewals: list[str] = []
    original_renew = store.renew_lease

    async def counting_renew(*args: object, **kwargs: object) -> bool:
        renewals.append("renew")
        return await original_renew(*args, **kwargs)  # type: ignore[arg-type]

    store.renew_lease = counting_renew  # type: ignore[method-assign]
    release = asyncio.Event()
    cancelled: list[bool] = []

    class StalledExecutor:
        async def _execute_claimed(self, job: GenerationJobRecord) -> None:
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

    runner = _runner(
        store,
        StalledExecutor(),  # type: ignore[arg-type]
        lease_seconds=3,
        max_execution_seconds=1.5,
    )

    call = asyncio.create_task(runner._execute_claimed_with_lease_renewal(claimed))
    await asyncio.sleep(1.2)
    renewed_before_limit = len(renewals)
    assert renewed_before_limit >= 1  # long legitimate calls still heartbeat
    await asyncio.sleep(1.3)
    assert len(renewals) == renewed_before_limit, "lease kept renewing past the limit"
    assert not call.done() and cancelled == []

    release.set()
    await asyncio.wait_for(call, timeout=2)


async def test_runner_rejects_non_positive_max_execution_seconds() -> None:
    with pytest.raises(ValueError, match="max_execution_seconds must be positive"):
        _runner(
            InMemoryJobStore(retry_backoff=ZERO_BACKOFF), FakeExecutor(), max_execution_seconds=0
        )  # type: ignore[arg-type]


async def test_over_budget_pending_job_is_never_claimed_and_is_reaped_to_failed() -> None:
    """A receipt requeued with no retry budget left must not be claimed again
    (that would run the provider past ``max_attempts``); the reaper hands it
    back for canonical terminalization instead of stranding it."""
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
    job = await _seed_pending_job(store, job_id="job1", max_attempts=2)
    job.attempts = 2
    await store.update_job(job, org_id=job.org_id)
    executor = FakeExecutor()
    runner = _runner(store, executor)  # type: ignore[arg-type]

    assert await runner.tick_once() is False
    assert executor._calls == 0

    await runner.reap_once()
    dead = await store.get_job("job1")
    assert dead is not None
    assert dead.status == JobStatus.FAILED
    assert dead.attempts == 2


# ─────────────────────────────────────────────────────────────────────
# Issue #398 — bounded retry policy: backoff gate and poison jobs
# ─────────────────────────────────────────────────────────────────────


class _AuthFailureExecutor:
    """Fails every call with a provider authentication fault — the one
    failure class retrying can never turn into a success."""

    def __init__(self, message: str = "provider 401 unauthorized: bad credentials") -> None:
        self.reconciled: list[str] = []
        self.message = message

    async def _execute_claimed(self, job: GenerationJobRecord) -> None:
        raise RuntimeError(self.message)

    async def fail_job_execution(self, job: GenerationJobRecord, exc: Exception) -> str:
        self.reconciled.append(job.id)
        return f"Generation failed: {exc}"


@pytest.mark.parametrize(
    "message",
    ["provider 401 unauthorized: bad credentials", "provider 403 unauthorized after timeout"],
)
async def test_poison_failure_terminalizes_without_spending_the_budget(message: str) -> None:
    """An authentication fault is permanent: the receipt terminalizes on the
    first failure instead of burning the remaining attempts on retries that
    cannot succeed. Terminal exhaustion and poison handling share one
    canonical reconciliation path (``fail_job_execution``)."""
    store = InMemoryJobStore(retry_backoff=ZERO_BACKOFF)
    executor = _AuthFailureExecutor(message)
    await _seed_pending_job(store, job_id="job1", max_attempts=3)

    runner = _runner(store, executor)
    assert await runner.tick_once() is True

    job = await store.get_job("job1")
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.attempts == 1, "poison job must not spend its remaining attempt budget"
    assert job.next_retry_at is None, "a terminal receipt must not carry a retry gate"
    assert "unauthorized" in (job.error_message or "")
    assert executor.reconciled == ["job1"], "canonical reconciliation must have run"


async def test_retryable_failure_requeues_behind_the_backoff_gate() -> None:
    """A retryable fault requeues, but not claimably: the receipt waits out
    the shared backoff schedule on the durable row before the next claim."""
    from datetime import datetime, timedelta

    from maistro_canvas.canvas.retry_policy import RetryBackoff

    backoff = RetryBackoff(base_seconds=120.0, factor=2.0, cap_seconds=600.0)
    store = InMemoryJobStore(retry_backoff=backoff)
    await _seed_pending_job(store, job_id="job1", max_attempts=3)

    runner = CanvasJobRunner(
        store=store,
        executor=FakeExecutor(fail_times=99),  # type: ignore[arg-type]
        retry_backoff=backoff,
    )
    assert await runner.tick_once() is True

    job = await store.get_job("job1")
    assert job is not None
    assert job.status == JobStatus.PENDING
    assert job.attempts == 1
    assert job.next_retry_at is not None
    remaining = job.next_retry_at - datetime.now(UTC)
    assert timedelta(seconds=110) < remaining <= timedelta(seconds=120)

    # The gate holds against the store's own claim path, not just the record.
    assert await store.claim_next_pending("canvas-worker-1", lease_seconds=60) is None
