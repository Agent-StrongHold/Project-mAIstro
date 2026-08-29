from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import stores
from fastapi import APIRouter, Request
from models.schemas import ChatCompletionRequest, ChatMessage, ChatSession, ChatSessionSummary
from pydantic import BaseModel, ConfigDict
from services.chat_completion import build_llm_port
from services.chat_completion import conversation_only as _conversation_only
from services.owned_records import chat_sessions_for

router = APIRouter(tags=["chat"])

# M0 containment (#483/#484): external Conductor chat is conversational-only
# until the canonical Warden input/tool-result/output boundaries land in #315.
# The tool-capable agent loop remains implemented behind services.chat_completion
# for trusted/internal callers, but this public route must not invoke it.
_DASHBOARD_EDIT_SCOPE = "dashboard_edit"
_DASHBOARD_EDIT_DISABLED = "AI dashboard editing is temporarily disabled until the governed widget capability boundary is enabled."


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


def _dashboard_edit_requested(req: ChatCompletionRequest) -> bool:
    extra = req.model_extra or {}
    return extra.get("tools_scope") == _DASHBOARD_EDIT_SCOPE


def _disabled_dashboard_response() -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": _DASHBOARD_EDIT_DISABLED}}]}


@router.post("/complete")
async def complete(req: ChatCompletionRequest, request: Request) -> dict:
    """Non-streaming conversational completion; model-driven tools are M0-disabled."""
    del request  # authentication/ownership is enforced by middleware before this route
    if _dashboard_edit_requested(req):
        # Do not send the dashboard builder prompt to a model at all. The SPA
        # interprets textual ```widget_update``` blocks, so tool disabling alone
        # would not contain model-authored widget mutations (#483).
        return _disabled_dashboard_response()
    llm = build_llm_port()
    return await llm.complete(_conversation_only(req))


@router.post("/stream")
async def stream_complete(req: ChatCompletionRequest, request: Request):
    """SSE-compatible conversational completion with tool execution disabled.

    M0 containment deliberately prefers one final `done` event over preserving
    token streaming through the tool-capable agent loop. Full streaming parity
    returns with the canonical Warden boundary in #315.
    """
    import json

    from fastapi.responses import StreamingResponse

    del request

    async def event_gen():
        if _dashboard_edit_requested(req):
            yield f"data: {json.dumps({'type': 'done', 'content': _DASHBOARD_EDIT_DISABLED})}\n\n"
            return
        try:
            llm = build_llm_port()
            result = await llm.complete(_conversation_only(req))
            choice = (result.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            yield f"data: {json.dumps({'type': 'done', 'content': content})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'done', 'content': f'Error: {type(exc).__name__}'})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
