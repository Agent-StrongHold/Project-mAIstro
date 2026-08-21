"""Tests for maistro.tasks.runner — TaskRunner (worker pool over TaskQueue)."""

from __future__ import annotations

import asyncio

import pytest

from maistro.agents.types import CodeOutput, ConductorOutput
from maistro.tasks.lanes import Lane, LaneGate
from maistro.tasks.models import TaskCreate, TaskResult, TaskStatus
from maistro.tasks.queue import TaskQueue
from maistro.tasks.runner import TaskRunner


async def success_executor(_request: TaskCreate) -> ConductorOutput:
    return ConductorOutput(
        success=True,
        code=CodeOutput(files_changed=["a.py"], description="changed a file"),
        final_answer="done",
    )


async def failure_executor(_request: TaskCreate) -> ConductorOutput:
    return ConductorOutput(success=False, final_answer="boom")


async def raising_executor(_request: TaskCreate) -> ConductorOutput:
    raise RuntimeError("executor blew up")


class FakeWebhook:
    def __init__(self, *, fail: bool = False) -> None:
        self.notified: list[object] = []
        self.closed = False
        self._fail = fail

    async def notify(self, payload: object) -> None:
        if self._fail:
            raise RuntimeError("webhook unreachable")
        self.notified.append(payload)

    async def aclose(self) -> None:
        self.closed = True


async def make_task(queue: TaskQueue, description: str = "do thing") -> str:
    response = await queue.submit(TaskCreate(description=description))
    return response.task_id


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_sets_running_and_creates_worker_task(self) -> None:
        queue = TaskQueue()
        runner = TaskRunner(queue, success_executor)
        await runner.start()
        assert runner._running is True
        assert runner._worker_task is not None
        await runner.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_worker_task_and_closes_webhook(self) -> None:
        queue = TaskQueue()
        webhook = FakeWebhook()
        runner = TaskRunner(queue, success_executor, progress_webhook=webhook)
        await runner.start()
        await runner.stop()
        assert runner._running is False
        assert webhook.closed is True

    @pytest.mark.asyncio
    async def test_stop_drains_active_tasks_within_timeout(self) -> None:
        queue = TaskQueue()
        runner = TaskRunner(queue, success_executor)
        task_id = await make_task(queue)

        async def slow() -> None:
            await asyncio.sleep(0.05)

        t = asyncio.create_task(slow())
        runner._active_tasks.add(t)
        await runner.start()
        await runner.stop(drain_timeout=1.0)
        assert t not in runner._active_tasks or t.done()
        del task_id

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks_exceeding_drain_timeout(self) -> None:
        queue = TaskQueue()
        runner = TaskRunner(queue, success_executor)

        async def hangs() -> None:
            await asyncio.sleep(10)

        t = asyncio.create_task(hangs())
        runner._active_tasks.add(t)
        await runner.start()
        await runner.stop(drain_timeout=0.01)
        assert t.cancelled() or t.done()


class TestDrain:
    @pytest.mark.asyncio
    async def test_drain_waits_for_active_tasks_then_stops_worker(self) -> None:
        queue = TaskQueue()
        runner = TaskRunner(queue, success_executor)

        async def quick() -> None:
            await asyncio.sleep(0.01)

        t = asyncio.create_task(quick())
        runner._active_tasks.add(t)
        await runner.start()
        await runner.drain(timeout=1)
        assert runner._draining is False
        assert runner._running is False

    @pytest.mark.asyncio
    async def test_drain_cancels_tasks_exceeding_timeout(self) -> None:
        queue = TaskQueue()
        runner = TaskRunner(queue, success_executor)

        async def hangs() -> None:
            await asyncio.sleep(10)

        t = asyncio.create_task(hangs())
        runner._active_tasks.add(t)
        await runner.start()
        await runner.drain(timeout=0)
        assert t.cancelled() or t.done()

    @pytest.mark.asyncio
    async def test_drain_with_webhook_closes_it(self) -> None:
        queue = TaskQueue()
        webhook = FakeWebhook()
        runner = TaskRunner(queue, success_executor, progress_webhook=webhook)
        await runner.start()
        await runner.drain(timeout=1)
        assert webhook.closed is True


