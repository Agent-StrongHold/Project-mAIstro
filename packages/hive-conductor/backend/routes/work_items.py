"""Gated Jira work items — suggest, clarify, edit, confirm.

Persona/Workspace system: routes accept an optional `workspace_id` query
param, resolved to that workspace's own `ProgramContext` project_id for
`suggest`/`confirm` -- omitted (every pre-Phase-H caller) keeps the exact
old global-default behavior. A `WorkItemDraft` remembers the `project_id`
it was suggested under (`maistro.agents.work_items.WorkItemDraft.
project_id`), so `confirm` reads back the same context it was suggested
from rather than always the global default.

The PM-gate is capability-based, not identity-based: a workspace unlocks
Jira/work-item drafting because its own materialized agent roster
(`services/agent_materialization.py`) actually includes the agents
`maistro.agents.pm_capabilities.agent_for_work_item()` dispatches to, not
because its persona is literally named "pm_fleet"
(`services/workspace_mode.py::workspace_has_pm_fleet_agents`). Any persona
whose spawns declare those agent names qualifies the same way.
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


def _require_submittable_workspace(user_id: str, workspace_id: str | None) -> None:
    """Refuse a submission that names a workspace the caller is not in (#158).

    Separate from `_require_pm` on purpose. That gate answers "may this caller
    use work items at all", and falls back to the legacy global flag for a
    workspace it cannot resolve -- which is right for reading, and wrong for
    naming the Workspace a Run gets filed in. Here an unresolvable or
    non-member workspace is a refusal, in the same 403 shape `routes/agents.py`
    uses for its own workspace-scoped writes.
    """
    if workspace_id and not is_workspace_member(user_id, workspace_id):
        raise HTTPException(status_code=403, detail="only a workspace member can submit work to it")


def _require_pm(user_id: str, workspace_id: str | None) -> None:
    """Refuse a caller with no workspace whose persona drafts work items (#129).

    The legacy global flag used to answer for an absent, unresolvable or
    non-member `workspace_id`, which meant a deployment running with
    `HIVE_POC_MODE=pm` handed the Jira draft flow to every caller and drafted
    against no workspace's roster at all. A persona that declares the agents
    is now the only way in, and the two refusals are told apart on purpose: a
    workspace whose persona has no such agents is a different problem from a
    caller who named no workspace.
    """
    if not workspace_id or not is_workspace_member(user_id, workspace_id):
        raise HTTPException(
            status_code=404,
            detail="Work items are drafted within a workspace; name one you are a member of",
        )
    if not workspace_has_pm_fleet_agents(workspace_id):
        raise HTTPException(
            status_code=404,
            detail="This workspace's persona has no Jira/work-item-capable agents",
        )


#: `project_id` a draft carries when it was suggested under no workspace.
GLOBAL_PROJECT_ID = "default"


def _resolve_project_id(user_id: str, workspace_id: str | None) -> str:
    """Same resolution as routes/program.py's _resolve_program_scope, minus
    the use_case half (work items don't run the interview script)."""
    if workspace_id and is_workspace_member(user_id, workspace_id):
        return workspace_id
    return GLOBAL_PROJECT_ID


def _draft_workspace(draft: WorkItemDraft) -> str | None:
    """The Workspace a draft was suggested under, or None for the global one.

    A draft persists the scope it was suggested under (`project_id`), and that
    is what its confirmation must submit into: the program context below is
    already read back from it, so filing the Run anywhere else would put the
    work in one Project and its context in another. `GLOBAL_PROJECT_ID` is the
    sentinel for "no workspace", not a workspace id.
    """
    scope = (draft.project_id or "").strip()
    return None if not scope or scope == GLOBAL_PROJECT_ID else scope


def _require_pm_for_draft(user_id: str, draft: WorkItemDraft) -> None:
    """Gate a draft-scoped route on the workspace the draft was suggested under.

    Not on the query string. The frontend sends no `workspace_id` to these
    routes -- `confirm_work_item` already reads the draft's own scope for the
    same reason -- and with the global flag gone (#129) a gate that asked the
    query string would refuse every request the UI actually makes. Reading the
    draft is also the stricter answer: a caller cannot widen their access by
    naming a different workspace than the one the draft belongs to.
    """
    _require_pm(user_id, _draft_workspace(draft))


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
def list_work_items(request: Request, workspace_id: str | None = None) -> dict[str, Any]:
    uid = _user_id(request)
    _require_pm(uid, workspace_id)
    drafts = _list_drafts(uid)
    return {"drafts": [d.as_dict() for d in drafts]}


@router.post("/suggest")
def suggest_work_item_route(
    body: SuggestBody, request: Request, workspace_id: str | None = None
) -> dict[str, Any]:
    uid = _user_id(request)
    _require_pm(uid, workspace_id)
    ctx = prog.get_context(uid, _resolve_project_id(uid, workspace_id))
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
def get_work_item(
    draft_id: str, request: Request, workspace_id: str | None = None
) -> dict[str, Any]:
    uid = _user_id(request)
    draft = _load_draft(draft_id, uid)
    _require_pm_for_draft(uid, draft)
    return {"draft": draft.as_dict()}


class ClarifyBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answers: dict[str, str] = Field(default_factory=dict)


@router.post("/{draft_id}/clarify")
def clarify_work_item(
    draft_id: str, body: ClarifyBody, request: Request, workspace_id: str | None = None
) -> dict[str, Any]:
    uid = _user_id(request)
    existing = _load_draft(draft_id, uid)
    _require_pm_for_draft(uid, existing)
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
def patch_work_item(
    draft_id: str, body: PatchFieldsBody, request: Request, workspace_id: str | None = None
) -> dict[str, Any]:
    uid = _user_id(request)
    draft = _load_draft(draft_id, uid)
    _require_pm_for_draft(uid, draft)
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
    # Authorization before capability gating: `_require_pm` answers 404 for a
    # workspace it cannot resolve, which would swallow the 403 a non-member is
    # owed and make the refusal depend on whether the legacy PM flag is on.
    _require_submittable_workspace(uid, workspace_id)
    draft = _load_draft(draft_id, uid)
    _require_pm_for_draft(uid, draft)
    # The draft's own scope decides where the Run is filed, not the query
    # string: the frontend confirms without one, so reading the request here
    # would file a workspace-scoped draft in the default Project while its
    # program context came from the workspace.
    scope = _draft_workspace(draft)
    if workspace_id and workspace_id != scope:
        raise HTTPException(
            status_code=409,
            detail="this draft was suggested under a different workspace",
        )
    _require_submittable_workspace(uid, scope)
    try:
        posted, result = confirm_post_stub(draft)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _save_draft(posted)

    # Read back the same ProgramContext this draft was suggested under
    # (draft.project_id), not always the global default -- so a draft
    # suggested from a specific workspace's context stays consistent
    # through to the queued task's `program` payload.
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
        # The workspace the draft was suggested under, so the agent name the
        # draft carries (`delivery`) resolves against that workspace's own
        # materialized roster (`ws-7.delivery`) rather than a global agent
        # that merely shares the name.
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
        # 501, not 500: the request is well-formed and authorized, and this
        # deployment simply cannot honour it. The Jira post above already
        # happened, so the draft stays posted and only the task is refused --
        # said plainly rather than rolled back, because the stub has no undo.
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
def cancel_work_item(draft_id: str, request: Request, workspace_id: str | None = None) -> None:
    uid = _user_id(request)
    draft = _load_draft(draft_id, uid)
    _require_pm_for_draft(uid, draft)
    _save_draft(draft.model_copy(update={"status": "cancelled"}))
