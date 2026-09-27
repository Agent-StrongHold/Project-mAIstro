"""Inbound harness-session API (SPEC-208 §5).

Exposes the maistro-core ``HarnessSessionManager`` over HTTP so another
orchestrator (another maistro Master Orchestrator, or an external meta-harness)
can drive *this* instance as a foreign-harness subagent: start a session, send
turns, stream events, stop. Backed by the engine's capability registry + Warden;
degrades to 503 when no ``harness_runner`` provider is active (SAFE_NOOP), and
returns 400 when Warden refuses an inbound payload.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from services.engine import get_engine

from maistro.agents.spec.agent_spec import AgentRole, AgentSpec
from maistro.capabilities import HarnessSessionManager, Unavailable
from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import InMemoryBindingStore
from maistro.capabilities.effect_context import new_effect_context
from maistro.capabilities.slots.harness_runner import HarnessInputBlocked
from maistro.policy import BudgetRule, SequencePolicyEngine
from maistro.security.warden.detector import Warden

router = APIRouter(tags=["harness"])

_manager: HarnessSessionManager | None = None


def _configured_harness_policy() -> SequencePolicyEngine:
    """Build the explicit route policy; absent configuration is read-only.

    The route must never construct a manager without a policy. Until a
    deployment supplies a richer harness policy, this bounded policy denies
    outbound actions while still allowing session lifecycle and conversation.
    """
    return SequencePolicyEngine([BudgetRule(dimension="count", limit=0)])


async def _get_manager() -> HarnessSessionManager:
    """Lazily build a process-wide manager over the engine registry + Warden."""
    global _manager
    if _manager is None:
        engine = get_engine()
        container = getattr(engine.agent_port, "container", None)
        effects = getattr(container, "capability_effects", None)
        if effects is None:
            # Stub/degraded engine mode has no policy authority. Keep the route
            # explicitly available only through a configured effect context;
            # the context default denies rather than granting the provider call.
            effects = new_effect_context()
        binding = Binding(
            binding_id="builtin:harness-route",
            workspace_id="default",
            project_id="default",
            capability="harness_runner",
        )
        # This is composition-time registration, not an effect-time grant. Once
        # revoked, the manager only resolves the existing identity and never
        # recreates it.
        if isinstance(effects.bindings, InMemoryBindingStore):
            with contextlib.suppress(Exception):
                # A revoked route Binding stays revoked; the manager below
                # exposes the route as unavailable rather than re-granting it.
                effects.bindings.register(binding)
        _manager = HarnessSessionManager(
            engine.capabilities,
            warden=Warden(),
            policy=_configured_harness_policy(),
            invocation_service=effects.invocations,
            invocation_binding=binding,
            binding_store=effects.bindings,
        )
    return _manager


class StartBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    description: str = "harness session"
    role: str = "coder"
    workdir: str = "."
    task_id: str = "harness"
    subtask_id: str = "harness"


class SendBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    messages: list[dict[str, Any]] = Field(default_factory=list)


def _agent_spec(body: StartBody) -> AgentSpec:
    try:
        role = AgentRole(body.role)
    except ValueError:
        role = AgentRole.CODER
    return AgentSpec(
        role=role,
        task_id=body.task_id,
        subtask_id=body.subtask_id,
        description=body.description,
    )


@router.post("/sessions")
async def start_session(body: StartBody) -> dict[str, Any]:
    manager = await _get_manager()
    result = await manager.start(_agent_spec(body), workdir=body.workdir)
    if isinstance(result, Unavailable):
        raise HTTPException(status_code=503, detail=result.reason)
    return {"session_id": result}


@router.post("/sessions/{session_id}/send")
async def send_turn(session_id: str, body: SendBody) -> dict[str, Any]:
    try:
        manager = await _get_manager()
        result = await manager.send(session_id, body.messages)
    except HarnessInputBlocked as exc:
        raise HTTPException(
            status_code=400, detail=f"blocked by warden: {', '.join(exc.flags)}"
        ) from exc
    if isinstance(result, Unavailable):
        status = 404 if result.reason.startswith("unknown harness session") else 503
        raise HTTPException(status_code=status, detail=result.reason)
    return result


@router.get("/sessions/{session_id}/stream")
async def stream_session(session_id: str, request: Request) -> StreamingResponse:
    manager = await _get_manager()
    events = await manager.stream_events(session_id)
    if isinstance(events, Unavailable):
        status = 404 if events.reason.startswith("unknown harness session") else 503
        raise HTTPException(status_code=status, detail=events.reason)

    async def event_gen() -> Any:
        yield ": connected\n\n"
        for event in events:
            if await request.is_disconnected():
                break
            kind = event.get("type", "message") if isinstance(event, dict) else "message"
            yield f"event: {kind}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/sessions/{session_id}")
async def stop_session(session_id: str) -> dict[str, Any]:
    manager = await _get_manager()
    result = await manager.stop(session_id)
    if isinstance(result, Unavailable):
        status = 404 if result.reason.startswith("unknown harness session") else 503
        raise HTTPException(status_code=status, detail=result.reason)
    return {"stopped": True}
