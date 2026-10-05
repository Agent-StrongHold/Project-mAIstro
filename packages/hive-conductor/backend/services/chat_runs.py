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
model is called (#1108): an ungoverned answer is not a fallback. A turn the
canonical active-Run ceiling refuses (#1182) is answered 429 instead --
backpressure, not an outage -- with the same detail and `Retry-After` the
maistro-server chat door uses for the same canonical limiter.
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
from maistro.runs.concurrency import RunConcurrencyExceeded
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
    admitter: ChatRunAdmitter


def _capacity(exc: RunConcurrencyExceeded) -> HTTPException:
    """The shared 429 for a full canonical admission ceiling (#1182).

    Same status, detail, and `Retry-After` as maistro-server's chat door for
    the same `RunStore` limiter: `exc.scope` says which ceiling is full, and
    the exception's type and fields stay intact on the chained cause.
    """
    return HTTPException(
        status_code=429,
        detail=f"too many active runs for this {exc.scope}; retry shortly",
        headers={"Retry-After": RETRY_AFTER_SECONDS},
    )


def _unavailable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=503, detail=detail, headers={"Retry-After": RETRY_AFTER_SECONDS}
    )


def _release_dispatch_shield(
    admitter: ChatRunAdmitter | None,
    run: Run | None,
    marked: bool,
) -> None:
    """Release the dispatch shield exactly when one was set.

    One cleanup invariant for every `admit_turn` failure path -- a full
    admission ceiling (#1182), a cancellation mid-admission, any other
    admission failure. `marked` implies both arguments are live: the marker
    is set only after a successful `mark_dispatch_pending(run.run_id)` on an
    admitted Run (#338).
    """
    if marked and admitter is not None and run is not None:
        admitter.release_dispatch_pending(run.run_id)


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


def _request_id(request: Request) -> str | None:
    """The HTTP request id, when middleware stamped one.

    Provenance carries it the same way the core seam does: a conversation is
    found by session id, a turn by request id. An empty stamp is no stamp.
    """
    value = getattr(getattr(request, "state", None), "request_id", None)
    return value if isinstance(value, str) and value else None


async def _settle_window(admitter: ChatRunAdmitter, run: Run) -> None:
    """Release this admitter's dispatch shield and re-apply its window.

    Hive keeps one `ChatRunAdmitter` per Workspace. `Container._close_chat_run`
    sweeps `container.chat_admitter`, which is a different window, so a Hive
    turn that ended with no later admission used to sit past `max_retained`.
    The shield is released only after the turn has settled: while it is set,
    a concurrent admission cannot delete a RUNNING turn that has no Attempt yet.
    """
    try:
        admitter.release_dispatch_pending(run.run_id)
    except Exception:
        logger.warning("chat dispatch shield release failed", exc_info=True)
    try:
        await asyncio.shield(admitter.sweep())
    except Exception:
        logger.warning("chat Run retention sweep failed", exc_info=True)


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
    admitter: ChatRunAdmitter | None = None
    marked = False
    try:
        ws = await _turn_workspace(user_id, workspace_id)
        agent = await resolve_workspace_agent(ws)
        admitter = await _admitter_for(container, ws)
        run = await admitter.admit(
            messages,
            session_id=_owned_session(request, session_id),
            request_id=_request_id(request),
            actor_principal_id=user_id,
        )
        await container.run_store.transition_run(run.run_id, RunStatus.QUEUED)
        # Marked while still QUEUED, before RUNNING, so a concurrent sweep
        # cannot see an Attempt-less RUNNING turn and delete it.
        admitter.mark_dispatch_pending(run.run_id)
        marked = True
        run = await container.run_store.transition_run(run.run_id, RunStatus.RUNNING)
    except asyncio.CancelledError:
        _release_dispatch_shield(admitter, run, marked)
        await asyncio.shield(container._cancel_incomplete_admission(run))
        raise
    except RunConcurrencyExceeded as exc:
        # Backpressure, not an admission outage (#1182): 429, not the 503 an
        # ordinary admission failure gets. The same cleanup as the other
        # refusals -- the ceiling usually refuses the create itself, before
        # any marker exists, but the invariant is not capacity-specific.
        logger.info("chat turn refused: active Run ceiling full", exc_info=True)
        _release_dispatch_shield(admitter, run, marked)
        await container._cancel_incomplete_admission(run)
        raise _capacity(exc) from exc
    except Exception:
        logger.warning("chat turn could not be admitted as a Run", exc_info=True)
        _release_dispatch_shield(admitter, run, marked)
        await container._cancel_incomplete_admission(run)
        raise _unavailable("chat turn could not be admitted; retry shortly") from None
    return AdmittedTurn(run=run, agent_id=agent.id, container=container, admitter=admitter)


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
        except asyncio.CancelledError:
            await container._close_chat_run(run, cancelled=True)
            raise
        except Exception as exc:
            if not dispatched:
                # The spine refused before the model was reached (#1108): nothing
                # failed, and the turn is not answered ungoverned.
                logger.warning("chat turn could not be recorded as an Attempt", exc_info=True)
                await container._close_chat_run(run, cancelled=True)
                raise _unavailable("chat turn could not be executed; retry shortly") from None
            await container._close_chat_run(run, error=failure_category(exc))
            raise
        else:
            await container._close_chat_run(run, result=chat_turn_outcome(result))
        result["run_id"] = run.run_id
        return result
    finally:
        await _settle_window(turn.admitter, run)


async def cancel_unstarted(turn: AdmittedTurn) -> None:
    """Close the Run of an admitted turn whose execution never began.

    A stream admitted before its response exists, whose body the server never
    iterated (a client gone before the first byte), would otherwise sit
    RUNNING until the stranded-admission sweep.
    """
    await asyncio.shield(turn.container._close_chat_run(turn.run, cancelled=True))
    await _settle_window(turn.admitter, turn.run)


def reset_for_tests() -> None:
    global _bound_run_store
    _admitters.clear()
    _bound_run_store = None
