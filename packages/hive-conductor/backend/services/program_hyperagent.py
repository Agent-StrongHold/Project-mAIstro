"""Shared program hyperagent helpers — used by program and missions routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request

from maistro.agents.hyperagent import (
    interview_status,
    propose_actions,
    propose_autonomous_actions,
    propose_work_item_suggestions,
)
from maistro.agents.pm_capabilities import is_autonomous
from maistro.agents.program_context import apply_guidance
from services import program_store as prog
from services.agent_invocation import pulse_roster, resolve_agent_task
from services.engine import get_engine

logger = logging.getLogger("hive.services.program_hyperagent")


def _use_secret(store: object, user_id: str, provider_id: str) -> str | None:
    """Single allowlisted callsite for use_secret — lambda is centralised here."""
    try:
        return store.use_secret(user_id, provider_id, lambda s: s)  # type: ignore[union-attr]
    except Exception:
        return None


def _get_atlassian_pats(user_id: str) -> dict[str, str | None]:
    """Pull Jira + Confluence PATs from the encrypted credential store."""
    from services import user_credentials as cred_svc

    store = cred_svc.get_credential_store()
    if store is None:
        return {}
    pats: dict[str, str | None] = {}
    for provider_id, key in [("jira", "jira"), ("confluence", "confluence")]:
        pats[key] = _use_secret(store, user_id, provider_id)
    return pats


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


async def apply_guidance_and_pulse(
    user_id: str,
    text: str,
    *,
    workspace_id: str | None = None,
    max_pulse_actions: int = 2,
) -> dict[str, Any]:
    """Record guidance and optionally queue autonomous fleet work."""
    project_id = _scope(workspace_id)
    ctx = apply_guidance(prog.get_context(user_id, project_id), text)
    ctx = prog.save_context(ctx)

    queued: list[dict[str, str]] = []
    pulse_error: str | None = None
    if ctx.interview_complete and max_pulse_actions > 0:
        try:
            pulse_result = await run_program_pulse(
                user_id, workspace_id=workspace_id, max_actions=max_pulse_actions
            )
            queued = pulse_result.get("queued", [])
        except Exception:
            pulse_error = "Fleet pulse skipped (engine unavailable)"

    out: dict[str, Any] = {
        "context": ctx.model_dump(mode="json"),
        "interview": interview_status(ctx),
        "proposed_actions": [
            a.as_dict()
            for a in propose_actions(ctx, roster=pulse_roster(workspace_id), max_actions=5)
        ],
        "queued_tasks": queued,
    }
    if pulse_error:
        out["pulse_note"] = pulse_error
    if not ctx.interview_complete:
        out["message"] = (
            "Guidance saved. Complete the Program interview to enable autonomous fleet actions."
        )
    elif queued:
        out["message"] = f"Guidance saved — {len(queued)} autonomous task(s) queued."
    else:
        out["message"] = "Guidance saved — fleet will use this on the next pulse."
    return out


def _empty_pulse_note(
    *,
    queued: list[dict[str, str]],
    failed: list[str],
    unavailable: list[str],
    actions: list[Any],
) -> str:
    """Why a pulse queued nothing, or empty when it queued something."""
    if queued or failed:
        return ""
    if unavailable:
        return (
            "This workspace's roster changed while the pulse was running: "
            f"{', '.join(sorted(set(unavailable)))} could no longer take the "
            "proposed work. No autonomous work was queued."
        )
    if not actions:
        return (
            "No agent in this workspace declares a capability the pulse can run "
            "without approval. No autonomous work was queued."
        )
    return ""


async def run_program_pulse(
    user_id: str, *, workspace_id: str | None = None, max_actions: int = 4
) -> dict[str, Any]:
    """Autonomous-only fleet tick, against `workspace_id`'s own roster."""
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
    engine = get_engine()
    queued: list[dict[str, str]] = []
    unavailable: list[str] = []
    failed: list[str] = []

    if engine._backend is None:
        return {
            "queued": [],
            "proposed": [a.as_dict() for a in actions],
            "work_item_suggestions": [s.as_dict() for s in suggestions],
            "context": ctx.model_dump(mode="json"),
            "note": "Task engine not running",
        }

    for action in actions:
        if not is_autonomous(action.capability):
            continue
        try:
            task_type, description, agent_id = resolve_agent_task(
                action.agent_id,
                action.capability,
                {
                    **action.payload,
                    "hyperagent_reason": action.reason,
                    "program": prog.context_dict(user_id, project_id),
                },
                workspace_id=workspace_id,
            )
            from maistro.agents.program_context import context_for_task

            pctx = context_for_task(ctx)
            pctx["atlassian_pats"] = _get_atlassian_pats(user_id)

            rec = await engine.submit_task(
                agent_id,
                description,
                user_id=user_id,
                workspace_id=workspace_id,
                task_type=task_type,
                agent_id=agent_id,
                capability=action.capability,
                program_context=pctx,
            )
            queued.append(
                {
                    "task_id": rec.id,
                    "agent_id": agent_id,
                    "capability": action.capability,
                    "reason": action.reason,
                }
            )
        except ValueError as exc:
            logger.warning(
                "pulse action %s/%s not available in workspace %s: %s",
                action.agent_id,
                action.capability,
                workspace_id or "-",
                exc,
            )
            unavailable.append(action.agent_id)
        except Exception as exc:
            logger.warning(
                "pulse action %s/%s failed to queue: %s",
                action.agent_id,
                action.capability,
                exc,
            )
            failed.append(action.agent_id)

    now = datetime.now(UTC).isoformat()
    prog.save_context(ctx.model_copy(update={"last_pulse_at": now, "updated_at": now}))

    result: dict[str, Any] = {
        "queued": queued,
        "proposed": [a.as_dict() for a in actions],
        "work_item_suggestions": [s.as_dict() for s in suggestions],
        "context": ctx.model_dump(mode="json"),
    }
    note = _empty_pulse_note(queued=queued, failed=failed, unavailable=unavailable, actions=actions)
    if note:
        result["note"] = note
    if failed:
        result["failed"] = sorted(set(failed))
    return result
