"""Canonical execution seam for Hive's contained conversational chat.

The model callback remains conversation-only in Hive until M2 tool security is
complete. Admission and physical execution do not: they use the embedded
maistro-core Container so a chat turn has the same Workspace/Project ->
Graph -> Run -> NodeRun -> Attempt evidence as every other ordinary turn.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast
from uuid import uuid4

from config import get_settings
from models.schemas import ChatCompletionRequest

from services.agent_materialization import workspace_agents
from services.engine import get_engine

ChatDispatch = Callable[[], Awaitable[dict[str, Any]]]


def request_workspace_id(req: ChatCompletionRequest) -> str | None:
    """Return an explicitly selected Workspace, without inventing one."""
    value = getattr(req, "workspace_id", None)
    return value.strip() if isinstance(value, str) and value.strip() else None


def selected_workspace_id(req: ChatCompletionRequest) -> str:
    """Resolve the product default for an unscoped chat request."""
    return request_workspace_id(req) or get_settings().hive_default_workspace_id


def _requested_agent_id(req: ChatCompletionRequest) -> str | None:
    value = getattr(req, "agent_id", None)
    return value.strip() if isinstance(value, str) and value.strip() else None


def resolve_workspace_agent_id(req: ChatCompletionRequest, workspace_id: str) -> str:
    """Resolve one stable Workspace Agent identity for the turn.

    Materialized rows win, using an explicit request selection when present and
    otherwise the deterministic overseer/program-manager preference. The final
    scoped id is stable even during bootstrap before a persona roster exists;
    it is a Workspace identity, not a per-turn Agent record.
    """
    agents = sorted(workspace_agents(workspace_id), key=lambda agent: agent.id)
    requested = _requested_agent_id(req)
    if requested:
        for agent in agents:
            if requested in (agent.id, agent.name, agent.name.rsplit(".", 1)[-1]):
                return agent.id
    preferred_suffixes = (".overseer", ".program_manager")
    for suffix in preferred_suffixes:
        preferred = next((agent for agent in agents if agent.id.endswith(suffix)), None)
        if preferred is not None:
            return preferred.id
    if agents:
        return agents[0].id
    return f"{workspace_id}.overseer"


def _canonical_container() -> Any | None:
    """Read the one embedded Container; never build a second execution spine."""
    try:
        engine = get_engine()
    except RuntimeError:
        return None
    port = getattr(engine, "agent_port", None)
    return getattr(port, "container", None)


def _principal_id(request: Any) -> str | None:
    user = getattr(request.state, "user", None) or {}
    value = user.get("id") or user.get("username")
    return str(value) if value else None


def _session_id(req: ChatCompletionRequest) -> str | None:
    value = getattr(req, "session_id", None)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _request_id(request: Any) -> str:
    return (request.headers.get("X-Request-ID") or str(uuid4())).strip()


async def execute_conversation_turn(
    req: ChatCompletionRequest,
    request: Any,
    messages: list[dict[str, Any]],
    dispatch: ChatDispatch,
) -> dict[str, Any]:
    """Run one conversation-only callback through canonical execution."""
    container = _canonical_container()
    route = getattr(container, "route_conversation_request", None)
    if route is None:
        # Stub/demo mode has no canonical runtime and retains the old product
        # response rather than manufacturing a second local RunStore.
        return await dispatch()
    workspace_id = selected_workspace_id(req)
    return cast(
        dict[str, Any],
        await route(
            messages,
            dispatch,
            workspace_id=workspace_id,
            workspace_agent_id=resolve_workspace_agent_id(req, workspace_id),
            session_id=_session_id(req),
            request_id=_request_id(request),
            actor_principal_id=_principal_id(request),
        ),
    )


__all__ = [
    "execute_conversation_turn",
    "request_workspace_id",
    "resolve_workspace_agent_id",
    "selected_workspace_id",
]
