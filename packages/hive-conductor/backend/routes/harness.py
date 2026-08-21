"""Inbound harness-session API (SPEC-208 §5).

Exposes the maistro-core ``HarnessSessionManager`` over HTTP so another
orchestrator (another maistro Master Orchestrator, or an external meta-harness)
can drive *this* instance as a foreign-harness subagent: start a session, send
turns, stream events, stop. Backed by the engine's capability registry + Warden;
degrades to 503 when no ``harness_runner`` provider is active (SAFE_NOOP), and
returns 400 when Warden refuses an inbound payload.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from services.engine import get_engine

from maistro.agents.spec.agent_spec import AgentRole, AgentSpec
from maistro.capabilities import HarnessSessionManager, Unavailable
from maistro.capabilities.slots.harness_runner import HarnessInputBlocked
from maistro.security.warden.detector import Warden

router = APIRouter(tags=["harness"])

_manager: HarnessSessionManager | None = None


def _get_manager() -> HarnessSessionManager:
    """Lazily build a process-wide manager over the engine registry + Warden."""
    global _manager
    if _manager is None:
        _manager = HarnessSessionManager(get_engine().capabilities, warden=Warden())
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
    result = await _get_manager().start(_agent_spec(body), workdir=body.workdir)
    if isinstance(result, Unavailable):
        raise HTTPException(status_code=503, detail=result.reason)
    return {"session_id": result}


@router.post("/sessions/{session_id}/send")
async def send_turn(session_id: str, body: SendBody) -> dict[str, Any]:
    try:
        result = await _get_manager().send(session_id, body.messages)
    except HarnessInputBlocked as exc:
        raise HTTPException(
            status_code=400, detail=f"blocked by warden: {', '.join(exc.flags)}"
        ) from exc
    if isinstance(result, Unavailable):
        raise HTTPException(status_code=404, detail=result.reason)
    return result


@router.get("/sessions/{session_id}/stream")
async def stream_session(session_id: str, request: Request) -> StreamingResponse:
    manager = _get_manager()

    async def event_gen() -> Any:
        yield ": connected\n\n"
        async for event in manager.stream(session_id):
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
    await _get_manager().stop(session_id)
    return {"stopped": True}
