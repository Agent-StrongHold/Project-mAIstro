"""Hive's conversation-only chat and voice turns as canonical chat Runs (#1037).

Each model-reaching turn is admitted as a Run over the one-node chat Graph in
the turn's Workspace -- the one the request named, when the caller is a member,
else the caller's default Workspace (ADR-092326-7ed7) -- and the model is
called from inside that Run's Attempt, stamped with the Workspace Agent.

The seam is core's: `wire_chat_admission` admits, `ChatAttemptExecutor`
executes, and the Container that owns the spine terminalizes, exactly as
`Container.route_request` does for its own turns. Only the dispatch differs:
the route's conversation-only model call, never the tool-capable Conduit.

A turn that cannot be admitted is refused with a retryable 503 before the
model is called (#1108): an ungoverned answer is not a fallback.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from maistro.runs.chat_admission import ChatRunAdmitter, chat_turn_outcome, failure_category
from maistro.runs.chat_execution import (
    ATTEMPT_AGENT_KEY,
    ChatAttemptExecutor,
    ChatDispatchUnrecorded,
)
from maistro.runs.model import Run, RunStatus
from maistro.runs.wiring import wire_chat_admission
from services import workspace_authority
from services.default_workspace import resolve_default_workspace
from services.owned_records import chat_sessions_for
from services.program_hyperagent import user_id_from_request
from services.workspace_agent import resolve_workspace_agent

logger = logging.getLogger(__name__)

RETRY_AFTER_SECONDS = "5"

ModelCall = Callable[[], Awaitable[dict[str, Any]]]

# One admitter per Workspace, so each keeps its own Workspace's retention
# window and sweep scope (#1175). Rebuilt when the engine's Run store changes.
_admitters: dict[str, ChatRunAdmitter] = {}
_bound_run_store: object | None = None


@dataclass(frozen=True)
class AdmittedTurn:
    """A turn admitted and RUNNING, with the Agent it runs under."""

    run: Run
    agent_id: str
    container: Any


def _unavailable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=503, detail=detail, headers={"Retry-After": RETRY_AFTER_SECONDS}
    )


def _container() -> Any:
    from services.engine import get_engine

    try:
        engine = get_engine()
    except RuntimeError:
        return None
    container = getattr(engine.agent_port, "container", None)
    if getattr(container, "run_store", None) is None:
        return None
    if getattr(container, "project_scope_store", None) is None:
        return None
    return container


async def _admitter_for(container: Any, workspace_id: str) -> ChatRunAdmitter:
    global _bound_run_store
    if _bound_run_store is not container.run_store:
        _admitters.clear()
        _bound_run_store = container.run_store
    admitter = _admitters.get(workspace_id)
    if admitter is None:
        await container.project_scope_store.create_root(workspace_id)
        admitter = _admitters.setdefault(
            workspace_id,
            wire_chat_admission(
                container.run_store,
                container.project_scope_store,
                workspace_id=workspace_id,
                intents=getattr(container, "intent_registry", None),
            ),
        )
    return admitter


async def _turn_workspace(user_id: str, workspace_id: Any) -> str:
    """The named Workspace when the caller is a member, else their default.

    A Workspace the caller cannot see is treated as no Workspace -- the same
    rule the brief interview applies to the same field -- so the turn is still
    answered, in a Workspace the caller owns, and never files into one they
    are not in.
    """
    # `visible_view`, not bare membership: the Workspace Agent needs the view,
    # and a Workspace this caller can be a member of but not see would
    # otherwise refuse every turn rather than fall back.
    if (
        isinstance(workspace_id, str)
        and await workspace_authority.visible_view(user_id, workspace_id) is not None
    ):
        return workspace_id
    return (await resolve_default_workspace(user_id)).id


def _owned_session(request: Request, session_id: Any) -> str | None:
    """The session id to record as provenance, when it is the caller's own.

    Provenance is what a conversation's Runs are later found by, so a caller
    must not be able to file a turn under someone else's session.
    """
    if not isinstance(session_id, str) or not session_id:
        return None
    try:
        chat_sessions_for(request).require(session_id)
    except HTTPException:
        return None
    return session_id


async def admit_turn(
    request: Request,
    messages: list[dict[str, Any]],
    *,
    workspace_id: Any = None,
    session_id: Any = None,
) -> AdmittedTurn:
    """Admit one turn as a RUNNING chat Run, or refuse it before the model."""
    user_id = user_id_from_request(request)
    container = _container()
    if container is None:
        raise _unavailable(
            "chat needs the maistro-core runtime and its Run spine, which this "
            "process has not started"
        )
    run: Run | None = None
    try:
        ws = await _turn_workspace(user_id, workspace_id)
        agent = await resolve_workspace_agent(ws)
        admitter = await _admitter_for(container, ws)
        run = await admitter.admit(
            messages,
            session_id=_owned_session(request, session_id),
            actor_principal_id=user_id,
        )
        await container.run_store.transition_run(run.run_id, RunStatus.QUEUED)
        run = await container.run_store.transition_run(run.run_id, RunStatus.RUNNING)
    except asyncio.CancelledError:
        await asyncio.shield(container._cancel_incomplete_admission(run))
        raise
    except Exception:
        logger.warning("chat turn could not be admitted as a Run", exc_info=True)
        await container._cancel_incomplete_admission(run)
        raise _unavailable("chat turn could not be admitted; retry shortly") from None
    return AdmittedTurn(run=run, agent_id=agent.id, container=container)


async def execute_turn(
    turn: AdmittedTurn, messages: list[dict[str, Any]], call_model: ModelCall
) -> dict[str, Any]:
    """Call the model inside the turn's Attempt and terminalize its Run.

    Returns the answer with the Workspace Agent under `agent` and the Run under
    `run_id`. A model failure fails the Run and re-raises. An answer the spine
    could not record is returned once, with the Run left open for the
    canonical recovery authorities -- `Container.route_request`'s rule.
    """
    container = turn.container
    run = turn.run

    dispatched = False

    async def _dispatch() -> dict[str, Any]:
        nonlocal dispatched
        dispatched = True
        response = dict(await call_model())
        response[ATTEMPT_AGENT_KEY] = turn.agent_id
        return response

    try:
        result = await ChatAttemptExecutor(container.run_store).execute(
            run.run_id, messages, _dispatch
        )
    except ChatDispatchUnrecorded as exc:
        logger.warning(
            "chat turn %s was answered but could not be recorded as an Attempt; "
            "its Run is left open for recovery",
            exc.run_id,
            exc_info=True,
        )
        result = exc.response
    except Exception as exc:
        if not dispatched:
            # The spine refused before the model was reached (#1108): nothing
            # failed, and the turn is not answered ungoverned.
            logger.warning("chat turn could not be recorded as an Attempt", exc_info=True)
            await container._close_chat_run(run, cancelled=True)
            raise _unavailable("chat turn could not be executed; retry shortly") from None
        await container._close_chat_run(run, error=failure_category(exc))
        raise
    except asyncio.CancelledError:
        await container._close_chat_run(run, cancelled=True)
        raise
    else:
        await container._close_chat_run(run, result=chat_turn_outcome(result))
    result["run_id"] = run.run_id
    return result


async def cancel_unstarted(turn: AdmittedTurn) -> None:
    """Close the Run of an admitted turn whose execution never began.

    A stream admitted before its response exists, whose body the server never
    iterated (a client gone before the first byte), would otherwise sit
    RUNNING until the stranded-admission sweep.
    """
    await asyncio.shield(turn.container._close_chat_run(turn.run, cancelled=True))


def reset_for_tests() -> None:
    global _bound_run_store
    _admitters.clear()
    _bound_run_store = None
