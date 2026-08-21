"""Task API endpoints — CRUD for engineering tasks."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from maistro.tasks.models import TaskCreate, TaskResponse, TaskResult
from maistro.tasks.queue import TaskQueue, get_task_queue
from maistro.tools.sandbox.workspace import validate_workspace_path
from maistro_server.api.auth import RequireAuth
from maistro_server.api.principal import AuthenticatedPrincipal
from maistro_server.api.schemas import PaginatedTasks, TaskCancelledResponse, TaskCreatedResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _validate_task_workspace(workspace: str) -> None:
    try:
        validate_workspace_path(workspace)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Workspace path is not allowed",
        ) from exc


def _owner_id(auth: AuthenticatedPrincipal | None) -> str:
    if auth is None:
        return "dev"
    return auth.user_id


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_task(
    request: TaskCreate,
    response: Response,
    auth: RequireAuth,
    queue: Annotated[TaskQueue, Depends(get_task_queue)],
) -> TaskCreatedResponse:
    _validate_task_workspace(request.workspace)
    uid = _owner_id(auth)
    task = await queue.submit(request, user_id=uid)
    response.headers["Location"] = f"/tasks/{task.task_id}"
    return TaskCreatedResponse(
        task_id=task.task_id,
        status=task.status.value,
        task=task,
    )


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    auth: RequireAuth,
    queue: Annotated[TaskQueue, Depends(get_task_queue)],
) -> TaskResponse:
    task = queue.get(task_id, user_id=_owner_id(auth))
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/result")
async def get_task_result(
    task_id: str,
    auth: RequireAuth,
    queue: Annotated[TaskQueue, Depends(get_task_queue)],
) -> TaskResult:
    """Return only the result portion of a task. 404 if no result yet."""
    task = queue.get(task_id, user_id=_owner_id(auth))
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.result is None:
        raise HTTPException(status_code=404, detail="Task has no result yet")
    return task.result


@router.delete("/{task_id}")
async def cancel_task(
    task_id: str,
    auth: RequireAuth,
    queue: Annotated[TaskQueue, Depends(get_task_queue)],
) -> TaskCancelledResponse:
    task = queue.get(task_id, user_id=_owner_id(auth))
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    cancelled = await queue.cancel(task_id)
    if not cancelled:
        raise HTTPException(status_code=400, detail="Cannot cancel task in current state")
    return TaskCancelledResponse(cancelled=True)


@router.get("")
async def list_tasks(
    auth: RequireAuth,
    queue: Annotated[TaskQueue, Depends(get_task_queue)],
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
) -> PaginatedTasks:
    items, next_cursor = queue.list_tasks(limit=limit, cursor=cursor, user_id=_owner_id(auth))
    return PaginatedTasks(
        items=items,
        next_cursor=next_cursor,
        count=len(items),
    )
