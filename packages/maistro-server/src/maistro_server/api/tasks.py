"""Task API endpoints — CRUD for engineering tasks."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from maistro.tasks.http_contract import (
    TASK_OWNER_ID_HEADER,
    TASK_OWNER_SIGNATURE_HEADER,
    WORKSPACE_ID_HEADER,
    WORKSPACE_SCOPE_SIGNATURE_HEADER,
    verify_task_owner_signature,
    verify_workspace_scope_signature,
)
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


def _asserted_owner_id(
    auth: AuthenticatedPrincipal | None,
    owner_id: str | None,
    owner_signature: str | None,
) -> str:
    """Resolve a trusted Hive browser owner across the service boundary.

    The bearer credential authenticates Hive itself, not the browser user. An
    owner header is therefore accepted only with the service-only HMAC proof;
    accepting the unsigned value would let any holder of the router key read
    or create tasks for an arbitrary principal.
    """
    if owner_id is None and owner_signature is None:
        return _owner_id(auth)
    key = os.getenv("WORKSPACE_SCOPE_KEY", "")
    if (
        not owner_id
        or not owner_signature
        or not key
        or not verify_task_owner_signature(owner_id, owner_signature, key)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Task owner assertion is not authorized",
        )
    return owner_id


def _authorize_workspace_scope(workspace_id: str, signature: str | None) -> None:
    """Accept named scope only when the trusted Hive boundary proves it.

    Ordinary API authentication identifies who may call maistro-server; it does
    not prove Hive has checked that caller's Workspace membership. The separate
    HMAC capability keeps that membership decision authoritative in Hive while
    preventing any holder of a normal API token from turning this header into a
    tenant selector.
    """
    key = os.getenv("WORKSPACE_SCOPE_KEY", "")
    if (
        not key
        or signature is None
        or not verify_workspace_scope_signature(workspace_id, signature, key)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace scope assertion is not authorized",
        )


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_task(
    request: TaskCreate,
    response: Response,
    auth: RequireAuth,
    queue: Annotated[TaskQueue, Depends(get_task_queue)],
    workspace_id: Annotated[str | None, Header(alias=WORKSPACE_ID_HEADER)] = None,
    workspace_signature: Annotated[
        str | None, Header(alias=WORKSPACE_SCOPE_SIGNATURE_HEADER)
    ] = None,
    task_owner: Annotated[str | None, Header(alias=TASK_OWNER_ID_HEADER)] = None,
    task_owner_signature: Annotated[str | None, Header(alias=TASK_OWNER_SIGNATURE_HEADER)] = None,
) -> TaskCreatedResponse:
    _validate_task_workspace(request.workspace)
    if workspace_id is not None:
        if not workspace_id.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Workspace id must be a non-empty string",
            )
        _authorize_workspace_scope(workspace_id, workspace_signature)
    uid = _asserted_owner_id(auth, task_owner, task_owner_signature)
    task = await queue.submit(request, user_id=uid, workspace_id=workspace_id)
    response.headers["Location"] = f"/tasks/{task.task_id}"
    return TaskCreatedResponse(
        task_id=task.task_id,
        status=task.status.value,
        run_id=task.run_id,
        task=task,
    )


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    auth: RequireAuth,
    queue: Annotated[TaskQueue, Depends(get_task_queue)],
    task_owner: Annotated[str | None, Header(alias=TASK_OWNER_ID_HEADER)] = None,
    task_owner_signature: Annotated[str | None, Header(alias=TASK_OWNER_SIGNATURE_HEADER)] = None,
) -> TaskResponse:
    task = queue.get(
        task_id,
        user_id=_asserted_owner_id(auth, task_owner, task_owner_signature),
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/result")
async def get_task_result(
    task_id: str,
    auth: RequireAuth,
    queue: Annotated[TaskQueue, Depends(get_task_queue)],
    task_owner: Annotated[str | None, Header(alias=TASK_OWNER_ID_HEADER)] = None,
    task_owner_signature: Annotated[str | None, Header(alias=TASK_OWNER_SIGNATURE_HEADER)] = None,
) -> TaskResult:
    """Return only the result portion of a task. 404 if no result yet."""
    task = queue.get(
        task_id,
        user_id=_asserted_owner_id(auth, task_owner, task_owner_signature),
    )
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
    task_owner: Annotated[str | None, Header(alias=TASK_OWNER_ID_HEADER)] = None,
    task_owner_signature: Annotated[str | None, Header(alias=TASK_OWNER_SIGNATURE_HEADER)] = None,
) -> TaskCancelledResponse:
    task = queue.get(
        task_id,
        user_id=_asserted_owner_id(auth, task_owner, task_owner_signature),
    )
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
    task_owner: Annotated[str | None, Header(alias=TASK_OWNER_ID_HEADER)] = None,
    task_owner_signature: Annotated[str | None, Header(alias=TASK_OWNER_SIGNATURE_HEADER)] = None,
) -> PaginatedTasks:
    items, next_cursor = queue.list_tasks(
        limit=limit,
        cursor=cursor,
        user_id=_asserted_owner_id(auth, task_owner, task_owner_signature),
    )
    return PaginatedTasks(
        items=items,
        next_cursor=next_cursor,
        count=len(items),
    )
