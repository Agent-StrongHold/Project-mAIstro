"""CanvasJobRunner — background worker that claims, executes, and reaps canvas generation jobs.

Poll loop: claim_next_pending → _execute_claimed → mark done/failed/requeue.
Reaper: periodic sweep of expired leases (dead workers).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro_canvas.canvas.executor import _sanitise_error

if TYPE_CHECKING:
    from maistro_canvas.canvas.executor import CanvasExecutor

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
                    await self._store.reap_expired_leases()
                except Exception:
                    logger.exception("canvas_runner_reap_error")
            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False

    async def tick_once(self) -> bool:
        """Claim and execute one job. Returns True if work was done."""
        from maistro_canvas.types import JobStatus

        job = await self._store.claim_next_pending(self._worker_id, self._lease_seconds)
        if job is None:
            return False

        logger.info(
            "canvas_job_claimed job=%s worker=%s attempt=%d", job.id, self._worker_id, job.attempts
        )

        try:
            await self._executor._execute_claimed(job)
            job.status = JobStatus.DONE
            job.completed_at = datetime.now(UTC)
            job.leased_by = None
            job.lease_expires_at = None
        except Exception as exc:
            logger.warning("canvas_job_failed job=%s error=%s", job.id, str(exc)[:200])
            if job.attempts < job.max_attempts:
                # Retryable — requeue
                job.status = JobStatus.PENDING
                job.leased_by = None
                job.lease_expires_at = None
            else:
                # Terminal failure
                job.status = JobStatus.FAILED
                job.error_message = _sanitise_error(exc)
                job.completed_at = datetime.now(UTC)
                job.leased_by = None
                job.lease_expires_at = None

        await self._store.update_job(job)
        return True
