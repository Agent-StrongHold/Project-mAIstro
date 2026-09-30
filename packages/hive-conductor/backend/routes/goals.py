"""GET /v1/goals — Workspace Goal inspection (#65).

A read-only door onto `services.goal_inspection`: the Goal-centric product
layer over the same canonical evidence the #1036 run-inspection seam serves.
Runs are never re-listed, re-identified, or re-controlled here — every run row
carries the id and the status `/v1/dag-runs` answers with, and every control
stays on the seam that owns it. The routes mutate nothing, so the Goal view
can never become a second terminal authority for anything (#65's boundary with
#1036).

The refusals are the #1174 shape: a Goal whose evidence lies outside the
caller's canonical Workspace universe is indistinguishable from a Goal that
does not exist.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from services.goal_inspection import goal_view, list_goal_views

router = APIRouter(tags=["goals"])


def _user_id(request: Request) -> str:
    """Principal for this request — set by AuthMiddleware on every /v1/ path.

    Same refusal contract as routes/dag_runs.py: a handler that cannot name
    its principal fails closed rather than guessing, because every response
    below is scoped to that principal's Workspace universe (#1174).
    """
    user = getattr(request.state, "user", None) or {}
    uid = str(user.get("id") or user.get("username") or "")
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication required")
    return uid


@router.get("")
async def list_goals(request: Request, limit: int = 25) -> list[dict[str, Any]]:
    uid = _user_id(request)
    return await list_goal_views(uid, limit=max(1, min(limit, 100)))


@router.get("/{goal_id}")
async def get_goal(goal_id: str, request: Request) -> dict[str, Any]:
    uid = _user_id(request)
    view = await goal_view(uid, goal_id)
    if view is None:
        # Same answer for "no such goal" and "not in your Workspace universe":
        # a scoped refusal must not confirm that an out-of-scope goal exists.
        raise HTTPException(status_code=404, detail="goal not found")
    return view
