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


def _auth_context(request: Any) -> Any:
    """Carry the authenticated Hive principal into Conduit in the same kind."""
    from maistro.security._types import AuthContext

    user = getattr(request.state, "user", None) or {}
    roles = user.get("roles", ())
    if isinstance(roles, str):
        roles = (roles,)
    elif not isinstance(roles, (list, tuple, set, frozenset)):
        roles = ()
    return AuthContext(
        user_id=str(user.get("id") or user.get("username") or ""),
        username=str(user.get("username") or ""),
        roles=frozenset(str(role) for role in roles),
    )


def _session_id(req: ChatCompletionRequest) -> str | None:
    value = getattr(req, "session_id", None)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _request_id(request: Any) -> str:
    return (request.headers.get("X-Request-ID") or str(uuid4())).strip()


async def resolve_workspace_runtime_agent_id(
    req: ChatCompletionRequest, workspace_id: str, container: Any
) -> str | None:
    """Resolve the persistent Workspace Agent to a real runtime identity.

    ``stores.agents`` is the durable product projection while ``container.agents``
    is the execution roster. Materialized Workspace definitions are promoted
    through the one #840 factory seam when the bridge is present; no synthetic
    per-turn runtime Agent is created when that seam is unavailable.
    """
    stable_id = resolve_workspace_agent_id(req, workspace_id)
    runtime_agents = getattr(container, "agents", {}) or {}
    if stable_id in runtime_agents:
        return stable_id

    for definition in workspace_agents(workspace_id):
        if definition.id != stable_id:
            continue
        name = definition.name
        if name in runtime_agents:
            return name
        from services.agent_materialization import materialize_runtime

        stored = await materialize_runtime(definition)
        if stored.config.get("dispatchable") and name in runtime_agents:
            return name
        return None
    return None


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
        # A stub port is an unavailable runtime, not a second chat executor.
        # Returning the callback result here produced a success-shaped answer
        # with no canonical Run/NodeRun/Attempt evidence.
        raise RuntimeError("canonical maistro-core chat runtime is unavailable")
    workspace_id = selected_workspace_id(req)
    workspace_agent_id = resolve_workspace_agent_id(req, workspace_id)
    runtime_agent_id = await resolve_workspace_runtime_agent_id(req, workspace_id, container)
    return cast(
        dict[str, Any],
        await route(
            messages,
            dispatch,
            workspace_id=workspace_id,
            workspace_agent_id=workspace_agent_id,
            runtime_agent_id=runtime_agent_id,
            auth=_auth_context(request),
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
