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
from maistro.agents.pm_capabilities import is_autonomous
from maistro.agents.program_context import apply_guidance
from services import program_store as prog
from services.agent_invocation import resolve_agent_task
from services.engine import get_engine


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


def require_program_access(user_id: str, workspace_id: str | None = None) -> None:
    """Gate the program hyperagent surface on workspace membership (#129).

    The interview itself was generalized to any persona long ago, through
    `program_context.py`'s per-use_case `INTERVIEW_TEMPLATES`; the gate in front
    of it was the last thing here that still asked an environment variable.
    `user_id` is required rather than optional now: the optional form existed
    only so a caller that had not been re-pointed yet could fall through to
    `is_pm_poc_mode()`, and there is no such caller left.

    Renamed from `require_pm_poc` because the name was the claim -- nothing
    about this surface is PM-specific, and any persona's workspace reaches it.
    """
    from services.workspace_mode import is_workspace_request_authorized

    if not is_workspace_request_authorized(user_id, workspace_id):
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
    """Record guidance and optionally queue autonomous fleet work.

    `workspace_id` names the roster the queued work resolves against (#129).
    The pulse proposes bare agent names (`delivery`), and those only mean
    something within a workspace whose persona materialized them.
    """
    ctx = apply_guidance(prog.get_context(user_id), text)
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
        "proposed_actions": [a.as_dict() for a in propose_actions(ctx, max_actions=5)],
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


async def run_program_pulse(
    user_id: str, *, workspace_id: str | None = None, max_actions: int = 4
) -> dict[str, Any]:
    """Autonomous-only fleet tick, against `workspace_id`'s own roster."""
    from datetime import UTC, datetime

    ctx = prog.get_context(user_id)
    if not ctx.interview_complete:
        return {
            "queued": [],
            "skipped": "interview_incomplete",
            "interview": interview_status(ctx),
        }

    actions = propose_autonomous_actions(ctx, max_actions=max_actions)
    suggestions = propose_work_item_suggestions(ctx, user_id)
    engine = get_engine()
    queued: list[dict[str, str]] = []

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
                    "program": prog.context_dict(user_id),
                },
                workspace_id=workspace_id,
            )
            from maistro.agents.program_context import context_for_task

            pctx = context_for_task(ctx)
            # Inject user's Atlassian PATs from encrypted credential store
            # so pm_runner can make real Jira/Confluence calls.
            pctx["atlassian_pats"] = _get_atlassian_pats(user_id)

            rec = await engine.submit_task(
                agent_id,
                description,
                user_id=user_id,
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
        except Exception as _exc:
            __import__("logging").getLogger("hive.services.program_hyperagent").warning(
                "error_swallowed file=%s line=%d: %s",
                "packages/hive-conductor/backend/services/program_hyperagent.py",
                137,
                _exc,
            )
            continue

    now = datetime.now(UTC).isoformat()
    prog.save_context(ctx.model_copy(update={"last_pulse_at": now, "updated_at": now}))

    return {
        "queued": queued,
        "proposed": [a.as_dict() for a in actions],
        "work_item_suggestions": [s.as_dict() for s in suggestions],
        "context": ctx.model_dump(mode="json"),
    }
