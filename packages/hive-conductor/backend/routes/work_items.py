"""Gated Jira work items — suggest, clarify, edit, confirm.

Workspace membership is canonical (#37). Hive's materialized roster still
answers the product-specific question of whether a Workspace has agents that
support the Jira/work-item capabilities.
"""

from __future__ import annotations

import logging
from typing import Any

from adapters.task_backend import WORKSPACE_NOT_ROUTABLE_DETAIL, WorkspaceNotRoutable
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from services import program_store as prog
from services.agent_invocation import resolve_agent_task
from services.engine import get_engine
from services.workspace_mode import is_workspace_member, workspace_has_pm_fleet_agents

from maistro.agents.pm_capabilities import WORK_ITEM_LABELS, WorkItemType
from maistro.agents.work_items import (
    WorkItemDraft,
    apply_clarifying_answers,
    confirm_post_stub,
    suggest_work_item,
    update_draft_fields,
)
from routes.audit import log_audit

router = APIRouter(tags=["work-items"])
logger = logging.getLogger("hive.work_items")


def _user_id(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(uid)


async def _require_submittable_workspace(user_id: str, workspace_id: str | None) -> None:
    """Refuse a submission that names a Workspace the caller is not in."""
    if workspace_id and not await is_workspace_member(user_id, workspace_id):
        raise HTTPException(status_code=403, detail="only a workspace member can submit work to it")


async def _require_pm(user_id: str, workspace_id: str | None) -> None:
    """Require canonical membership plus a roster capable of work-item drafting."""
    if not workspace_id or not await is_workspace_member(user_id, workspace_id):
        raise HTTPException(
            status_code=404,
            detail="Work items are drafted within a workspace; name one you are a member of",
        )
    if not workspace_has_pm_fleet_agents(workspace_id):
        raise HTTPException(
            status_code=404,
            detail="This workspace's persona has no Jira/work-item-capable agents",
        )


GLOBAL_PROJECT_ID = "default"


async def _resolve_project_id(user_id: str, workspace_id: str | None) -> str:
    if workspace_id and await is_workspace_member(user_id, workspace_id):
        return workspace_id
    return GLOBAL_PROJECT_ID


def _draft_workspace(draft: WorkItemDraft) -> str | None:
    scope = (draft.project_id or "").strip()
    return None if not scope or scope == GLOBAL_PROJECT_ID else scope


async def _require_pm_for_draft(user_id: str, draft: WorkItemDraft) -> None:
    """Authorize against the Workspace persisted on the draft itself."""
    await _require_pm(user_id, _draft_workspace(draft))


def _load_draft(draft_id: str, user_id: str) -> WorkItemDraft:
    import stores

    raw = stores.work_item_drafts.get(draft_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft = WorkItemDraft.model_validate(raw)
    if draft.user_id != user_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


def _save_draft(draft: WorkItemDraft) -> WorkItemDraft:
    import stores

    stores.work_item_drafts[draft.id] = draft.model_dump(mode="json")
    return draft


def _list_drafts(user_id: str) -> list[WorkItemDraft]:
    import stores

    out: list[WorkItemDraft] = []
    for raw in stores.work_item_drafts.values():
        try:
            d = WorkItemDraft.model_validate(raw)
        except Exception as _exc:
            __import__("logging").getLogger("hive.routes.work_items").warning(
                "error_swallowed file=%s line=%d: %s",
                "packages/hive-conductor/backend/routes/work_items.py",
                67,
                _exc,
            )
            continue
        if d.user_id == user_id and d.status != "cancelled":
            out.append(d)
    return sorted(out, key=lambda d: d.updated_at, reverse=True)


class SuggestBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    work_type: WorkItemType
    reason: str = ""
    hint: str = ""
    parent_key: str = ""


@router.get("")
async def list_work_items(request: Request, workspace_id: str | None = None) -> dict[str, Any]:
    uid = _user_id(request)
    await _require_pm(uid, workspace_id)
    drafts = _list_drafts(uid)
    return {"drafts": [d.as_dict() for d in drafts]}


@router.post("/suggest")
async def suggest_work_item_route(
    body: SuggestBody, request: Request, workspace_id: str | None = None
) -> dict[str, Any]:
    uid = _user_id(request)
    await _require_pm(uid, workspace_id)
    ctx = prog.get_context(uid, await _resolve_project_id(uid, workspace_id))
    draft = suggest_work_item(
        uid,
        body.work_type,
        ctx,
        reason=body.reason or f"User requested {WORK_ITEM_LABELS[body.work_type]}",
        hint=body.hint,
        parent_key=body.parent_key,
    )
    _save_draft(draft)
    log_audit("work_item_suggest", uid, target=draft.id, detail={"work_type": body.work_type})
    return {
        "draft": draft.as_dict(),
        "message": "Review clarifying questions, edit fields, then confirm to post to Jira.",
    }


@router.get("/{draft_id}")
async def get_work_item(
    draft_id: str, request: Request, workspace_id: str | None = None
) -> dict[str, Any]:
    uid = _user_id(request)
    draft = _load_draft(draft_id, uid)
    await _require_pm_for_draft(uid, draft)
    return {"draft": draft.as_dict()}


class ClarifyBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answers: dict[str, str] = Field(default_factory=dict)


@router.post("/{draft_id}/clarify")
async def clarify_work_item(
    draft_id: str, body: ClarifyBody, request: Request, workspace_id: str | None = None
) -> dict[str, Any]:
    uid = _user_id(request)
    existing = _load_draft(draft_id, uid)
    await _require_pm_for_draft(uid, existing)
    draft = apply_clarifying_answers(existing, body.answers)
    draft = _save_draft(draft)
    return {"draft": draft.as_dict()}


class PatchFieldsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str | None = None
    description: str | None = None
    project_key: str | None = None
    parent_key: str | None = None
    priority: str | None = None
    labels: list[str] | None = None
    assignee: str | None = None
    due_date: str | None = None


@router.patch("/{draft_id}")
async def patch_work_item(
    draft_id: str, body: PatchFieldsBody, request: Request, workspace_id: str | None = None
) -> dict[str, Any]:
    uid = _user_id(request)
    draft = _load_draft(draft_id, uid)
    await _require_pm_for_draft(uid, draft)
    if draft.status == "posted":
        raise HTTPException(status_code=400, detail="Already posted to Jira")
    updates = body.model_dump(exclude_none=True)
    draft = update_draft_fields(draft, updates)
    if draft.status == "clarifying" and draft.fields.summary and draft.fields.description:
        required_ok = all(
            not q.required or q.answer
            for q in draft.clarifying_questions
            if q.id not in ("summary", "description")
        )
        if required_ok:
            draft = draft.model_copy(update={"status": "ready"})
    draft = _save_draft(draft)
    return {"draft": draft.as_dict()}


@router.post("/{draft_id}/confirm")
async def confirm_work_item(
    draft_id: str, request: Request, workspace_id: str | None = None
) -> dict[str, Any]:
    """User-approved post to Jira (stub) — only after clarify + edit."""
    uid = _user_id(request)
    await _require_submittable_workspace(uid, workspace_id)
    draft = _load_draft(draft_id, uid)
    await _require_pm_for_draft(uid, draft)
    scope = _draft_workspace(draft)
    if workspace_id and workspace_id != scope:
        raise HTTPException(
            status_code=409,
            detail="this draft was suggested under a different workspace",
        )
    await _require_submittable_workspace(uid, scope)
    try:
        resolve_agent_task(
            draft.agent_id,
            draft.capability,
            {},
            workspace_id=draft.project_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"this workspace's persona has no agent {draft.agent_id!r} able to "
                f"{draft.capability!r}; the draft was not posted"
            ),
        ) from exc
    try:
        posted, result = confirm_post_stub(draft)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _save_draft(posted)

    engine = get_engine()
    task_type, description, agent_id = resolve_agent_task(
        posted.agent_id,
        posted.capability,
        {
            "title": posted.fields.summary,
            "summary": posted.fields.description,
            "program": prog.context_dict(uid, posted.project_id),
            "jira_issue_key": result.get("issue_key"),
            "confirmed": True,
        },
        workspace_id=posted.project_id,
    )
    prog_ctx = prog.context_dict(uid, posted.project_id)
    prog_ctx["confirmed"] = True
    prog_ctx["jira_issue_key"] = result.get("issue_key")
    try:
        rec = await engine.submit_task(
            posted.agent_id,
            description,
            user_id=uid,
            workspace_id=scope,
            task_type=task_type,
            agent_id=agent_id,
            capability=posted.capability,
            program_context=prog_ctx,
        )
    except WorkspaceNotRoutable as exc:
        logger.warning("workspace_not_routable %s", exc)
        raise HTTPException(status_code=501, detail=WORKSPACE_NOT_ROUTABLE_DETAIL) from exc
    log_audit(
        "work_item_confirm",
        uid,
        target=posted.id,
        detail={"issue_key": result.get("issue_key"), "task_id": rec.id},
    )
    return {
        "draft": posted.as_dict(),
        "jira": result,
        "task_id": rec.id,
        "message": f"Posted {result.get('issue_key')} to Jira (stub).",
    }


@router.delete("/{draft_id}", status_code=204)
async def cancel_work_item(
    draft_id: str, request: Request, workspace_id: str | None = None
) -> None:
    uid = _user_id(request)
    draft = _load_draft(draft_id, uid)
    await _require_pm_for_draft(uid, draft)
    _save_draft(draft.model_copy(update={"status": "cancelled"}))
