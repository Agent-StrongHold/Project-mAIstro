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

#: Receipt/Run error for a job whose worker lease expired at its retry ceiling.
#: Preclassified (Codex #1535): worker loss is not a provider failure, and the
#: generic sanitiser would otherwise report it as one.
LEASE_EXPIRED_MESSAGE = "Generation failed: canvas worker lease expired before the job completed."


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
        max_execution_seconds: float = 1800.0,
    ) -> None:
        if max_execution_seconds <= 0:
            raise ValueError("max_execution_seconds must be positive")
        self._store = store
        self._executor = executor
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._poll_interval = poll_interval
        self._reap_interval = reap_interval
        self._max_execution_seconds = max_execution_seconds
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

        The terminal write is a compare-and-set on ``running`` at the reaped
        claim generation: a user cancellation can land while
        ``fail_job_execution`` runs, and its ``cancelled`` receipt (matching an
        already-cancelled canonical Run) must not be overwritten as
        ``failed`` (Codex #1535).
        """
        from maistro_canvas.canvas.executor import PreclassifiedJobFailure
        from maistro_canvas.types import JobLeaseLostError, JobStatus

        reaped: list[GenerationJobRecord] = await self._store.reap_expired_leases()
        terminal_failure = getattr(self._executor, "fail_job_execution", None)
        for job in reaped:
            if job.status != JobStatus.RUNNING:
                continue
            error = PreclassifiedJobFailure(LEASE_EXPIRED_MESSAGE)
            if terminal_failure is not None:
                job.error_message = await terminal_failure(job, error)
            else:
                # Compatibility for runner-focused test doubles whose executor
                # predates the canonical adapter and has no reconciliation to run.
                job.error_message = str(error)
            job.status = JobStatus.FAILED
            job.completed_at = job.completed_at or datetime.now(UTC)
            job.leased_by = None
            job.lease_expires_at = None
            # Scope rides the receipt (#857): the reaper reconciles the
            # job under the org it was admitted in, never a global one.
            try:
                await self._store.update_job(
                    job,
                    org_id=job.org_id,
                    expected_status=JobStatus.RUNNING,
                    expected_attempts=job.attempts,
                )
            except JobLeaseLostError:
                logger.warning(
                    "canvas_reap_terminal_superseded job=%s; a concurrent terminal write won",
                    job.id,
                )
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
        claimed_attempt = job.attempts

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

        # Fence on this exact claim: the worker id alone is reusable (every
        # production instance defaults to the same id), so the claim's
        # attempt number pins the generation, and ``running`` refuses to
        # replace a cancellation that landed while the provider call ran.
        try:
            await self._store.update_job(
                job,
                org_id=job.org_id,
                expected_leased_by=self._worker_id,
                expected_attempts=claimed_attempt,
                expected_status=JobStatus.RUNNING,
            )
        except JobLeaseLostError:
            # The lease expired and was reaped (another claim — possibly under
            # this same worker id — may now hold it, or a retry is pending),
            # or the receipt was cancelled, before this completion write
            # landed. This worker's result is stale; discard it rather than
            # clobber whatever the newer writer has since written.
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

        Renewal is bounded (Codex #1535): the lease is renewed only for
        ``max_execution_seconds``, then left to expire so the reaper can
        recover a job whose call never returns. The runner does not cancel
        the call itself -- cancelling the awaiting task would be recorded
        canonically as a *requested* cancellation that terminalizes the Run
        (Codex #1560). The deadline that ends the call is the executor's
        ``execution_timeout_s``, enforced by the canonical Runtime as a
        retryable timeout; composition gives both the same value.
        """
        renew = getattr(self._store, "renew_lease", None)
        if renew is None:
            await self._executor._execute_claimed(job)
            return

        interval = max(1.0, self._lease_seconds / 3)
        claimed_attempt = job.attempts
        loop = asyncio.get_running_loop()
        renew_until = loop.time() + self._max_execution_seconds

        async def _heartbeat() -> None:
            while True:
                await asyncio.sleep(interval)
                if loop.time() >= renew_until:
                    logger.error(
                        "canvas_lease_renewal_stopped job=%s limit=%ss; lease left to expire",
                        job.id,
                        self._max_execution_seconds,
                    )
                    return
                try:
                    await renew(
                        job.id,
                        self._worker_id,
                        self._lease_seconds,
                        expected_attempts=claimed_attempt,
                    )
                except Exception:
                    logger.exception("canvas_lease_renew_error job=%s", job.id)

        heartbeat = asyncio.create_task(_heartbeat())
        try:
            await self._executor._execute_claimed(job)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
