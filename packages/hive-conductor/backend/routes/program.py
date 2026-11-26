"""Program hyperagent API — interview, guidance, proactive fleet pulse.

Workspace identity and membership are resolved through the canonical authority;
Hive still uses the Workspace's presentation record to choose its persona
interview script (#37).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from services import brief_store
from services import program_store as prog
from services.persona_authoring import all_persona_templates
from services.program_hyperagent import (
    apply_guidance_and_pulse,
    require_program_access,
    run_program_pulse,
    user_id_from_request,
)
from services.workspace_authority import visible_view

from maistro.agents.brief_interview import (
    VIDEO_BRIEF_ALIASES,
    VIDEO_BRIEF_SCRIPT,
    BriefField,
    BriefIncompleteError,
    BriefInterview,
    BriefScript,
    apply_brief_answer,
    brief_summary,
    commit_brief,
    next_brief_question,
    start_brief_interview,
)
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


# ---------------------------------------------------------------------------
# Brief interview: the conversation a Goal or CreativeBrief is committed from
# (SPEC-091726-7c2a). One interview per person per workspace; nothing here
# writes a Goal. ``/brief/draft`` is the gate: it returns the draft the Goal
# and CreativeBrief writers (#458, #774) consume, and refuses while a
# required field is still open.
# ---------------------------------------------------------------------------

_BRIEF_SCRIPTS: dict[str, BriefScript] = {VIDEO_BRIEF_SCRIPT.id: VIDEO_BRIEF_SCRIPT}
_BRIEF_ALIASES: dict[str, dict[str, str]] = {VIDEO_BRIEF_SCRIPT.id: VIDEO_BRIEF_ALIASES}


def _brief_script(state: BriefInterview) -> BriefScript:
    return _BRIEF_SCRIPTS[state.script_id]


def _question_view(field: BriefField | None) -> dict[str, Any] | None:
    if field is None:
        return None
    return {
        "key": field.key,
        "label": field.label,
        "question": field.question,
        "options": [{"key": o.key, "value": o.value} for o in field.options],
        "can_assume": field.default is not None,
    }


def _brief_view(state: BriefInterview | None) -> dict[str, Any]:
    if state is None:
        return {"interview": None, "summary": None, "question": None}
    script = _brief_script(state)
    return {
        "interview": state.model_dump(mode="json"),
        "summary": brief_summary(script, state),
        "question": _question_view(next_brief_question(script, state)),
    }


@router.get("/brief")
async def get_brief_interview(request: Request, workspace_id: str | None = None) -> dict[str, Any]:
    """The brief so far for this person in this workspace, or nothing."""
    uid = user_id_from_request(request)
    await require_program_access(uid, workspace_id)
    project_id, _, _ = await _resolve_program_scope(uid, workspace_id)
    return _brief_view(brief_store.get_interview(uid, project_id))


class BriefStartBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    opening: str = Field(min_length=1, max_length=4000)
    script: str = Field(default=VIDEO_BRIEF_SCRIPT.id, max_length=64)


@router.post("/brief/start", status_code=201)
async def start_brief(
    body: BriefStartBody,
    request: Request,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Open the interview from the turn that asked for work. Replaces any
    interview this person had open here; that one was never committed."""
    uid = user_id_from_request(request)
    await require_program_access(uid, workspace_id)
    project_id, _, _ = await _resolve_program_scope(uid, workspace_id)
    script = _BRIEF_SCRIPTS.get(body.script)
    if script is None:
        raise HTTPException(status_code=404, detail=f"No brief script named {body.script!r}.")
    state = start_brief_interview(script, body.opening)
    brief_store.save_interview(uid, project_id, state)
    log_audit(
        "brief_interview_started",
        uid,
        detail={"script": script.id, "workspace_id": workspace_id},
    )
    return _brief_view(state)


class BriefAnswerBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answer: str = Field(min_length=1, max_length=4000)


@router.post("/brief/answer")
async def answer_brief(
    body: BriefAnswerBody,
    request: Request,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """One free-text turn. The reply says what the turn did (answered,
    routed, assumed, cannot_assume, changed, noted, dropped)."""
    uid = user_id_from_request(request)
    await require_program_access(uid, workspace_id)
    project_id, _, _ = await _resolve_program_scope(uid, workspace_id)
    state = brief_store.get_interview(uid, project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="No brief interview is open here.")
    script = _brief_script(state)
    reply = apply_brief_answer(script, state, body.answer, aliases=_BRIEF_ALIASES.get(script.id))
    brief_store.save_interview(uid, project_id, reply.state)
    return {"event": reply.event, "field": reply.field, **_brief_view(reply.state)}


@router.post("/brief/draft")
async def draft_brief(request: Request, workspace_id: str | None = None) -> dict[str, Any]:
    """The gate. Returns the draft a Goal revision and a CreativeBrief version
    are written from, or 409 naming the fields still missing."""
    uid = user_id_from_request(request)
    await require_program_access(uid, workspace_id)
    project_id, _, _ = await _resolve_program_scope(uid, workspace_id)
    state = brief_store.get_interview(uid, project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="No brief interview is open here.")
    try:
        draft = commit_brief(_brief_script(state), state)
    except BriefIncompleteError as exc:
        raise HTTPException(
            status_code=409,
            detail={"missing": list(exc.missing), "reason": str(exc)},
        ) from exc
    log_audit(
        "brief_interview_drafted",
        uid,
        detail={
            "script": draft["script"],
            "assumed": draft["assumed"],
            "workspace_id": workspace_id,
        },
    )
    return {"draft": draft, "written": [], **_brief_view(state)}


@router.delete("/brief")
async def drop_brief(request: Request, workspace_id: str | None = None) -> dict[str, Any]:
    """Forget the open interview. Nothing was committed, so nothing is undone."""
    uid = user_id_from_request(request)
    await require_program_access(uid, workspace_id)
    project_id, _, _ = await _resolve_program_scope(uid, workspace_id)
    return {"dropped": brief_store.clear_interview(uid, project_id)}
