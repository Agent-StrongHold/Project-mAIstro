"""Workspace Attention routes (#1049).

GET projects HITL pauses + failed Runs. POST ``…/dismiss`` records a
defer/dismiss preference (not a second Attention store). Answering still
stays on the HITL answer door named by ``answer_href``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from services.attention import clear_dismissal, list_attention, record_dismissal
from services.request_principal import require_principal
from services.workspace_authority import is_member

from routes.hitl import _request_user_id

router = APIRouter(tags=["attention"])

#: The scope `/v1/hitl/pending` takes: items carry the question a paused node
#: is asking, which is in-flight execution content of the same sensitivity.
_READ_SCOPE = "dags.write"


class AttentionDismissBody(BaseModel):
    sourceKind: str = Field(min_length=1)
    sourceId: str = Field(min_length=1)
    action: Literal["dismiss", "defer"] = "dismiss"


@router.get("/{workspace_id}/attention")
async def get_workspace_attention(workspace_id: str, request: Request) -> dict[str, Any]:
    user_id = _request_user_id(request)
    if not require_principal(request).has_permission(_READ_SCOPE):
        raise HTTPException(
            status_code=403, detail=f"Permission '{_READ_SCOPE}' required. Elevate to proceed."
        )
    body = await list_attention(user_id, workspace_id, now=datetime.now(UTC))
    if body is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return body


@router.post("/{workspace_id}/attention/dismiss")
async def dismiss_workspace_attention(
    workspace_id: str, body: AttentionDismissBody, request: Request
) -> dict[str, Any]:
    """Defer/dismiss one Attention source id for this Workspace (#1049)."""
    user_id = _request_user_id(request)
    if not require_principal(request).has_permission(_READ_SCOPE):
        raise HTTPException(
            status_code=403, detail=f"Permission '{_READ_SCOPE}' required. Elevate to proceed."
        )
    if not await is_member(user_id, workspace_id):
        raise HTTPException(status_code=404, detail="workspace not found")
    try:
        record = record_dismissal(
            workspace_id,
            body.sourceKind,
            body.sourceId,
            actor=user_id,
            action=body.action,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "action": record["action"],
        "count": record["count"],
        "key": f"{body.sourceKind}:{body.sourceId}",
    }


@router.delete("/{workspace_id}/attention/dismiss")
async def undismiss_workspace_attention(
    workspace_id: str, request: Request, sourceKind: str, sourceId: str
) -> dict[str, Any]:
    """Clear a defer/dismiss preference so the item can surface again."""
    user_id = _request_user_id(request)
    if not require_principal(request).has_permission(_READ_SCOPE):
        raise HTTPException(
            status_code=403, detail=f"Permission '{_READ_SCOPE}' required. Elevate to proceed."
        )
    if not await is_member(user_id, workspace_id):
        raise HTTPException(status_code=404, detail="workspace not found")
    removed = clear_dismissal(workspace_id, sourceKind, sourceId)
    return {"ok": True, "cleared": removed}
