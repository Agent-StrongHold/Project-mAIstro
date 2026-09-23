from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import stores
from fastapi import APIRouter, HTTPException, Request
from models.schemas import ChatCompletionRequest, ChatMessage, ChatSession, ChatSessionSummary
from pydantic import BaseModel, ConfigDict
from services.brief_chat import brief_turn
from services.chat_completion import _execute_workflow_with_approval, build_llm_port
from services.chat_completion import conversation_only as _conversation_only
from services.chat_gate import (
    REASON_BUDGET_EXCEEDED,
    REASON_SCANNER_ERROR,
    REASON_SCANNER_TIMEOUT,
    gate_untrusted,
    openai_refusal,
)
from services.owned_records import chat_sessions_for
from services.program_hyperagent import user_id_from_request

router = APIRouter(tags=["chat"])

# The input half of #315 has landed: every conversational message crosses the
# Warden boundary (`_gate_messages` -> `services.chat_gate`) before the model is
# called. External completion stays conversational-only; the separate workflow
# route below is explicitly permission- and approval-gated before it enters the
# existing canonical DAG execution path.
_DASHBOARD_EDIT_SCOPE = "dashboard_edit"
_DASHBOARD_EDIT_DISABLED = "AI dashboard editing is temporarily disabled until the governed widget capability boundary is enabled."
_CONVERSATION_SYSTEM_PROMPT = (
    "You are a Fantasia orchestration assistant. This external chat surface is temporarily "
    "conversational-only while governed tool boundaries are being completed. Answer concisely "
    "and helpfully, but do not claim to have executed tools, changed external systems, or taken actions."
)


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


class RunWorkflowBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dag_id: str
    goal: str = ""


@router.post("/workflows/run")
async def run_workflow(body: RunWorkflowBody, request: Request) -> dict:
    """Run a chat-selected workflow only after the shared approval inbox settles it."""
    user = getattr(request.state, "user", None) or {}
    user_id = str(user.get("id") or user.get("username") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    args = {"dag_id": body.dag_id}
    if body.goal:
        args["goal"] = body.goal
    return await _execute_workflow_with_approval(args, user_id)


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


async def _gate_messages(req: ChatCompletionRequest, request: Request, surface: str):
    """The Warden input boundary every external chat turn crosses (#315).

    One function for both routes so streaming and non-streaming cannot drift:
    the same scan, the same refusal shape, the same failure policy. A refused
    turn answers as an ordinary assistant message (`content_filter`, like the
    engine's #150 gate) and never reaches the model. Scanner failure and
    oversized input are wiring-level refusals, so they surface as HTTP errors
    rather than as conversational text a client might mistake for an answer.
    """
    user = getattr(request.state, "user", None) or {}
    decision = await gate_untrusted(
        req.messages, surface=surface, user_id=str(user.get("id") or user.get("username") or "")
    )
    if decision.allowed:
        return None
    if decision.reason == REASON_BUDGET_EXCEEDED:
        raise HTTPException(status_code=413, detail="request exceeds the security scan budget")
    if decision.reason in (REASON_SCANNER_TIMEOUT, REASON_SCANNER_ERROR):
        raise HTTPException(status_code=503, detail="security scanner unavailable; request refused")
    return openai_refusal(decision)


async def _interview_turn(req: ChatCompletionRequest, request: Request):
    """The brief interview's answer to this turn, when it is the interview's to answer.

    A turn in a workspace that asks for work opens the interview
    (SPEC-091726-7c2a); while one is open, every turn there is an answer to
    it. The reply comes after the Warden boundary and instead of the model:
    the interview is deterministic and writes nothing but its own state.
    """
    extra = req.model_extra or {}
    workspace_id = extra.get("workspace_id")
    if not isinstance(workspace_id, str) or not workspace_id:
        return None
    last_user = next(
        (m.get("content") for m in reversed(req.messages) if m.get("role") == "user"), None
    )
    if not isinstance(last_user, str):
        return None
    return await brief_turn(user_id_from_request(request), workspace_id, last_user)


@router.post("/complete")
async def complete(req: ChatCompletionRequest, request: Request) -> dict:
    """Non-streaming conversational completion; model-driven tools are M0-disabled."""
    if _dashboard_edit_requested(req):
        # Do not send the dashboard builder prompt to a model at all. The SPA
        # interprets textual ```widget_update``` blocks, so tool disabling alone
        # would not contain model-authored widget mutations (#483).
        return _disabled_dashboard_response()
    refusal = await _gate_messages(req, request, "chat_complete")
    if refusal is not None:
        return refusal
    turn = await _interview_turn(req, request)
    if turn is not None:
        return {
            "choices": [{"message": {"role": "assistant", "content": turn.text}}],
            "brief": turn.payload(),
        }
    messages = list(req.messages)
    if not any(message.get("role") == "system" for message in messages):
        messages.insert(0, {"role": "system", "content": _CONVERSATION_SYSTEM_PROMPT})
    llm = build_llm_port()
    return await llm.complete(_conversation_only(req.model_copy(update={"messages": messages})))


@router.post("/stream")
async def stream_complete(req: ChatCompletionRequest, request: Request):
    """SSE-compatible conversational completion with tool execution disabled.

    M0 containment deliberately prefers one final `done` event over preserving
    token streaming through the tool-capable agent loop. The Warden input
    boundary (#315) is crossed before the stream starts, through the same
    `_gate_messages` the non-streaming route uses — enforcement that lived in
    the generator would be enforcement only once streaming had begun.
    """
    import json

    from fastapi.responses import StreamingResponse

    if _dashboard_edit_requested(req):
        return StreamingResponse(
            _single_done_event(_DASHBOARD_EDIT_DISABLED),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    refusal = await _gate_messages(req, request, "chat_stream")
    if refusal is not None:
        content = refusal["choices"][0]["message"]["content"]
        return StreamingResponse(
            _single_done_event(content),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    turn = await _interview_turn(req, request)
    if turn is not None:
        return StreamingResponse(
            _brief_events(turn),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def event_gen():
        try:
            messages = list(req.messages)
            if not any(message.get("role") == "system" for message in messages):
                messages.insert(0, {"role": "system", "content": _CONVERSATION_SYSTEM_PROMPT})
            llm = build_llm_port()
            result = await llm.complete(
                _conversation_only(req.model_copy(update={"messages": messages}))
            )
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


def _brief_events(turn):
    """The interview's SSE frames: the brief so far, then the reply as `done`."""
    import json

    async def gen():
        yield f"data: {json.dumps(turn.payload())}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'content': turn.text})}\n\n"

    return gen()


def _single_done_event(content: str):
    """One `done` SSE frame — the shape every contained stream answer takes."""
    import json

    async def gen():
        yield f"data: {json.dumps({'type': 'done', 'content': content})}\n\n"

    return gen()