class TestDispatcherLoop:
    @pytest.mark.asyncio
    async def test_timeout_with_no_tasks_keeps_looping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("maistro.tasks.runner.WORKER_POLL_TIMEOUT", 0.01)
        queue = TaskQueue()
        runner = TaskRunner(queue, success_executor)
        await runner.start()
        await asyncio.sleep(0.05)
        assert runner._worker_task is not None
        assert not runner._worker_task.done()
        await runner.stop()

    @pytest.mark.asyncio
    async def test_dispatches_submitted_task_to_executor(self) -> None:
        queue = TaskQueue()
        runner = TaskRunner(queue, success_executor)
        await runner.start()
        task_id = await make_task(queue)
        for _ in range(50):
            task = queue.get(task_id)
            assert task is not None
            if task.status == TaskStatus.COMPLETED:
                break
            await asyncio.sleep(0.02)
        await runner.stop()
        task = queue.get(task_id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED


class TestRunWithPermit:
    @pytest.mark.asyncio
    async def test_success_releases_permit(self) -> None:
        queue = TaskQueue()
        runner = TaskRunner(queue, success_executor)
        runner._gate = LaneGate(4, live_reserved=2, background_reserved=1)
        await runner._gate.acquire(Lane.BACKGROUND)
        task_id = await make_task(queue)
        await runner._run_with_permit(task_id, Lane.BACKGROUND)
        assert runner._gate.held(Lane.BACKGROUND) == 0
        task = queue.get(task_id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_exception_marks_task_failed_and_releases_permit(self) -> None:
        queue = TaskQueue()
        runner = TaskRunner(queue, raising_executor)
        runner._gate = LaneGate(4, live_reserved=2, background_reserved=1)
        await runner._gate.acquire(Lane.BACKGROUND)
        task_id = await make_task(queue)
        await runner._run_with_permit(task_id, Lane.BACKGROUND)
        task = queue.get(task_id)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert task.result is not None
        assert task.result.error == "executor blew up"
        assert runner._gate.held(Lane.BACKGROUND) == 0

    @pytest.mark.asyncio
    async def test_cancelled_error_marks_task_failed_and_releases_permit(self) -> None:
        async def cancels(_request: TaskCreate) -> ConductorOutput:
            raise asyncio.CancelledError

        queue = TaskQueue()
        runner = TaskRunner(queue, cancels)
        runner._gate = LaneGate(4, live_reserved=2, background_reserved=1)
        await runner._gate.acquire(Lane.BACKGROUND)
        task_id = await make_task(queue)
        await runner._run_with_permit(task_id, Lane.BACKGROUND)
        task = queue.get(task_id)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert task.result is not None
        assert task.result.error == "Task cancelled during shutdown"
        assert runner._gate.held(Lane.BACKGROUND) == 0


class TestEmitProgressWebhook:
    @pytest.mark.asyncio
    async def test_no_webhook_returns_immediately(self) -> None:
        queue = TaskQueue()
        runner = TaskRunner(queue, success_executor)
        await runner._emit_progress_webhook("nonexistent")

        assert runner._progress_webhook is None

    @pytest.mark.asyncio
    async def test_missing_task_returns_without_notifying(self) -> None:
        queue = TaskQueue()
        webhook = FakeWebhook()
        runner = TaskRunner(queue, success_executor, progress_webhook=webhook)
        await runner._emit_progress_webhook("nonexistent")
        assert webhook.notified == []

    @pytest.mark.asyncio
    async def test_notifies_webhook_with_existing_task(self) -> None:
        queue = TaskQueue()
        webhook = FakeWebhook()
        runner = TaskRunner(queue, success_executor, progress_webhook=webhook)
        task_id = await make_task(queue)
        await runner._emit_progress_webhook(task_id)
        assert len(webhook.notified) == 1

    @pytest.mark.asyncio
    async def test_webhook_failure_is_swallowed(self) -> None:
        queue = TaskQueue()
        webhook = FakeWebhook(fail=True)
        runner = TaskRunner(queue, success_executor, progress_webhook=webhook)
        task_id = await make_task(queue)
        await runner._emit_progress_webhook(task_id)

        assert webhook.notified == []


class TestExecuteTask:
    @pytest.mark.asyncio
    async def test_missing_task_returns_early(self) -> None:
        queue = TaskQueue()
        runner = TaskRunner(queue, success_executor)
        task_id = await make_task(queue)
        await runner._execute_task("nonexistent")

        task = queue.get(task_id)
        assert task is not None
        assert task.status == TaskStatus.QUEUED

    @pytest.mark.asyncio
    async def test_success_path_sets_completed_with_files_changed(self) -> None:
        queue = TaskQueue()
        runner = TaskRunner(queue, success_executor)
        task_id = await make_task(queue)
        await runner._execute_task(task_id)
        task = queue.get(task_id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.result == TaskResult(files_changed=["a.py"])

    @pytest.mark.asyncio
    async def test_success_with_no_code_defaults_files_changed_empty(self) -> None:
        async def success_no_code(_request: TaskCreate) -> ConductorOutput:
            return ConductorOutput(success=True, code=None, final_answer="done")

        queue = TaskQueue()
        runner = TaskRunner(queue, success_no_code)
        task_id = await make_task(queue)
        await runner._execute_task(task_id)
        task = queue.get(task_id)
        assert task is not None
        assert task.result is not None
        assert task.result.files_changed == []

    @pytest.mark.asyncio
    async def test_failure_path_sets_failed_with_final_answer_as_error(self) -> None:
        queue = TaskQueue()
        runner = TaskRunner(queue, failure_executor)
        task_id = await make_task(queue)
        await runner._execute_task(task_id)
        task = queue.get(task_id)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert task.result is not None
        assert task.result.error == "boom"


class TestLaneReservation:
    """ADR-010's acceptance criteria. These build the gate the way `start()`
    does rather than running the dispatcher, so they assert admission policy
    without depending on worker-loop timing."""

    def _gate_for(self, runner: TaskRunner) -> LaneGate:
        return LaneGate(
            runner._max_workers,
            live_reserved=runner._live_slots,
            background_reserved=runner._background_slots,
        )

    @pytest.mark.asyncio
    async def test_live_task_runs_when_background_pool_is_full(self) -> None:
        runner = TaskRunner(TaskQueue(), success_executor, max_workers=4)
        gate = self._gate_for(runner)
        # Defaults are live=2, background=1, so exactly one permit is shared:
        # background's floor plus that shared permit saturates everything it
        # is allowed to touch.
        saturating = runner._background_slots + (
            runner._max_workers - runner._live_slots - runner._background_slots
        )
        for _ in range(saturating):
            await gate.acquire(Lane.BACKGROUND, "P5")
        assert gate.stats()["shared_free"] == 0
        with pytest.raises(TimeoutError):  # background genuinely cannot take more
            await asyncio.wait_for(gate.acquire(Lane.BACKGROUND, "P5"), timeout=0.05)
        # The reserved slot is what makes this succeed rather than block.
        await asyncio.wait_for(gate.acquire(Lane.LIVE, "P0"), timeout=0.5)
        assert gate.held(Lane.LIVE) == 1

    @pytest.mark.asyncio
    async def test_defaults_shrink_rather_than_breaking_small_pools(self) -> None:
        """A runner predating lanes (max_workers=1 or 2) must still construct."""
        for mw in (1, 2, 3, 8):
            runner = TaskRunner(TaskQueue(), success_executor, max_workers=mw)
            assert runner._live_slots + runner._background_slots <= mw
            self._gate_for(runner)  # must not raise

    @pytest.mark.asyncio
    async def test_explicit_floors_are_validated_not_clamped(self) -> None:
        """Only defaults adapt. Silently shrinking an operator's explicit floor
        would make the guarantee they asked for quietly untrue."""
        runner = TaskRunner(
            TaskQueue(), success_executor, max_workers=2, live_slots=2, background_slots=2
        )
        with pytest.raises(ValueError, match="exceed total"):
            self._gate_for(runner)

    @pytest.mark.asyncio
    async def test_task_lane_and_tier_drive_admission(self) -> None:
        queue = TaskQueue()
        runner = TaskRunner(queue, success_executor, max_workers=4)
        response = await queue.submit(
            TaskCreate(description="interactive", lane=Lane.LIVE, priority_tier="P0")
        )
        assert runner._schedule_of(response.task_id) == (Lane.LIVE, "P0")

    @pytest.mark.asyncio
    async def test_lane_survives_the_queue_round_trip(self) -> None:
        """The label has to be stored, not just accepted. Before TaskResponse
        carried these fields, submit() dropped them and every task reached the
        dispatcher as BACKGROUND/P2 regardless of what the caller asked for."""
        queue = TaskQueue()
        response = await queue.submit(
            TaskCreate(description="interactive", lane=Lane.LIVE, priority_tier="P1")
        )
        stored = queue.get(response.task_id)
        assert stored is not None
        assert (stored.lane, stored.priority_tier) == (Lane.LIVE, "P1")

    @pytest.mark.asyncio
    async def test_default_task_is_background_p2(self) -> None:
        queue = TaskQueue()
        runner = TaskRunner(queue, success_executor)
        response = await queue.submit(TaskCreate(description="batch"))
        assert runner._schedule_of(response.task_id) == (Lane.BACKGROUND, "P2")

    @pytest.mark.asyncio
    async def test_missing_task_still_yields_a_releasable_lane(self) -> None:
        """A task removed between dequeue and lookup must not leave the
        dispatcher without a lane to release against."""
        runner = TaskRunner(TaskQueue(), success_executor)
        assert runner._schedule_of("does-not-exist") == (Lane.BACKGROUND, "P2")


class TestDispatcherDoesNotHeadOfLineBlock:
    """The dispatcher used to `await gate.acquire(...)` inline, which meant the
    single loop blocked on whatever was at the head of the FIFO. A later
    LIVE/P0 task could not overtake it even with LIVE reservations sitting
    free, and the gate never held more than one waiter, so its tier heap had
    nothing to order. These assert the behaviour the lanes exist to provide.
    """

    @pytest.mark.asyncio
    async def test_live_task_overtakes_a_blocked_background_queue(self) -> None:
        started: list[str] = []
        release = asyncio.Event()

        async def slow_executor(request: TaskCreate) -> ConductorOutput:
            started.append(request.description)
            if request.description.startswith("bg"):
                await release.wait()
            return ConductorOutput(success=True, final_answer="ok")

        queue = TaskQueue()
        runner = TaskRunner(queue, slow_executor, max_workers=4)
        await runner.start()
        try:
            # Saturate everything BACKGROUND is allowed to touch (floor +
            # shared), then queue one more that cannot be admitted.
            for i in range(3):
                await queue.submit(TaskCreate(description=f"bg{i}"))
            await asyncio.sleep(0.15)
            await queue.submit(TaskCreate(description="live", lane=Lane.LIVE, priority_tier="P0"))
            # The LIVE task must start on its reserved floor while the extra
            # BACKGROUND task is still waiting.
            for _ in range(50):
                if "live" in started:
                    break
                await asyncio.sleep(0.02)
            assert "live" in started, f"LIVE never started; started={started}"
        finally:
            release.set()
            await runner.stop(drain_timeout=2.0)

    @pytest.mark.asyncio
    async def test_queued_tasks_become_concurrent_waiters_on_the_gate(self) -> None:
        """Tier ordering can only work if more than one task waits at once."""
        release = asyncio.Event()

        async def blocking_executor(_request: TaskCreate) -> ConductorOutput:
            await release.wait()
            return ConductorOutput(success=True, final_answer="ok")

        queue = TaskQueue()
        runner = TaskRunner(queue, blocking_executor, max_workers=4)
        await runner.start()
        try:
            for i in range(10):
                await queue.submit(TaskCreate(description=f"t{i}"))
            await asyncio.sleep(0.25)
            assert runner._gate is not None
            waiting = runner._gate.stats()["waiting"]
            assert waiting > 1, f"expected several concurrent waiters, got {waiting}"
        finally:
            release.set()
            await runner.stop(drain_timeout=2.0)
