"""OpenAI-compatible /v1/chat/completions endpoint for Open WebUI integration.

This translates between OpenAI chat format and the Maistro conductor pipeline.
Supports streaming SSE responses.

Two things this endpoint did not do, and now does (#150).

**It is scanned.** `CLAUDE.md`'s sixth decision is that all input is untrusted
and the Warden scans at every trust boundary. This is an externally reachable
boundary; it was not scanned. `Gate.process_input` is the reusable primitive for
exactly that, and a `Gate()` self-wires a Warden, so the door is guarded by
default rather than only when a deployment remembers to configure one. A blocked
turn gets an ordinary OpenAI-shaped assistant message with
`finish_reason="content_filter"` — a refusal is a normal answer, not a 500 — and
never reaches `run_task`.

**Its turns have a canonical Run.** The same seam `route_request()` uses
(ADR-082326-c126): one Run per turn, `run_id` returned additively, terminalized
when the work ends. The Run is only RUNNING while the conductor is running, so a
client that disconnects mid-stream cannot leave one open — by then it is already
terminal, which is the true record: the work finished, the reader left.

This endpoint still does not go through the Conduit. That is #142's, and needs a
Container this app does not build; closing the unscanned door did not have to
wait for it.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from maistro.agents.conductor import run_task
from maistro.agents.types import LLMProviderError
from maistro.constants import STREAM_CHUNK_SIZE
from maistro.runs.chat_admission import ChatRunAdmitter
from maistro.runs.model import Run, RunStatus
from maistro.runs.store import RunStore
from maistro.security._types import AuthContext
from maistro.security.gate import Gate
from maistro.tasks.models import TaskCreate
from maistro_server.api.auth import RequireAuth
from maistro_server.api.principal import AuthenticatedPrincipal

logger = structlog.get_logger()

router = APIRouter(prefix="/v1", tags=["openai-compat"])

#: OpenAI's own finish_reason for a refusal, so a client that already handles
#: moderation needs no Maistro-specific case.
CONTENT_FILTER = "content_filter"

_gate: Gate | None = None
_chat_admitter: ChatRunAdmitter | None = None
_run_store: RunStore | None = None


def configure_gate(gate: Gate | None) -> None:
    """Install the Gate this endpoint scans with, from the app lifespan.

    None restores the default. There is no "no Gate" state: `get_gate()` builds
    a plain one on first use, because a deployment that forgot to configure this
    must still be scanned. Configuring one only adds what a bare Gate lacks —
    strike tracking, and a Warden the rest of the process shares.
    """
    global _gate
    _gate = gate


def get_gate() -> Gate:
    global _gate
    if _gate is None:
        _gate = Gate()
    return _gate


def configure_chat_admission(
    admitter: ChatRunAdmitter | None,
    run_store: RunStore | None = None,
) -> None:
    """Install the seam chat turns are admitted through, from the lifespan."""
    global _chat_admitter, _run_store
    _chat_admitter = admitter
    _run_store = run_store


class ChatMessage(BaseModel):
    role: str
    content: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str = "maistro-tier-2"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


class Choice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:8]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = ""
    choices: list[Choice]
    usage: Usage = Field(default_factory=Usage)
    #: The canonical Run this turn was admitted as (#150). Additive: every
    #: field an OpenAI client reads is unchanged, and this one sits beside
    #: them. Explicitly `null` rather than absent when no Run store is wired,
    #: because "this deployment records no Run" and "I forgot to send it" are
    #: different answers and a client should be able to tell them apart.
    run_id: str | None = None


class DeltaMessage(BaseModel):
    role: str | None = None
    content: str | None = None


class StreamChoice(BaseModel):
    index: int = 0
    delta: DeltaMessage
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str = ""
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = ""
    choices: list[StreamChoice]
    #: Set on the opening and closing chunks of a stream (#150), so a consumer
    #: that keeps only one of them still learns the turn's canonical identity.
    #: Content chunks leave it null rather than repeating it on every frame.
    run_id: str | None = None


def _extract_user_message(request: ChatCompletionRequest) -> str:
    """Extract the last user message from the chat request."""
    return (
        next(
            (m.content for m in reversed(request.messages) if m.role == "user" and m.content),
            "",
        )
        or "No task specified"
    )


async def _run_conductor(user_msg: str) -> str:
    """Run the conductor pipeline and return the final answer text.

    Raises appropriate exceptions for callers to handle.
    """
    task = TaskCreate(description=user_msg)
    result = await run_task(task)
    return result.final_answer or "Task completed successfully."


def _auth_context(auth: AuthenticatedPrincipal | None) -> AuthContext | None:
    """The Gate's identity view of an authenticated caller.

    Built rather than passed through: `AuthContext` is what every strike path
    keys on, and handing the Gate an object that merely happens to have a
    `user_id` would work until one of those paths reached for anything else.
    """
    if auth is None:
        return None
    return AuthContext(user_id=auth.user_id, roles=auth.roles)


async def _scan(user_msg: str, auth: AuthenticatedPrincipal | None) -> str | None:
    """The block reason, or None when the turn may proceed.

    A Gate that raises must not become an open door, so a scan that fails for
    its own reasons refuses the turn. That is the opposite of how the Run
    admitter fails — a turn is answered without a Run, and refused without a
    scan — because the two protect different things: one is a record, the other
    is the boundary.
    """
    try:
        verdict = await get_gate().process_input(
            user_msg, task_type="chat", auth=_auth_context(auth)
        )
    except Exception:
        logger.exception("chat_completions_gate_error")
        return "Request could not be screened and was not run."
    if not verdict.blocked:
        return None
    await logger.awarning("chat_completions_gate_block", reason=verdict.block_reason)
    return f"Request blocked: {verdict.block_reason}"


async def _admit_turn(
    request: ChatCompletionRequest,
    auth: AuthenticatedPrincipal | None,
) -> Run | None:
    """Admit this turn as a canonical Run, or None when none is wired.

    Never refuses the turn. The chat path has no receipt to fall back on, so
    failing here would turn "this process cannot record the turn" into "this
    process cannot answer" — the same rule `Container.route_request` follows.
    """
    if _chat_admitter is None or _run_store is None:
        return None
    try:
        run = await _chat_admitter.admit(
            [m.model_dump() for m in request.messages],
            actor_principal_id=auth.user_id if auth else None,
        )
        await _run_store.transition_run(run.run_id, RunStatus.QUEUED)
        return await _run_store.transition_run(run.run_id, RunStatus.RUNNING)
    except Exception:
        logger.exception("chat_completions_run_admission_failed")
        return None


async def _close_turn(
    run: Run | None,
    *,
    error: str | None = None,
    result: object | None = None,
) -> None:
    """Terminalize a turn's Run. A Run left RUNNING reads as a dead process."""
    if run is None or _run_store is None:
        return
    target = RunStatus.FAILED if error is not None else RunStatus.COMPLETED
    try:
        await _run_store.transition_run(run.run_id, target, result=result, error=error)
    except Exception:
        logger.exception("chat_completions_run_close_failed", run_id=run.run_id)


