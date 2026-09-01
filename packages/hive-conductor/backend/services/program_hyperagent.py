"""Shared program hyperagent helpers — used by program and missions routes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from maistro.agents.hyperagent import (
    interview_status,
    propose_actions,
    propose_autonomous_actions,
    propose_work_item_suggestions,
)
from maistro.agents.program_context import apply_guidance
from services import program_store as prog
from services.agent_invocation import pulse_roster


def user_id_from_request(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(uid)


GLOBAL_PROJECT_ID = "default"


def _scope(workspace_id: str | None) -> str:
    """Which program context a workspace-scoped call reads and writes."""
    return workspace_id or GLOBAL_PROJECT_ID


async def require_program_access(user_id: str, workspace_id: str | None = None) -> None:
    """Gate the program hyperagent surface on canonical Workspace membership."""
    from services.workspace_mode import is_workspace_request_authorized

    if not await is_workspace_request_authorized(user_id, workspace_id):
        raise HTTPException(
            status_code=404,
            detail=(
                "The program hyperagent runs within a workspace. "
                "Name a workspace you are a member of."
            ),
        )


_RETIRED_PM_EXECUTION_NOTE = (
    "Autonomous PM capability execution was retired with PM-Fleet POC mode; "
    "Workspace Persona proposals remain visible until canonical Graph execution owns these capabilities."
)


async def apply_guidance_and_pulse(
    user_id: str,
    text: str,
    *,
    workspace_id: str | None = None,
    max_pulse_actions: int = 2,
) -> dict[str, Any]:
    """Record guidance and generate workspace-scoped Program Pulse proposals."""
    project_id = _scope(workspace_id)
    ctx = apply_guidance(prog.get_context(user_id, project_id), text)
    ctx = prog.save_context(ctx)

    queued: list[dict[str, str]] = []
    pulse_note: str | None = None
    if ctx.interview_complete and max_pulse_actions > 0:
        try:
            pulse_result = await run_program_pulse(
                user_id, workspace_id=workspace_id, max_actions=max_pulse_actions
            )
            queued = pulse_result.get("queued", [])
            note = pulse_result.get("note")
            pulse_note = str(note) if note else None
        except Exception:
            pulse_note = "Program pulse proposal generation failed."

    out: dict[str, Any] = {
        "context": ctx.model_dump(mode="json"),
        "interview": interview_status(ctx),
        "proposed_actions": [
            a.as_dict()
            for a in propose_actions(ctx, roster=pulse_roster(workspace_id), max_actions=5)
        ],
        "queued_tasks": queued,
    }
    if pulse_note:
        out["pulse_note"] = pulse_note
    if not ctx.interview_complete:
        out["message"] = "Guidance saved. Complete the Program interview to generate proposals."
    elif queued:
        out["message"] = f"Guidance saved — {len(queued)} autonomous task(s) queued."
    elif pulse_note:
        out["message"] = (
            "Guidance saved — Program Pulse produced proposals without executing retired PM "
            "capability work."
        )
    else:
        out["message"] = "Guidance saved — no autonomous actions were proposed."
    return out




async def run_program_pulse(
    user_id: str, *, workspace_id: str | None = None, max_actions: int = 4
) -> dict[str, Any]:
    """Generate Program Pulse proposals without reviving PM-Fleet execution authority."""
    from datetime import UTC, datetime

    project_id = _scope(workspace_id)
    ctx = prog.get_context(user_id, project_id)
    if not ctx.interview_complete:
        return {
            "queued": [],
            "skipped": "interview_incomplete",
            "interview": interview_status(ctx),
        }

    roster = pulse_roster(workspace_id)
    actions = propose_autonomous_actions(ctx, roster=roster, max_actions=max_actions)
    suggestions = propose_work_item_suggestions(ctx, user_id)


    now = datetime.now(UTC).isoformat()
    prog.save_context(ctx.model_copy(update={"last_pulse_at": now, "updated_at": now}))

    note = (
        _RETIRED_PM_EXECUTION_NOTE
        if actions
        else (
            "No agent in this workspace declares a capability the pulse can run "
            "without approval. No autonomous work was queued."
        )
    )
    return {
        "queued": [],
        "proposed": [a.as_dict() for a in actions],
        "work_item_suggestions": [s.as_dict() for s in suggestions],
        "context": ctx.model_dump(mode="json"),
        "note": note,
    }
