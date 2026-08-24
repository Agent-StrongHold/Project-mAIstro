"""TaskBackend boundary (SPEC-226 / ADR-096).

EngineService depends on this Protocol instead of constructing a concrete
TaskQueue/TaskRunner pair. MaistroServerTaskBackend (production default)
calls maistro-server's /tasks API. LocalTaskBackend (demo/dev mode only,
gated behind settings.hive_mode == "demo") wraps the in-process
TaskQueue + TaskRunner.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx

from maistro.http import shared_client
from maistro.tasks.models import TaskCreate, TaskResponse, TaskStatus

_TERMINAL = frozenset({"completed", "failed"})

_STATUS_MAP = {
    "queued": "pending",
    "planning": "running",
    "coding": "running",
    "reviewing": "running",
    "testing": "running",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "failed",
}


class TaskRecord:
    def __init__(self, task: Any) -> None:
        self._task = task

    @property
    def id(self) -> str:
        return self._task.task_id

    @property
    def run_id(self) -> str | None:
        """Canonical execution identity (#41), or None where none was admitted."""
        return getattr(self._task, "run_id", None)

    @property
    def name(self) -> str:
        return self._task.description[:60]

    @property
    def description(self) -> str:
        return self._task.description

    @property
    def mission_status(self) -> str:
        return _STATUS_MAP.get(str(self._task.status), "pending")

    @property
    def progress(self) -> float:
        p = self._task.progress
        if p.subtasks:
            return p.completed / p.subtasks
        if self.mission_status == "completed":
            return 1.0
        return 0.0

    @property
    def current_step(self) -> str:
        return self._task.progress.current or self._task.phase or ""

    @property
    def created_at(self) -> Any:
        return self._task.created_at

    @property
    def started_at(self) -> Any:
        return self._task.started_at

    @property
    def completed_at(self) -> Any:
        return self._task.completed_at

    @property
    def error(self) -> str | None:
        result = self._task.result
        return result.error if result is not None else None

    @property
    def raw(self) -> Any:
        """The underlying TaskResponse — for PM-fleet status logic needing
        task_type/status/description beyond TaskRecord's view."""
        return self._task


#: What an API caller is told when `WorkspaceNotRoutable` reaches a route.
#: Separate from the exception's own message, which names the server this
#: deployment would have submitted to -- that belongs in the log, not in a
#: response body.
WORKSPACE_NOT_ROUTABLE_DETAIL = (
    "this deployment routes tasks to a single-Workspace task server, which "
    "cannot admit work into a named workspace"
)


class WorkspaceNotRoutable(RuntimeError):
    """This backend cannot file work in the Workspace the submission named.

    maistro-server binds one Workspace per instance (ADR-019/ADR-068: one
    instance is one Workspace), so a Conductor that proxies to it has exactly
    one Workspace to offer no matter how many its users belong to. Refusing is
    the honest answer: admitting anyway would file the work in the server's
    default Project while telling the caller it went to theirs, which is the
    silent scope loss #158 exists to remove.
    """


class TaskBackend(Protocol):
    async def submit(
        self, create: TaskCreate, *, user_id: str, workspace_id: str | None = None
    ) -> TaskRecord: ...

    def get(self, task_id: str, *, user_id: str | None = None) -> TaskRecord | None: ...

    def list_tasks(self, *, user_id: str | None = None) -> list[TaskRecord]: ...

    async def cancel(self, task_id: str) -> bool: ...

    async def iter_events(self, task_id: str) -> AsyncIterator[dict[str, Any]]: ...

    async def stop(self) -> None: ...


class LocalTaskBackend:
    """Wraps TaskQueue + TaskRunner in-process. Demo/dev mode only (ADR-096)."""

    def __init__(self, *, executor: Any, admitter: Any = None) -> None:
        from maistro.tasks.queue import TaskQueue
        from maistro.tasks.runner import TaskRunner

        # `admitter` is the core Container's seam onto the canonical Run spine
        # (#41). None means this process has no Container — the stub path — and
        # the queue then admits without a Run rather than inventing one.
        self._queue = TaskQueue(admitter=admitter)
        self._runner = TaskRunner(self._queue, executor=executor)

    async def start(self) -> None:
        await self._runner.start()

    async def submit(
        self, create: TaskCreate, *, user_id: str, workspace_id: str | None = None
    ) -> TaskRecord:
        task = await self._queue.submit(create, user_id=user_id, workspace_id=workspace_id)
        return TaskRecord(task)

    def get(self, task_id: str, *, user_id: str | None = None) -> TaskRecord | None:
        task = self._queue.get(task_id, user_id=user_id)
        return TaskRecord(task) if task is not None else None

    def list_tasks(self, *, user_id: str | None = None) -> list[TaskRecord]:
        items, _ = self._queue.list_tasks(limit=200, user_id=user_id)
        return [TaskRecord(t) for t in reversed(items)]

    async def cancel(self, task_id: str) -> bool:
        return await self._queue.cancel(task_id)

    def remove(self, task_id: str) -> bool:
        return self._queue.remove(task_id)

    def remove_where(self, *, status: TaskStatus | None = None) -> int:
        return self._queue.remove_where(status=status)

    async def iter_events(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        while True:
            task = self._queue.get(task_id)
            if task is None:
                return
            rec = TaskRecord(task)
            yield {
                "id": rec.id,
                "status": rec.mission_status,
                "progress": rec.progress,
                "current_step": rec.current_step,
            }
            if rec.mission_status in _TERMINAL:
                return
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._queue.wait_for_update(task_id), timeout=30.0)

    async def stop(self) -> None:
        with contextlib.suppress(Exception):
            await self._runner.stop()


class MaistroServerTaskBackend:
    """httpx client against maistro-server's /tasks API. Production default."""

    _POLL_INTERVAL_S = 2.0

    def __init__(self, *, base_url: str, api_key: str | None) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key or ""

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        return headers

    async def submit(
        self, create: TaskCreate, *, user_id: str, workspace_id: str | None = None
    ) -> TaskRecord:
        if workspace_id is not None:
            raise WorkspaceNotRoutable(
                f"this deployment submits tasks to a single-Workspace maistro-server at "
                f"{self._base}, which cannot admit into Workspace {workspace_id!r}"
            )
        async with shared_client(timeout=30.0) as client:
            r = await client.post(
                f"{self._base}/tasks",
                headers=self._headers(),
                json=create.model_dump(mode="json"),
            )
            r.raise_for_status()
            body = r.json()
            task = TaskResponse.model_validate(body["task"])
            return TaskRecord(task)

    def get(self, task_id: str, *, user_id: str | None = None) -> TaskRecord | None:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(f"{self._base}/tasks/{task_id}", headers=self._headers())
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return TaskRecord(TaskResponse.model_validate(r.json()))

    def list_tasks(self, *, user_id: str | None = None) -> list[TaskRecord]:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(f"{self._base}/tasks", headers=self._headers(), params={"limit": 200})
            r.raise_for_status()
            body = r.json()
            items = [TaskResponse.model_validate(t) for t in body["items"]]
            return [TaskRecord(t) for t in items]

    async def cancel(self, task_id: str) -> bool:
        async with shared_client(timeout=30.0) as client:
            r = await client.delete(f"{self._base}/tasks/{task_id}", headers=self._headers())
            if r.status_code == 404:
                return False
            if r.status_code == 400:
                return False
            r.raise_for_status()
            return bool(r.json().get("cancelled", False))

    async def iter_events(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        async with shared_client(timeout=30.0) as client:
            while True:
                r = await client.get(f"{self._base}/tasks/{task_id}", headers=self._headers())
                if r.status_code == 404:
                    return
                r.raise_for_status()
                rec = TaskRecord(TaskResponse.model_validate(r.json()))
                yield {
                    "id": rec.id,
                    "status": rec.mission_status,
                    "progress": rec.progress,
                    "current_step": rec.current_step,
                }
                if rec.mission_status in _TERMINAL:
                    return
                await asyncio.sleep(self._POLL_INTERVAL_S)

    async def stop(self) -> None:
        return None
