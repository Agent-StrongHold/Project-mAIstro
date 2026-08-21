"""Tests for maistro.a2a.lifecycle — TaskQueue, WorkerPool, TaskLifecycleManager."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro.a2a.delegate import TaskStatus
from maistro.a2a.lifecycle import TaskLifecycleManager, TaskQueue, WorkerConfig, WorkerPool


class TestWorkerConfig:
    def test_defaults(self) -> None:
        config = WorkerConfig()
        assert config.max_workers == 4
        assert config.task_timeout_seconds == 300
        assert config.max_retries == 3
        assert config.retry_delay_seconds == 5


class TestTaskQueue:
    @pytest.mark.asyncio
    async def test_enqueue_returns_task_id(self) -> None:
        queue = TaskQueue()
        task_id = await queue.enqueue({"name": "t1"}, priority="P1")
        assert isinstance(task_id, str)
        assert task_id

    @pytest.mark.asyncio
    async def test_dequeue_specific_priority(self) -> None:
        queue = TaskQueue()
        await queue.enqueue({"name": "t1"}, priority="P1")
        task = await queue.dequeue(priority="P1")
        assert task is not None
        assert task["name"] == "t1"

    @pytest.mark.asyncio
    async def test_dequeue_specific_priority_empty_falls_through_to_order(self) -> None:
        queue = TaskQueue()
        await queue.enqueue({"name": "low"}, priority="P3")
        task = await queue.dequeue(priority="P1")
        assert task is not None
        assert task["name"] == "low"

    @pytest.mark.asyncio
    async def test_dequeue_without_priority_uses_priority_order(self) -> None:
        queue = TaskQueue()
        await queue.enqueue({"name": "low"}, priority="P3")
        await queue.enqueue({"name": "high"}, priority="P0")
        first = await queue.dequeue()
        second = await queue.dequeue()
        assert first is not None and first["name"] == "high"
        assert second is not None and second["name"] == "low"

    @pytest.mark.asyncio
    async def test_dequeue_empty_queue_returns_none(self) -> None:
        queue = TaskQueue()
        assert await queue.dequeue() is None

    @pytest.mark.asyncio
    async def test_size_counts_all_priorities(self) -> None:
        queue = TaskQueue()
        await queue.enqueue({"name": "a"}, priority="P0")
        await queue.enqueue({"name": "b"}, priority="P1")
        assert queue.size() == 2

    @pytest.mark.asyncio
    async def test_size_by_priority(self) -> None:
        queue = TaskQueue()
        await queue.enqueue({"name": "a"}, priority="P0")
        await queue.enqueue({"name": "b"}, priority="P0")
        await queue.enqueue({"name": "c"}, priority="P1")
        assert queue.size_by_priority("P0") == 2
        assert queue.size_by_priority("P1") == 1

    def test_size_by_priority_unknown_returns_zero(self) -> None:
        queue = TaskQueue()
        assert queue.size_by_priority("P0") == 0


class TestWorkerPool:
    @pytest.mark.asyncio
    async def test_submit_success(self) -> None:
        pool = WorkerPool(WorkerConfig(max_workers=2))
        await pool.submit("t1", {"name": "t1"})
        assert "t1" in pool.get_active_tasks()

    @pytest.mark.asyncio
    async def test_submit_at_capacity_raises(self) -> None:
        pool = WorkerPool(WorkerConfig(max_workers=1))
        await pool.submit("t1", {"name": "t1"})
        with pytest.raises(RuntimeError, match="capacity"):
            await pool.submit("t2", {"name": "t2"})

    @pytest.mark.asyncio
    async def test_execute_task_success_sets_completed(self) -> None:
        pool = WorkerPool(WorkerConfig(task_timeout_seconds=5))
        task_data: dict[str, object] = {"name": "t1"}
        result = await pool._execute_task("t1", task_data)
        assert result == "t1"
        assert task_data["status"] == TaskStatus.COMPLETED
        assert task_data["result"] == "completed"
        assert "completed_at" in task_data

    @pytest.mark.asyncio
    async def test_execute_task_timeout_exhausts_retries_sets_failed(self) -> None:
        pool = WorkerPool(
            WorkerConfig(task_timeout_seconds=0, max_retries=2, retry_delay_seconds=0)
        )
        task_data: dict[str, object] = {"name": "t1"}
        result = await pool._execute_task("t1", task_data)
        assert result == "t1"
        assert task_data["status"] == TaskStatus.FAILED
        assert task_data["error"] == "Task timeout"

    def test_get_active_tasks_empty(self) -> None:
        pool = WorkerPool()
        assert pool.get_active_tasks() == []

    def test_get_status(self) -> None:
        pool = WorkerPool(WorkerConfig(max_workers=3))
        status = pool.get_status()
        assert status["active_tasks"] == 0
        assert status["max_workers"] == 3
        assert status["available_workers"] == 3


class TestTaskLifecycleManager:
    @pytest.mark.asyncio
    async def test_create_task(self) -> None:
        manager = TaskLifecycleManager()
        task_id = await manager.create_task({"name": "t1"}, priority="P0")
        assert isinstance(task_id, str)
        assert manager.queue.size_by_priority("P0") == 1

    @pytest.mark.asyncio
    async def test_get_task_status_not_found_returns_queued_default(self) -> None:
        manager = TaskLifecycleManager()
        status = await manager.get_task_status("missing")
        assert status == {"status": TaskStatus.QUEUED, "task_id": "missing"}

    @pytest.mark.asyncio
    async def test_get_task_status_found_returns_full_status(self) -> None:
        manager = TaskLifecycleManager()
        manager.workers._active_tasks["t1"] = {
            "status": TaskStatus.COMPLETED,
            "from_agent": "a",
            "to_agent": "b",
            "created_at": datetime.now(UTC),
            "completed_at": datetime.now(UTC),
            "result": "done",
            "error": None,
        }
        status = await manager.get_task_status("t1")
        assert status["status"] == TaskStatus.COMPLETED
        assert status["from_agent"] == "a"
        assert status["to_agent"] == "b"
        assert status["result"] == "done"
        assert status["error"] is None

    @pytest.mark.asyncio
    async def test_get_queue_status(self) -> None:
        manager = TaskLifecycleManager()
        await manager.create_task({"name": "t1"}, priority="P0")
        status = await manager.get_queue_status()
        assert status["queue_size"] == 1
        assert status["queue_by_priority"]["P0"] == 1
        assert status["worker_status"]["max_workers"] == 4
