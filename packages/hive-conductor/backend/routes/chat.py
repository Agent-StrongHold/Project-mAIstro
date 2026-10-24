from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from models.schemas import (
    ChatCompletionRequest,
    ChatMessage,
    ChatSession,
    ChatSessionSummary,
    CreateSessionBody,
)
from pydantic import BaseModel, ConfigDict
from services import conversation_sessions
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
from services.chat_runs import admit_turn, cancel_unstarted, execute_turn
from services.program_hyperagent import user_id_from_request
from services.request_principal import require_actor_id

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


def _history_as_messages(session_id: str, history: list[dict[str, str]]) -> list[ChatMessage]:
    """Build API ChatMessage rows from SessionStore history.

    Stable ids are derived from history order (the store's seq) so a reload
    sees the same identities without a second transcript index.
    """
    out: list[ChatMessage] = []
    for seq, entry in enumerate(history):
        role = entry.get("role", "user")
        if role not in ("user", "assistant", "system", "tool"):
            continue
        out.append(
            ChatMessage(
                id=f"{session_id}:{seq}",
                role=role,  # type: ignore[arg-type]
                content=entry.get("content", ""),
            )
        )
    return out


def _to_chat_session(
    record: conversation_sessions.ConversationSessionRecord,
    history: list[dict[str, str]],
) -> ChatSession:
    return ChatSession(
        id=record.session_id,
        user_id=record.user_id,
        workspace_id=record.workspace_id,
        title=record.title,
        messages=_history_as_messages(record.session_id, history),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/sessions", response_model=list[ChatSessionSummary])
async def list_sessions(
    request: Request,
    workspace_id: str = Query(...),
) -> list[ChatSessionSummary]:
    user_id = require_actor_id(request)
    records = await conversation_sessions.list_for(user_id, workspace_id)
    out: list[ChatSessionSummary] = []
    for record in records:
        _rec, history = await conversation_sessions.get(user_id, record.session_id)
        out.append(
            ChatSessionSummary(
                id=record.session_id,
                user_id=record.user_id,
                workspace_id=record.workspace_id,
                title=record.title,
                message_count=len(history),
                updated_at=record.updated_at,
            )
        )
    return out


@router.post("/sessions", response_model=ChatSession)
async def create_session(body: CreateSessionBody, request: Request) -> ChatSession:
    user_id = require_actor_id(request)
    record = await conversation_sessions.create(user_id, body.workspace_id, body.title)
    return _to_chat_session(record, [])


@router.get("/sessions/{session_id}", response_model=ChatSession)
async def get_session(session_id: str, request: Request) -> ChatSession:
    user_id = require_actor_id(request)
    record, history = await conversation_sessions.get(user_id, session_id)
    return _to_chat_session(record, history)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request) -> None:
    user_id = require_actor_id(request)
    await conversation_sessions.delete(user_id, session_id)


class RunWorkflowBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dag_id: str
    goal: str = ""


@router.post("/workflows/run")
async def run_workflow(body: RunWorkflowBody, request: Request) -> dict:
    """Run a chat-selected workflow only after the shared approval inbox settles it."""
    user_id = require_actor_id(request)
    args = {"dag_id": body.dag_id}
    if body.goal:
        args["goal"] = body.goal
    return await _execute_workflow_with_approval(args, user_id)


class AppendMessageBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["user", "assistant", "system", "tool"] = "user"
    content: str


@router.post("/sessions/{session_id}/messages", response_model=ChatMessage)
async def append_message(session_id: str, body: AppendMessageBody, request: Request) -> ChatMessage:
    user_id = require_actor_id(request)
    conversation_sessions.require_owned(user_id, session_id)
    msg_id = str(uuid4())
    # SessionStore only persists user/assistant turns; other roles are refused
    # at the store boundary. The API still accepts the role for shape parity.
    if body.role in ("user", "assistant"):
        await conversation_sessions.append_turn(
            session_id,
            [{"role": body.role, "content": body.content}],
            turn_id=msg_id,
        )
    return ChatMessage(
        id=msg_id,
        role=body.role,
        content=body.content,
        timestamp=_now(),
    )


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
    decision = await gate_untrusted(
        req.messages, surface=surface, user_id=require_actor_id(request)
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


def _conversation_messages(req: ChatCompletionRequest) -> list[dict]:
    messages = list(req.messages)
    if not any(message.get("role") == "system" for message in messages):
        messages.insert(0, {"role": "system", "content": _CONVERSATION_SYSTEM_PROMPT})
    return messages


async def _admit(req: ChatCompletionRequest, request: Request, messages: list[dict]):
    extra = req.model_extra or {}
    return await admit_turn(
        request,
        messages,
        workspace_id=extra.get("workspace_id"),
        session_id=extra.get("session_id"),
    )


def _model_call(req: ChatCompletionRequest, messages: list[dict]):
    async def call() -> dict:
        llm = build_llm_port()
        return await llm.complete(_conversation_only(req.model_copy(update={"messages": messages})))

    return call


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
    messages = _conversation_messages(req)
    turn = await _admit(req, request, messages)
    return await execute_turn(turn, messages, _model_call(req, messages))


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

    # Admitted before the response exists, so a turn that cannot be admitted
    # is a 503 rather than a 200 stream that then fails (#1037, #1108).
    messages = _conversation_messages(req)
    turn = await _admit(req, request, messages)
    run_id = turn.run.run_id

    started = False

    async def event_gen():
        nonlocal started
        started = True
        try:
            result = await execute_turn(turn, messages, _model_call(req, messages))
            choice = (result.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            yield f"data: {json.dumps({'type': 'done', 'content': content, 'run_id': run_id})}\n\n"
        except Exception as exc:
            content = f"Error: {type(exc).__name__}"
            yield f"data: {json.dumps({'type': 'done', 'content': content, 'run_id': run_id})}\n\n"

    async def on_finished() -> None:
        if not started:
            await cancel_unstarted(turn)

    return _RunStreamingResponse(
        event_gen(),
        on_finished=on_finished,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class _RunStreamingResponse(StreamingResponse):
    """A stream that settles its admitted Run even if its body never runs."""

    def __init__(self, content, *, on_finished, **kwargs) -> None:
        super().__init__(content, **kwargs)
        self._on_finished = on_finished

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._on_finished()


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
