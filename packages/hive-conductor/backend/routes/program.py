"""Program hyperagent API — interview, guidance, proactive fleet pulse.

Workspace identity and membership are resolved through the canonical authority;
Hive still uses the Workspace's presentation record to choose its persona
interview script (#37).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from services import program_store as prog
from services.persona_authoring import all_persona_templates
from services.program_hyperagent import (
    apply_guidance_and_pulse,
    require_program_access,
    run_program_pulse,
    user_id_from_request,
)
from services.workspace_authority import visible_view

from maistro.agents.hyperagent import interview_status
from maistro.agents.program_context import apply_interview_answer
from routes.audit import log_audit

router = APIRouter(tags=["program"])
logger = logging.getLogger("hive.program")


async def _resolve_program_scope(
    user_id: str,
    workspace_id: str | None,
) -> tuple[str, str, tuple[dict[str, str], ...] | None]:
    """Map an authorized Workspace to program context and persona interview."""
    if workspace_id:
        workspace = await visible_view(user_id, workspace_id)
        if workspace is not None:
            template = all_persona_templates().get(workspace.persona_template_id)
            custom_steps = (
                tuple(
                    {"field": q.field, "agent": q.agent, "question": q.question}
                    for q in template.interview
                )
                if template is not None and template.interview
                else None
            )
            return workspace_id, workspace.persona_template_id, custom_steps
    return "default", "pm_fleet", None


@router.get("/context")
@router.get("/cpntext")
async def get_program_context(request: Request, workspace_id: str | None = None) -> dict[str, Any]:
    uid = user_id_from_request(request)
    await require_program_access(uid, workspace_id)
    project_id, use_case, custom_steps = await _resolve_program_scope(uid, workspace_id)
    ctx = prog.get_context(uid, project_id)
    return {
        "context": ctx.model_dump(mode="json"),
        "interview": interview_status(ctx, use_case=use_case, custom_steps=custom_steps),
    }


class InterviewAnswerBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answer: str = Field(min_length=1, max_length=4000)


@router.post("/interview/answer")
async def post_interview_answer(
    body: InterviewAnswerBody,
    request: Request,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    uid = user_id_from_request(request)
    await require_program_access(uid, workspace_id)
    project_id, use_case, custom_steps = await _resolve_program_scope(uid, workspace_id)
    ctx = prog.get_context(uid, project_id)
    ctx = apply_interview_answer(ctx, body.answer, use_case=use_case, custom_steps=custom_steps)
    ctx = prog.save_context(ctx)
    log_audit(
        "program_interview",
        uid,
        detail={"step": ctx.interview_step, "workspace_id": workspace_id},
    )

    queued: list[dict[str, str]] = []
    if ctx.interview_complete:
        pulse_result = await run_program_pulse(uid, workspace_id=workspace_id, max_actions=2)
        queued = pulse_result.get("queued", [])

    return {
        "context": ctx.model_dump(mode="json"),
        "interview": interview_status(ctx, use_case=use_case, custom_steps=custom_steps),
        "queued_tasks": queued,
    }


class GuidanceBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=1, max_length=8000)
    task_id: str | None = None


@router.post("/guidance")
async def post_guidance(
    body: GuidanceBody,
    request: Request,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Human guidance for the meta hyperagent within an authorized Workspace."""
    uid = user_id_from_request(request)
    await require_program_access(uid, workspace_id)
    log_audit("program_guidance", uid, target=body.task_id, detail={"chars": len(body.text)})
    result = await apply_guidance_and_pulse(uid, body.text.strip(), workspace_id=workspace_id)
    return {"ok": True, "task_id": body.task_id, **result}


class PulseBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_actions: int = Field(default=3, ge=1, le=8)


@router.post("/pulse")
async def post_pulse(
    body: PulseBody,
    request: Request,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Proactive fleet tick — queue autonomous agent work only."""
    uid = user_id_from_request(request)
    await require_program_access(uid, workspace_id)
    return await run_program_pulse(uid, workspace_id=workspace_id, max_actions=body.max_actions)