async def _conduct(user_msg: str, run: Run | None) -> str:
    """Run the conductor, terminalizing the turn's Run either way.

    The Run is closed here rather than when the stream ends, and that is the
    whole answer to "what if the client disconnects mid-stream": by the time
    any content chunk is written the Run is already terminal, so a reader who
    leaves cannot strand it. It also stays true — the work did finish.
    """
    try:
        response_text = await _run_conductor(user_msg)
    except BaseException as exc:
        await _close_turn(run, error=f"{type(exc).__name__}: {exc}")
        raise
    await _close_turn(run)
    return response_text


def _text_chunks(chunk_id: str, model: str, text: str) -> list[str]:
    """The SSE content chunks for one answer, in small pieces."""
    return [
        "data: "
        + ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(content=text[i : i + STREAM_CHUNK_SIZE]))],
        ).model_dump_json()
        + "\n\n"
        for i in range(0, len(text), STREAM_CHUNK_SIZE)
    ]


async def _stream_conductor_response(
    request: ChatCompletionRequest,
    auth: AuthenticatedPrincipal | None = None,
    run: Run | None = None,
) -> AsyncIterator[str]:
    """Stream the conductor response as SSE chunks."""
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    run_id = run.run_id if run is not None else None

    # Send role chunk
    role_chunk = ChatCompletionChunk(
        id=chunk_id,
        model=request.model,
        choices=[StreamChoice(delta=DeltaMessage(role="assistant"))],
        run_id=run_id,
    )
    yield f"data: {role_chunk.model_dump_json()}\n\n"

    # For Phase 1, run the conductor and stream the final_answer in chunks.
    user_msg = _extract_user_message(request)

    blocked = await _scan(user_msg, auth)
    if blocked is not None:
        # A refusal is an ordinary answer: the same chunks a real one would
        # produce, finished as content_filter. `run_task` is never reached.
        await _close_turn(run, result={"gate_blocked": True})
        for chunk in _text_chunks(chunk_id, request.model, blocked):
            yield chunk
        filtered = ChatCompletionChunk(
            id=chunk_id,
            model=request.model,
            choices=[StreamChoice(delta=DeltaMessage(), finish_reason=CONTENT_FILTER)],
            run_id=run_id,
        )
        yield f"data: {filtered.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"
        return

    try:
        response_text = await _conduct(user_msg, run)
    except TimeoutError:
        logger.error("chat_completions_timeout", user_msg=user_msg[:100])
        error_event = {"error": {"type": "timeout", "message": "LLM call timed out"}}
        yield f"data: {json.dumps(error_event)}\n\n"
        yield "data: [DONE]\n\n"
        return
    except LLMProviderError:
        logger.exception("chat_completions_llm_error", user_msg=user_msg[:100])
        error_event = {"error": {"type": "upstream_error", "message": "LLM provider error"}}
        yield f"data: {json.dumps(error_event)}\n\n"
        yield "data: [DONE]\n\n"
        return
    except Exception:
        logger.exception("chat_completions_error", user_msg=user_msg[:100])
        error_event = {"error": {"type": "internal_error", "message": "Internal server error"}}
        yield f"data: {json.dumps(error_event)}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Stream content in small chunks for responsive feel
    for chunk in _text_chunks(chunk_id, request.model, response_text):
        yield chunk

    # Send finish chunk
    finish_chunk = ChatCompletionChunk(
        id=chunk_id,
        model=request.model,
        choices=[StreamChoice(delta=DeltaMessage(), finish_reason="stop")],
        run_id=run_id,
    )
    yield f"data: {finish_chunk.model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    request: ChatCompletionRequest,
    auth: RequireAuth,
) -> ChatCompletionResponse | StreamingResponse:
    # Admitted here rather than inside the generator, so the streaming branch
    # can name the Run in a response header — the one place a client can read
    # it without parsing SSE at all.
    run = await _admit_turn(request, auth)

    if request.stream:
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        if run is not None:
            headers["X-Maistro-Run-Id"] = run.run_id
        return StreamingResponse(
            _stream_conductor_response(request, auth, run),
            media_type="text/event-stream",
            headers=headers,
        )

    # Non-streaming: run conductor and return full response
    user_msg = _extract_user_message(request)

    blocked = await _scan(user_msg, auth)
    if blocked is not None:
        await _close_turn(run, result={"gate_blocked": True})
        return _answer(request, blocked, run, finish_reason=CONTENT_FILTER)

    try:
        response_text = await _conduct(user_msg, run)
    except TimeoutError:
        logger.error("chat_completions_timeout", user_msg=user_msg[:100])
        raise HTTPException(status_code=504, detail="LLM call timed out") from None
    except LLMProviderError as exc:
        # Upstream detail goes to the log only — echoing it leaks provider
        # internals to clients (June audit 3.5; the streaming branch already
        # sanitizes the same way).
        logger.exception("chat_completions_llm_error", user_msg=user_msg[:100])
        raise HTTPException(status_code=502, detail="LLM provider error") from exc
    except Exception as exc:
        logger.exception("chat_completions_error", user_msg=user_msg[:100])
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    return _answer(request, response_text, run)


def _answer(
    request: ChatCompletionRequest,
    text: str,
    run: Run | None,
    *,
    finish_reason: str = "stop",
) -> ChatCompletionResponse:
    """One assistant answer, with `run_id` alongside rather than instead.

    `run_id` is null when no Run was admitted — see the field's own note for
    why that is stated rather than omitted.
    """
    response = ChatCompletionResponse(
        model=request.model,
        choices=[
            Choice(
                message=ChatMessage(role="assistant", content=text),
                finish_reason=finish_reason,
            )
        ],
    )
    if run is not None:
        response.run_id = run.run_id
    return response
