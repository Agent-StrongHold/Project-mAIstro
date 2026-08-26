from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import stores
from fastapi import APIRouter, Request
from models.schemas import ChatCompletionRequest, ChatMessage, ChatSession, ChatSessionSummary
from pydantic import BaseModel, ConfigDict
from services.chat_completion import run_chat_completion
from services.owned_records import chat_sessions_for

router = APIRouter(tags=["chat"])

# Handlers take `chat_sessions_for(request)` and never `stores.chat_sessions`,
# so a route cannot reach another user's session even by mistake (#312).
# `scripts/check-owned-store-access.py` enforces that this is the only door.


def _now() -> datetime:
    return datetime.now(UTC)


class CreateSessionBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = "New chat"


@router.get("/sessions", response_model=list[ChatSessionSummary])
def list_sessions(request: Request) -> list[ChatSessionSummary]:
    owned = chat_sessions_for(request)
    stores.seed_chat_for(owned.owner_id)
    out = [
        ChatSessionSummary(
            id=s.id,
            user_id=s.user_id,
            title=s.title,
            message_count=len(s.messages),
            updated_at=s.updated_at,
        )
        for s in owned.values()
    ]
    return sorted(out, key=lambda x: x.updated_at, reverse=True)


@router.post("/sessions", response_model=ChatSession)
def create_session(body: CreateSessionBody, request: Request) -> ChatSession:
    sid = str(uuid4())
    t = _now()
    session = ChatSession(id=sid, title=body.title, messages=[], created_at=t, updated_at=t)
    return chat_sessions_for(request).create(sid, session)


@router.get("/sessions/{session_id}", response_model=ChatSession)
def get_session(session_id: str, request: Request) -> ChatSession:
    owned = chat_sessions_for(request)
    stores.seed_chat_for(owned.owner_id)
    return owned.require(session_id)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, request: Request) -> None:
    chat_sessions_for(request).discard(session_id)


class AppendMessageBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["user", "assistant", "system", "tool"] = "user"
    content: str


@router.post("/sessions/{session_id}/messages", response_model=ChatMessage)
def append_message(session_id: str, body: AppendMessageBody, request: Request) -> ChatMessage:
    owned = chat_sessions_for(request)
    stores.seed_chat_for(owned.owner_id)
    session = owned.require(session_id)
    msg = ChatMessage(
        id=str(uuid4()),
        role=body.role,
        content=body.content,
        timestamp=_now(),
    )
    session.messages.append(msg)
    session.updated_at = _now()
    owned.persist(session_id)
    return msg


@router.post("/complete")
async def complete(req: ChatCompletionRequest, request: Request) -> dict:
    """Non-streaming completion — PM agent with real tools."""
    user = getattr(request.state, "user", None) or {}
    user_id = str(user.get("id", ""))
    return await run_chat_completion(req, user_id=user_id)


@router.post("/stream")
async def stream_complete(req: ChatCompletionRequest, request: Request):
    """SSE streaming — sends real status updates as tools execute."""
    import json

    from fastapi.responses import StreamingResponse
    from services.chat_completion import run_chat_completion_streaming

    user = getattr(request.state, "user", None) or {}
    user_id = str(user.get("id", ""))

    async def event_gen():
        try:
            async for event in run_chat_completion_streaming(req, user_id=user_id):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'done', 'content': f'Error: {e}'})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
