"""GET /v1/workspaces/{workspace_id}/goals — Workspace Goal inspection (#65).

A read-only door onto `services.goal_inspection`: the Goal-centric product
layer over the same canonical evidence the #1036 run-inspection seam serves.
Runs are never re-listed, re-identified, or re-controlled here — every run row
carries the id and the status `/v1/dag-runs` answers with, and every control
stays on the seam that owns it. The routes mutate nothing, so the Goal view
can never become a second terminal authority for anything (#65's boundary with
#1036).

The routes live under the already-declared `/v1/workspaces` prefix — the same
mount Home (#1048) and Attention (#1049) use — rather than minting a new
`/v1/goals` prefix the route-permission registry would have to re-review.
Membership is the Workspace's own, fail closed: a caller who is not a member
gets the same 404 a missing Workspace gets, and underneath it the #1174
universe scoping still applies — a Goal whose evidence lies outside the
caller's canonical Workspace universe is indistinguishable from a Goal that
does not exist.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from services.goal_inspection import GoalInspectionView, goal_view, list_goal_views
from services.request_principal import require_actor_id
from services.workspace_authority import visible_view

router = APIRouter(tags=["goals"])


async def _require_member(request: Request, workspace_id: str) -> str:
    """The principal for this request, after a membership check that cannot
    be skipped.

    Same refusal contract as routes/home.py: not a member and not a Workspace
    are both 404, so the route is not an existence oracle for other people's
    Workspaces (#1174). A handler that cannot name its principal fails closed
    rather than guessing, because every response below is scoped to that
    principal's Workspace universe.
    """
    user_id = require_actor_id(request)
    if await visible_view(user_id, workspace_id) is None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return user_id


@router.get("/{workspace_id}/goals", response_model=list[GoalInspectionView])
async def list_goals(workspace_id: str, request: Request, limit: int = 25) -> list[dict[str, Any]]:
    uid = await _require_member(request, workspace_id)
    return await list_goal_views(uid, limit=max(1, min(limit, 100)), workspace_id=workspace_id)


@router.get("/{workspace_id}/goals/{goal_id}", response_model=GoalInspectionView)
async def get_goal(workspace_id: str, goal_id: str, request: Request) -> dict[str, Any]:
    uid = await _require_member(request, workspace_id)
    view = await goal_view(uid, goal_id, workspace_id=workspace_id)
    if view is None:
        # Same answer for "no such goal" and "not in this Workspace's
        # history": a scoped refusal must not confirm that an out-of-scope
        # goal exists.
        raise HTTPException(status_code=404, detail="goal not found")
    return view
