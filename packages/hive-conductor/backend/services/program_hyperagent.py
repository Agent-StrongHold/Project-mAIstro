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


#: The program store's project id for a caller in no workspace.
#:
#: Not reachable from a request any more (#129 refuses those), but
#: `program_store` still defaults to it and pre-existing rows carry it.
GLOBAL_PROJECT_ID = "default"


def _scope(workspace_id: str | None) -> str:
    """Which program context a workspace-scoped call reads and writes.

    A workspace's guidance, interview progress and proposed actions belong to
    that workspace. Reading `default` while the caller named `ws-a` writes
    their guidance somewhere they will never see it again, and reports a
    completed `ws-a` interview as incomplete.
    """
    return workspace_id or GLOBAL_PROJECT_ID


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
    """Why a pulse queued nothing, or empty when it queued something.

    Said once, plainly, rather than inferred from an empty `queued` beside a
    full `proposed` — and saying which of two different things happened (#221).

    Before the pulse read this workspace's own roster, "nothing here can do
    what was proposed" was the ordinary case and had one message. Now it is a
    race — the roster changed between proposing and queueing — and the ordinary
    empty pulse is the second message: this workspace has agents, and none of
    them declares a capability that may run without approval.
    """
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

    # The workspace's own roster decides who is proposed (#221). Before this
    # the pulse named PM Fleet's agents to every workspace, so any other
    # persona got a list of actions that could not run here.
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
            # Inject user's Atlassian PATs from encrypted credential store
            # so pm_runner can make real Jira/Confluence calls.
            pctx["atlassian_pats"] = _get_atlassian_pats(user_id)

            rec = await engine.submit_task(
                agent_id,
                description,
                user_id=user_id,
                # The Run is filed in the workspace the pulse was requested for.
                # `submit_task` reads an omitted workspace as the deployment's
                # default, so autonomous work asked for in `ws-a` was admitted
                # into another Project while carrying a `ws-a` agent.
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
            # An action was proposed for an agent this workspace turns out not
            # to have, or for a capability it does not declare. Since #221 the
            # proposals come from this workspace's own roster, so the ordinary
            # cause of this is gone — what remains is a roster that changed
            # between proposing and queueing, which is a real race and worth
            # reporting rather than assuming away.
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
