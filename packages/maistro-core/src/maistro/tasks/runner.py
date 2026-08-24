"""Task runner — pulls tasks from the queue and executes them via an injected executor."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from typing import Any

import structlog

from maistro.agents.types import ConductorOutput
from maistro.constants import WORKER_POLL_TIMEOUT
from maistro.tasks.execution import TaskAttemptExecutor, TaskExecutionFailed
from maistro.tasks.lanes import Lane, LaneGate
from maistro.tasks.models import TaskCreate, TaskProgress, TaskResult, TaskStatus
from maistro.tasks.progress_webhook import ProgressWebhookSink, payload_from_task
from maistro.tasks.queue import TaskQueue

logger = structlog.get_logger()

# Default number of concurrent task workers
DEFAULT_MAX_WORKERS = 4

# ADR-010: slots reserved for Lane.LIVE, so an interactive task never queues
# behind a full background pool. The ADR specifies 2. BACKGROUND keeps a
# floor of its own so sustained live traffic cannot starve batch work.
DEFAULT_LIVE_SLOTS = 2
DEFAULT_BACKGROUND_SLOTS = 1

#: How long shutdown waits for one cancelled worker to terminalize its Attempt
#: before giving up on it. Short: this runs after the drain timeout has already
#: expired, and the work itself is over — only its bookkeeping is outstanding.
CANCELLED_SETTLE_TIMEOUT = 5.0

# Type for the injected executor — takes a TaskCreate, returns ConductorOutput
TaskExecutor = Callable[[TaskCreate], Coroutine[Any, Any, ConductorOutput]]


class TaskRunner:
    """Background worker pool that processes tasks from the queue.

    The executor is injected at construction time, breaking the
    bidirectional coupling between tasks/ and agents/ packages.
    """

    def __init__(
        self,
        queue: TaskQueue,
        executor: TaskExecutor,
        max_workers: int = DEFAULT_MAX_WORKERS,
        progress_webhook: ProgressWebhookSink | None = None,
        live_slots: int | None = None,
        background_slots: int | None = None,
        attempts: TaskAttemptExecutor | None = None,
    ) -> None:
        self._queue = queue
        self._executor = executor
        # The canonical execution seam (#143). When it is wired, every task's
        # work runs as a physical Attempt under its Run's NodeRun. When it is
        # not — no Run store in this process, so no Run to hang one on — the
        # executor is called directly, exactly as it always was. That is the
        # same shape as the queue's admitter: the runner does not fabricate an
        # execution record it cannot back with a Run.
        self._attempts = attempts
        self._max_workers = max_workers
        self._progress_webhook = progress_webhook
        self._running = False
        self._draining = False
        # Explicit floors are passed to LaneGate untouched and validated
        # strictly. Only the DEFAULTS adapt to max_workers — a runner built
        # with max_workers=2 predates lanes entirely and must keep working,
        # so the defaults shrink rather than raising on someone else's config.
        #
        # One permit is always held back for the shared pool. Without that,
        # max_workers=1 produced live=0/background=1/shared=0, and a LIVE task
        # could never be admitted even on a completely idle runner — it blocked
        # the dispatcher forever and took every later task with it.
        shareable = max(0, max_workers - 1)
        self._live_slots = (
            live_slots if live_slots is not None else min(DEFAULT_LIVE_SLOTS, shareable)
        )
        self._background_slots = (
            background_slots
            if background_slots is not None
            else min(DEFAULT_BACKGROUND_SLOTS, max(0, shareable - self._live_slots))
        )
        self._gate: LaneGate | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._active_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        self._running = True
        self._gate = LaneGate(
            self._max_workers,
            live_reserved=self._live_slots,
            background_reserved=self._background_slots,
        )
        self._worker_task = asyncio.create_task(self._dispatcher_loop())
        await logger.ainfo(
            "task_runner_started",
            max_workers=self._max_workers,
            live_slots=self._live_slots,
            background_slots=self._background_slots,
        )

    async def stop(self, drain_timeout: float = 30.0) -> None:
        """Stop the runner, waiting for in-progress tasks to drain."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task

        # Drain in-progress tasks with timeout. Snapshot first: the done
        # callback discards from the live set, so it can empty between the
        # check and the wait — and `asyncio.wait([])` raises ValueError.
        active = set(self._active_tasks)
        if active:
            await logger.ainfo("draining_active_tasks", count=len(active))
            _, pending = await asyncio.wait(active, timeout=drain_timeout)
            if pending:
                await self._settle_cancelled(pending)
                await logger.awarning("tasks_cancelled_on_shutdown", count=len(pending))

        if self._progress_webhook:
            await self._progress_webhook.aclose()

        await logger.ainfo("task_runner_stopped")

    async def drain(self, timeout: int = 30) -> None:
        """Graceful shutdown: stop accepting new tasks, wait for current tasks."""
        self._draining = True
        self._running = False
        await logger.ainfo(
            "task_runner_draining", timeout=timeout, active_count=len(self._active_tasks)
        )

        # Snapshot — see the note in `stop()`.
        active = set(self._active_tasks)
        if active:
            _, pending = await asyncio.wait(active, timeout=timeout)
            if pending:
                await self._settle_cancelled(pending)
                await logger.awarning("task_runner_drain_timeout", cancelled=len(pending))

        if self._worker_task:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task

        if self._progress_webhook:
            await self._progress_webhook.aclose()

        self._draining = False
        await logger.ainfo("task_runner_stopped")

    async def _dispatcher_loop(self) -> None:
        """Dequeue continuously; each task waits for its own lane permit.

        Admission is *not* awaited here. It used to be, and that quietly
        defeated the whole point of the gate: the loop blocked on whatever
        happened to be at the head of the FIFO, so a P0 LIVE task sat in
        ``TaskQueue._pending`` behind an ineligible BACKGROUND one even with
        LIVE reservations free. It also meant the gate never held more than a
        single waiter, so its tier heap had nothing to order.

        Spawning the wait per task makes every queued task a concurrent waiter,
        which is what lets tier ordering and the reserved floors actually
        decide who runs next. The waiters are cheap; the gate still bounds how
        many of them execute at once.
        """
        while self._running:
            try:
                task_id = await asyncio.wait_for(
                    self._queue.next_task(), timeout=WORKER_POLL_TIMEOUT
                )
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            lane, tier = self._schedule_of(task_id)
            t = asyncio.create_task(self._admit_and_run(task_id, lane, tier))
            self._active_tasks.add(t)
            t.add_done_callback(self._active_tasks.discard)

    async def _admit_and_run(self, task_id: str, lane: Lane, tier: str) -> None:
        """Wait for a permit in ``lane``, then execute.

        Cancellation while still waiting (shutdown) is clean: ``acquire``
        returns the permit if it had already been handed one, and no task
        state is touched because execution never began.
        """
        assert self._gate is not None
        try:
            await self._gate.acquire(lane, tier)
        except asyncio.CancelledError:
            return
        await self._run_with_permit(task_id, lane)

    def _schedule_of(self, task_id: str) -> tuple[Lane, str]:
        """The task's lane and tier, defaulting to BACKGROUND/P2 (ADR-010).

        A task that vanished between dequeue and lookup still needs a lane to
        release against, so this never returns None — it defaults, and
        ``_execute_task`` handles the missing task separately.
        """
        task = self._queue.get(task_id)
        if task is None:
            return Lane.BACKGROUND, "P2"
        return task.lane, task.priority_tier

    async def _run_with_permit(self, task_id: str, lane: Lane) -> None:
        """Execute a task and return its lane permit when done.

        The lane is passed in rather than re-read from the queue: the task may
        be mutated or removed while running, and releasing against a different
        lane than was acquired would corrupt the gate's per-lane counts.
        """
        assert self._gate is not None
        try:
            await self._execute_task(task_id)
        except asyncio.CancelledError:
            # Graceful shutdown — mark task as failed rather than leaving it stuck
            await self._queue.update_status(
                task_id, TaskStatus.FAILED, error="Task cancelled during shutdown"
            )
            self._queue.set_result(task_id, TaskResult(error="Task cancelled during shutdown"))
            await self._emit_progress_webhook(task_id)
        except Exception as exc:
            await logger.aexception("task_execution_failed", task_id=task_id)
            await self._queue.update_status(task_id, TaskStatus.FAILED, error=str(exc))
            self._queue.set_result(task_id, TaskResult(error=str(exc)))
            await self._emit_progress_webhook(task_id)
        finally:
            self._gate.release(lane)

    async def _settle_cancelled(self, pending: set[asyncio.Task[None]]) -> None:
        """Cancel workers and wait for their cleanup to actually finish.

        Cancelling and returning was enough while a worker's cleanup was purely
        in-memory. It is not now: each in-flight task holds a persisted Attempt,
        and the `CancelledError` handler is what terminalizes it. Returning
        before those handlers run lets the caller close the Run store — or the
        process exit — with an Attempt still recorded as running, which is
        exactly the false "a worker died here" signal recovery reads (#143).

        Bounded, because a worker that ignores cancellation must not hold
        shutdown open forever; what it leaves behind is then a genuine orphan
        for reconciliation rather than one this method created.
        """
        for task in pending:
            task.cancel()
        settled = await asyncio.gather(
            *(asyncio.wait_for(asyncio.shield(t), CANCELLED_SETTLE_TIMEOUT) for t in pending),
            return_exceptions=True,
        )
        stuck = sum(1 for outcome in settled if isinstance(outcome, TimeoutError))
        if stuck:
            await logger.awarning("task_cancellation_did_not_settle", count=stuck)

    async def _execute_work(self, run_id: str | None, request: TaskCreate) -> ConductorOutput:
        """Run the task's work, through the Attempt seam when there is one.

        `run_id` is None whenever the queue admitted without an admitter, and
        the seam is absent whenever this process has no Run store. Either way
        the executor is still called — a task must not stop running because
        nothing is recording it.
        """
        if self._attempts is None or run_id is None:
            return await self._executor(request)
        return await self._attempts.execute(run_id, request, self._executor)

    async def _emit_progress_webhook(self, task_id: str) -> None:
        if self._progress_webhook is None:
            return
        snap = self._queue.get(task_id)
        if snap is None:
            return
        try:
            await self._progress_webhook.notify(payload_from_task(snap))
        except Exception:
            await logger.adebug(
                "progress_webhook_notify_failed",
                task_id=task_id,
                exc_info=True,
            )

    async def _execute_task(self, task_id: str) -> None:
        task = self._queue.get(task_id)
        if task is None:
            return

        async with self._queue.claim(task_id):
            # Planning phase
            if not await self._queue.update_status(task_id, TaskStatus.PLANNING):
                # The canonical Run refused (cancelled, or already terminal),
                # so this work must not run. Ignoring the return value meant a
                # cancelled Run still had its task executed, with the receipt
                # left QUEUED and the result written afterwards describing work
                # nobody asked for.
                await logger.awarning("task_abandoned_run_refused", task_id=task_id)
                return
            self._queue.update_progress(
                task_id, TaskProgress(current="Analyzing task and creating plan...")
            )
            await self._emit_progress_webhook(task_id)

            request = TaskCreate(
                description=task.description,
                workspace=task.workspace,
                tier=task.tier,
                task_type=task.task_type,
                agent_id=task.agent_id,
                capability=task.capability,
                program_context=task.program_context,
                user_id=task.user_id or None,
                lane=task.lane,
                priority_tier=task.priority_tier,
            )

            # Run conductor (single-pass: plan + code in one LLM call)
            if not await self._queue.update_status(task_id, TaskStatus.CODING):
                await logger.awarning("task_abandoned_run_refused", task_id=task_id)
                return
            self._queue.update_progress(
                task_id, TaskProgress(current="Generating implementation...")
            )
            await self._emit_progress_webhook(task_id)

            try:
                result = await self._execute_work(task.run_id, request)
            except TaskExecutionFailed as exc:
                # The Attempt already recorded the failure. The receipt's own
                # failure branch below is unchanged, so a `/tasks` caller reads
                # what it always read.
                result = exc.output

            # Phase 1 is single-pass — transition to COMPLETED or FAILED directly
            # The outcome goes to both: the Run because it is the execution
            # identity a caller follows, the receipt because that is what the
            # /tasks API returns. Passing it only to `set_result` left every
            # terminal Run reporting result=None and error=None.
            if result.success:
                files_changed = result.code.files_changed if result.code else []
                await self._queue.update_status(
                    task_id,
                    TaskStatus.COMPLETED,
                    result={"files_changed": files_changed},
                )
                self._queue.set_result(
                    task_id,
                    TaskResult(files_changed=files_changed),
                )
                await self._emit_progress_webhook(task_id)
            else:
                await self._queue.update_status(
                    task_id, TaskStatus.FAILED, error=result.final_answer
                )
                self._queue.set_result(
                    task_id,
                    TaskResult(error=result.final_answer),
                )
                await self._emit_progress_webhook(task_id)
