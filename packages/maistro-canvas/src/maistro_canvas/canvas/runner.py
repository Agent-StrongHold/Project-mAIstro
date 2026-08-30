"""Canvas background worker over canonical generation execution (#735).

The Canvas receipt still owns worker-claim coordination and user-facing domain
state. Once claimed, provider execution and retry lifecycle belong to the
canonical Run/NodeRun/Attempt adapter; the receipt is refreshed from that
evidence rather than independently deciding success/failure.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from maistro_canvas.canvas.canonical_execution import canonical_run_id

if TYPE_CHECKING:
    from maistro_canvas.canvas.canonical_execution import CanvasCanonicalExecution
    from maistro_canvas.canvas.executor import CanvasExecutor

logger = logging.getLogger("maistro.canvas.runner")


class CanvasJobRunner:
    """Claim Canvas work, execute it canonically, and persist the domain receipt."""

    def __init__(
        self,
        *,
        store: Any,
        executor: CanvasExecutor,
        canonical_execution: CanvasCanonicalExecution,
        worker_id: str = "canvas-worker-1",
        lease_seconds: int = 300,
        poll_interval: float = 1.0,
        reap_interval: float = 30.0,
    ) -> None:
        self._store = store
        self._executor = executor
        self._canonical_execution = canonical_execution
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
                    await self._store.reap_expired_leases()
                except Exception:
                    logger.exception("canvas_runner_reap_error")
            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False

    async def tick_once(self) -> bool:
        """Claim one receipt and let canonical execution own provider retries."""
        from maistro_canvas.types import JobStatus

        job = await self._store.claim_next_pending(self._worker_id, self._lease_seconds)
        if job is None:
            return False

        logger.info(
            "canvas_job_claimed job=%s worker=%s receipt_attempt=%d",
            job.id,
            self._worker_id,
            job.attempts,
        )

        newly_admitted = canonical_run_id(job) is None
        try:
            if newly_admitted:
                await self._canonical_execution.admit(job)
                # Persist the Run correlation before physical work starts. If
                # this write fails, compensate the still-QUEUED Run below.
                await self._store.update_job(job)

            await self._canonical_execution.execute(job, executor=self._executor)
        except Exception:
            if newly_admitted:
                await self._canonical_execution.abandon_admission(job)
            # A control-plane/integrity failure is not provider evidence. Leave
            # the receipt retryable so the next worker can recover the Run.
            job.status = JobStatus.PENDING
            job.leased_by = None
            job.lease_expires_at = None
            await self._store.update_job(job)
            raise

        # The adapter projected terminal status/result/error/Attempt count from
        # canonical evidence. The runner owns only its worker lease now.
        job.leased_by = None
        job.lease_expires_at = None
        await self._store.update_job(job)
        return True
