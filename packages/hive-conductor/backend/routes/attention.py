"""GET /v1/workspaces/{workspace_id}/attention — the Workspace Attention read (#1049).

A read-only door onto `services.attention`. Answering an item stays on the
HITL answer route its `answer_href` names, so nothing reachable from here can
settle or terminalize the canonical object an item points at.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from middleware.auth import principal_has_permission
from services.attention import list_attention

from routes.hitl import _request_user_id

router = APIRouter(tags=["attention"])

#: The scope `/v1/hitl/pending` takes: items carry the question a paused node
#: is asking, which is in-flight execution content of the same sensitivity.
_READ_SCOPE = "dags.write"


@router.get("/{workspace_id}/attention")
async def get_workspace_attention(workspace_id: str, request: Request) -> dict[str, Any]:
    user_id = _request_user_id(request)
    if not principal_has_permission(request.state.user, _READ_SCOPE):
        raise HTTPException(
            status_code=403, detail=f"Permission '{_READ_SCOPE}' required. Elevate to proceed."
        )
    body = await list_attention(user_id, workspace_id, now=datetime.now(UTC))
    if body is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return body
