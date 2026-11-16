"""Workspace BacklogItem history API (#101).

The read side of the audit story: any Workspace member can replay an item's
full history — who changed what, which Goal/Run/reconciliation it references,
what evidence justified closure — and an outsider gets the same 404 an
unknown item gets, so the route never discloses what exists elsewhere. There
are no write routes here by design: history is appended by the recording
helpers in `maistro.workspaces.backlog_history.recording`, never patched or
deleted over HTTP.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from maistro.workspaces import WorkspaceStore
from maistro.workspaces.backlog_history import (
    BacklogHistoryEvent,
    BacklogHistoryEventKind,
    BacklogHistoryStore,
)
from maistro_server.api.auth import RequireAuth
from maistro_server.api.workspace_access import (
    get_workspace_store,
    require_workspace_membership,
    user_id,
)

router = APIRouter(prefix="/{workspace_id}/backlog", tags=["backlog-history"])


def get_backlog_history_store(request: Request) -> BacklogHistoryStore:
    """The BacklogItem history store the process Container selected."""
    try:
        store: BacklogHistoryStore | None = request.app.state.container.backlog_history_store
    except AttributeError:
        store = None
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No BacklogItem history store is configured",
        )
    return store


WorkspaceStoreDep = Annotated[WorkspaceStore, Depends(get_workspace_store)]
BacklogHistoryStoreDep = Annotated[BacklogHistoryStore, Depends(get_backlog_history_store)]


@router.get("/{item_id}/history", response_model=list[BacklogHistoryEvent])
async def list_item_history(
    workspace_id: str,
    item_id: str,
    auth: RequireAuth,
    workspace_store: WorkspaceStoreDep,
    store: BacklogHistoryStoreDep,
    kind: Annotated[BacklogHistoryEventKind | None, Query()] = None,
) -> list[BacklogHistoryEvent]:
    """The item's history, oldest first, for members only."""
    await require_workspace_membership(workspace_store, workspace_id, user_id(auth))
    return await store.history_for_item(workspace_id, item_id, kind=kind)


__all__ = ["get_backlog_history_store", "list_item_history", "router"]
