"""CanvasJobRunner — claim/retry mechanics projected over canonical execution.

The Canvas store still owns queue claims, worker leases, retry budget, and the
user-facing GenerationJobRecord receipt. Physical provider work is delegated to
CanvasExecutor, which records it as canonical Attempts. This runner therefore
must never terminalize the receipt without reconciling the canonical Run first.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from maistro_canvas.canvas.executor import CanvasExecutor
    from maistro_canvas.types import GenerationJobRecord

logger = logging.getLogger("maistro.canvas.runner")


class CanvasJobRunner:
    """Background job runner with atomic claim, lease reaping, and bounded retries."""

    def __init__(
        self,
        *,
        store: Any,
        executor: CanvasExecutor,
        worker_id: str = "canvas-worker-1",
        lease_seconds: int = 300,
        poll_interval: float = 1.0,
        reap_interval: float = 30.0,
    ) -> None:
        self._store = store
        self._executor = executor
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._poll_interval = poll_interval
        self._reap_interval = reap_interval
        self._running = False

    async def start(self) -> None:
        """Run the poll loop until stop() is called."""
        self._running = True
        logger.info("canvas_runner_started worker=%s", self._worker_id)
        reap_counter = 0.0
        while self._running:
            try:
                await self.tick_once()
            except Exception:
                logger.exception("canvas_runner_tick_error")
            reap_counter += self._poll_interval
            if reap_counter >= self._reap_interval:
                reap_counter = 0.0
                try:
                    await self.reap_once()
                except Exception:
                    logger.exception("canvas_runner_reap_error")
            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False

    async def reap_once(self) -> list[GenerationJobRecord]:
        """Reap expired Canvas leases and reconcile exhausted jobs canonically.

        ``reap_expired_leases`` only requeues candidates with retry budget
        left (returned already ``pending``); a candidate at its retry
        ceiling comes back still ``running`` — its stale lease holder
        cleared, but not yet terminal — specifically so this method decides
        when it becomes ``failed``: only after canonical reconciliation
        (``fail_job_execution``) has actually run and returned. If that call
        raises, or this worker dies before the follow-up ``update_job``
        commits, the row stays ``running`` with its already-expired lease
        and is picked up again on the next sweep — it never silently
        diverges from its canonical Run/NodeRun/Attempt.
        """
        from maistro_canvas.types import JobStatus

        reaped: list[GenerationJobRecord] = await self._store.reap_expired_leases()
        terminal_failure = getattr(self._executor, "fail_job_execution", None)
        for job in reaped:
            if job.status != JobStatus.RUNNING:
                continue
            error = RuntimeError(job.error_message or "canvas worker lease expired")
            if terminal_failure is not None:
                job.error_message = await terminal_failure(job, error)
            else:
                # Compatibility for runner-focused test doubles whose executor
                # predates the canonical adapter and has no reconciliation to run.
                job.error_message = job.error_message or str(error)
            job.status = JobStatus.FAILED
            job.completed_at = job.completed_at or datetime.now(UTC)
            job.leased_by = None
            job.lease_expires_at = None
            # Scope rides the receipt (#857): the reaper reconciles the
            # job under the org it was admitted in, never a global one.
            await self._store.update_job(job, org_id=job.org_id)
        return reaped

    async def tick_once(self) -> bool:
        """Claim and execute one job. Returns True if work was done."""
        from maistro_canvas.types import JobLeaseLostError, JobStatus

        # A real CanvasExecutor exposes this flag. Refuse before taking a lease
        # when production composition forgot the canonical binding: claiming
        # first would make an unavailable execution path look like worker loss.
        # Runner-focused test doubles predate the adapter and intentionally omit
        # the attribute, so None preserves their narrow claim/retry contract.
        if getattr(self._executor, "canonical_enabled", None) is False:
            raise RuntimeError(
                "CanvasJobRunner requires canonical execution binding before claiming provider work"
            )

        # Reconciliation precedes claiming. A process can die after canonical
        # admission and before the Canvas receipt insert; the canonical Run is
        # the durable recovery owner and recreates that receipt here.
        reconcile = getattr(self._executor, "reconcile_admissions", None)
        if reconcile is not None:
            await reconcile()

        job = await self._store.claim_next_pending(self._worker_id, self._lease_seconds)
        if job is None:
            return False

        logger.info(
            "canvas_job_claimed job=%s worker=%s attempt=%d", job.id, self._worker_id, job.attempts
        )

        try:
            await self._execute_claimed_with_lease_renewal(job)
            job.status = JobStatus.DONE
            job.completed_at = datetime.now(UTC)
            job.leased_by = None
            job.lease_expires_at = None
        except Exception as exc:
            logger.warning("canvas_job_failed job=%s error=%s", job.id, str(exc)[:200])
            if job.attempts < job.max_attempts:
                # The canonical Attempt has already failed and parked its
                # NodeRun. Requeueing is a Canvas retry-policy decision; the
                # next claim calls retry_node under that same NodeRun.
                job.status = JobStatus.PENDING
                job.leased_by = None
                job.lease_expires_at = None
            else:
                terminal_failure = getattr(self._executor, "fail_job_execution", None)
                if terminal_failure is not None:
                    job.error_message = await terminal_failure(job, exc)
                else:
                    # Compatibility for runner-focused test doubles. The real
                    # CanvasExecutor always provides fail_job_execution and
                    # sanitizes before the domain receipt becomes terminal.
                    job.error_message = f"Generation failed: {str(exc)[:500]}"
                job.status = JobStatus.FAILED
                job.completed_at = datetime.now(UTC)
                job.leased_by = None
                job.lease_expires_at = None

        try:
            await self._store.update_job(job, org_id=job.org_id, expected_leased_by=self._worker_id)
        except JobLeaseLostError:
            # The lease expired and was reaped (another worker may now hold
            # it, or a retry is pending) before this completion write landed.
            # This worker's result is stale; discard it rather than clobber
            # whatever the new holder — or the reaper — has since written.
            logger.warning(
                "canvas_job_lease_reclaimed job=%s worker=%s; discarding stale completion",
                job.id,
                self._worker_id,
            )
        return True

    async def _execute_claimed_with_lease_renewal(self, job: GenerationJobRecord) -> None:
        """Run one claimed job while periodically renewing its lease.

        Provider calls (image generation) can outlast a single
        ``lease_seconds`` window. Without a heartbeat, `reap_expired_leases`
        would treat this worker as dead partway through and let another
        worker reclaim and re-execute the same job while the original
        provider call is still in flight — canonical Attempt fencing guards
        the Run/NodeRun/Attempt records but cannot cancel an in-flight
        external provider request, so this risks a duplicate paid
        generation. A store without `renew_lease` (a narrow test double
        predating it) simply gets no heartbeat, matching prior behavior.
        """
        renew = getattr(self._store, "renew_lease", None)
        if renew is None:
            await self._executor._execute_claimed(job)
            return

        interval = max(1.0, self._lease_seconds / 3)

        async def _heartbeat() -> None:
            while True:
                await asyncio.sleep(interval)
                try:
                    await renew(job.id, self._worker_id, self._lease_seconds)
                except Exception:
                    logger.exception("canvas_lease_renew_error job=%s", job.id)

        heartbeat = asyncio.create_task(_heartbeat())
        try:
            await self._executor._execute_claimed(job)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
