from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException, Request
from models.schemas import ChatCompletionRequest, ChatMessage, ChatSession, ChatSessionSummary
from pydantic import BaseModel, ConfigDict
from services.chat_completion import run_chat_completion

router = APIRouter(tags=["chat"])


def _now() -> datetime:
    return datetime.now(UTC)


class CreateSessionBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = "New chat"


@router.get("/sessions", response_model=list[ChatSessionSummary])
def list_sessions() -> list[ChatSessionSummary]:
    stores.seed_chat_if_empty()
    out: list[ChatSessionSummary] = []
    for s in stores.chat_sessions.values():
        out.append(
            ChatSessionSummary(
                id=s.id,
                title=s.title,
                message_count=len(s.messages),
                updated_at=s.updated_at,
            )
        )
    return sorted(out, key=lambda x: x.updated_at, reverse=True)


@router.post("/sessions", response_model=ChatSession)
def create_session(body: CreateSessionBody) -> ChatSession:
    sid = str(uuid4())
    t = _now()
    session = ChatSession(id=sid, title=body.title, messages=[], created_at=t, updated_at=t)
    stores.chat_sessions[sid] = session
    return session


@router.get("/sessions/{session_id}", response_model=ChatSession)
def get_session(session_id: str) -> ChatSession:
    stores.seed_chat_if_empty()
    if session_id not in stores.chat_sessions:
        raise HTTPException(status_code=404, detail="session not found")
    return stores.chat_sessions[session_id]


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str) -> None:
    stores.chat_sessions.pop(session_id, None)


class AppendMessageBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["user", "assistant", "system", "tool"] = "user"
    content: str


@router.post("/sessions/{session_id}/messages", response_model=ChatMessage)
def append_message(session_id: str, body: AppendMessageBody) -> ChatMessage:
    stores.seed_chat_if_empty()
    if session_id not in stores.chat_sessions:
        raise HTTPException(status_code=404, detail="session not found")
    session = stores.chat_sessions[session_id]
    msg = ChatMessage(
        id=str(uuid4()),
        role=body.role,
        content=body.content,
        timestamp=_now(),
    )
    session.messages.append(msg)
    session.updated_at = _now()
    stores.chat_sessions.persist(session_id)
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
