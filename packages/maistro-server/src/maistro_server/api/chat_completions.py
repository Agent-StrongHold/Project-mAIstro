"""OpenAI-compatible /v1/chat/completions endpoint for Open WebUI integration.

This translates between OpenAI chat format and the Maistro conductor pipeline.
Supports streaming SSE responses.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from maistro.agents.conductor import run_task
from maistro.agents.types import LLMProviderError
from maistro.constants import STREAM_CHUNK_SIZE
from maistro.tasks.models import TaskCreate
from maistro_server.api import chat_guard
from maistro_server.api.auth import RequireAuth

logger = structlog.get_logger()

router = APIRouter(prefix="/v1", tags=["openai-compat"])


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
    #: The turn's canonical Run (#150). Additive — an OpenAI client ignores it —
    #: and empty only when this process has no spine wired.
    run_id: str = ""


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
    #: The turn's canonical Run, carried on the first chunk of the stream and on
    #: a refusal. Additive exactly as on the non-streaming response — an OpenAI
    #: client ignores it. Without it a streaming caller had no way to name the
    #: Run this endpoint created for its turn: `/runs` resolves by Run ID only,
    #: and the `chunk_id` it can see is request provenance, not an identity.
    run_id: str = ""


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


def _refusal_chunks(chunk_id: str, model: str, reason: str, run_id: str = "") -> list[str]:
    """A Gate refusal as ordinary SSE content, not a transport error.

    The client asked a question and is being told no; that is an answer, and an
    OpenAI-compatible caller has no way to read a mid-stream error event as one.
    """
    content = ChatCompletionChunk(
        id=chunk_id,
        model=model,
        choices=[StreamChoice(delta=DeltaMessage(content=reason))],
        run_id=run_id,
    )
    finish = ChatCompletionChunk(
        id=chunk_id,
        model=model,
        choices=[StreamChoice(delta=DeltaMessage(), finish_reason="stop")],
    )
    return [
        f"data: {content.model_dump_json()}\n\n",
        f"data: {finish.model_dump_json()}\n\n",
        "data: [DONE]\n\n",
    ]


@dataclass
class _TurnState:
    """The Run for one streaming turn, and whether anything has closed it yet.

    Shared between the two generators because both can be the last code to run:
    `_stream_answer` closes the Run on every ordinary exit, and the outer
    `finally` has to clean up when the client vanishes instead. A plain local
    would leave the outer generator unable to tell "already closed" from "never
    started", and it would re-close a Run that had legitimately completed.
    """

    run: Any = None
    closed: bool = False


async def _stream_conductor_response(
    request: ChatCompletionRequest,
    user_id: str = "",
) -> AsyncIterator[str]:
    """Stream the conductor response as SSE chunks."""
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    user_msg = _extract_user_message(request)

    # Scanned before the role chunk, so a blocked prompt never reaches the
    # conductor and the stream carries only the refusal (#150).
    verdict = await chat_guard.scan_prompt(user_msg)
    if verdict is not None and verdict.blocked:
        reason = f"{chat_guard.BLOCKED_RUN_ERROR_PREFIX}{verdict.block_reason}"
        logger.warning("chat_completions_blocked", streaming=True)
        # Admitted and cancelled, exactly as the non-streaming branch does. A
        # refusal is an outcome of a turn, not the absence of one: leaving this
        # path without a Run meant policy-blocked streaming requests were the
        # one class of traffic missing from the execution audit this endpoint
        # exists to produce.
        blocked_run = await chat_guard.admit_turn(user_msg, request_id=chunk_id, user_id=user_id)
        await chat_guard.close_turn(blocked_run, error=reason)
        blocked_id = blocked_run.run_id if blocked_run is not None else ""
        for chunk in _refusal_chunks(chunk_id, request.model, reason, blocked_id):
            yield chunk
        return

    # `finally` rather than a close at each exit: a client that disconnects
    # mid-stream raises `GeneratorExit` into this body, and a Run left RUNNING
    # is what recovery scans read as a process that died (#150).
    #
    # Admission sits *inside* the try, with `on_created` filling the state as
    # soon as the Run is persisted. Against PostgreSQL admission is several
    # separate awaits, so a disconnect part-way through would otherwise strand
    # a CREATED or QUEUED Run that this cleanup never learned the id of.
    state = _TurnState()
    try:
        state.run = await chat_guard.admit_turn(
            user_msg,
            request_id=chunk_id,
            user_id=user_id,
            on_created=lambda created: setattr(state, "run", created),
        )
        # Send role chunk
        role_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=request.model,
            choices=[StreamChoice(delta=DeltaMessage(role="assistant"))],
            run_id=state.run.run_id if state.run is not None else "",
        )
        yield f"data: {role_chunk.model_dump_json()}\n\n"

        async for chunk in _stream_answer(request, chunk_id, user_msg, state):
            yield chunk
    finally:
        if not state.closed:
            await chat_guard.abandon_turn(state.run, error="stream ended before completion")


async def _stream_answer(
    request: ChatCompletionRequest,
    chunk_id: str,
    user_msg: str,
    state: _TurnState,
) -> AsyncIterator[str]:
    """The conductor call and its chunks, once the prompt has been admitted.

    Every exit closes the turn's Run and marks `state.closed`, so the caller's
    `finally` can tell a finished turn from an abandoned one. The error branches
    keep their sanitised payloads unchanged — the upstream detail stays in the
    log, never in the stream (June audit 3.5).
    """
    run = state.run
    try:
        response_text = await _run_conductor(user_msg)
    except TimeoutError:
        logger.error("chat_completions_timeout", user_msg=user_msg[:100])
        await chat_guard.fail_turn(run, error="LLM call timed out")
        state.closed = True
        error_event = {"error": {"type": "timeout", "message": "LLM call timed out"}}
        yield f"data: {json.dumps(error_event)}\n\n"
        yield "data: [DONE]\n\n"
        return
    except LLMProviderError:
        logger.exception("chat_completions_llm_error", user_msg=user_msg[:100])
        await chat_guard.fail_turn(run, error="LLM provider error")
        state.closed = True
        error_event = {"error": {"type": "upstream_error", "message": "LLM provider error"}}
        yield f"data: {json.dumps(error_event)}\n\n"
        yield "data: [DONE]\n\n"
        return
    except Exception:
        logger.exception("chat_completions_error", user_msg=user_msg[:100])
        await chat_guard.fail_turn(run, error="internal error")
        state.closed = True
        error_event = {"error": {"type": "internal_error", "message": "Internal server error"}}
        yield f"data: {json.dumps(error_event)}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Stream content in small chunks for responsive feel
    for i in range(0, len(response_text), STREAM_CHUNK_SIZE):
        text_chunk = response_text[i : i + STREAM_CHUNK_SIZE]
        content_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=request.model,
            choices=[StreamChoice(delta=DeltaMessage(content=text_chunk))],
        )
        yield f"data: {content_chunk.model_dump_json()}\n\n"

    # Closed *before* the terminal chunk goes out, not after. A client that
    # stops reading the moment it sees `finish_reason="stop"` closes the
    # generator while it is suspended at that yield, so a close placed after it
    # never runs — and the caller's cleanup would then record a turn the client
    # received in full as FAILED. The answer is complete at this point; the
    # remaining yields are transport.
    await chat_guard.close_turn(run)
    state.closed = True

    finish_chunk = ChatCompletionChunk(
        id=chunk_id,
        model=request.model,
        choices=[StreamChoice(delta=DeltaMessage(), finish_reason="stop")],
    )
    yield f"data: {finish_chunk.model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    request: ChatCompletionRequest,
    auth: RequireAuth,
) -> ChatCompletionResponse | StreamingResponse:
    # The principal, not `_auth` discarded. Every Run this endpoint created was
    # anonymous while the route had the caller's identity in hand, which
    # ADR-082226-c126 cannot honour: a turn nobody can be attributed to is a
    # turn the audit cannot answer questions about. `None` in an unauthenticated
    # deployment stays an empty string, which the admitter reads as "no actor".
    user_id = auth.user_id if auth is not None else ""

    if request.stream:
        return StreamingResponse(
            _stream_conductor_response(request, user_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming: run conductor and return full response
    user_msg = _extract_user_message(request)

    # The trust boundary (#150). A refused prompt never reaches the conductor,
    # and the caller gets an ordinary assistant message rather than a 4xx: the
    # request was well-formed and the answer is "no".
    verdict = await chat_guard.scan_prompt(user_msg)
    if verdict is not None and verdict.blocked:
        logger.warning("chat_completions_blocked", streaming=False)
        reason = f"{chat_guard.BLOCKED_RUN_ERROR_PREFIX}{verdict.block_reason}"
        run = await chat_guard.admit_turn(user_msg, user_id=user_id)
        await chat_guard.close_turn(run, error=reason)
        return ChatCompletionResponse(
            model=request.model,
            choices=[Choice(message=ChatMessage(role="assistant", content=reason))],
            run_id=run.run_id if run is not None else "",
        )

    run = await chat_guard.admit_turn(user_msg, user_id=user_id)
    try:
        response_text = await _run_conductor(user_msg)
    except TimeoutError:
        logger.error("chat_completions_timeout", user_msg=user_msg[:100])
        await chat_guard.fail_turn(run, error="LLM call timed out")
        raise HTTPException(status_code=504, detail="LLM call timed out") from None
    except LLMProviderError as exc:
        # Upstream detail goes to the log only — echoing it leaks provider
        # internals to clients (June audit 3.5; the streaming branch already
        # sanitizes the same way).
        logger.exception("chat_completions_llm_error", user_msg=user_msg[:100])
        await chat_guard.fail_turn(run, error="LLM provider error")
        raise HTTPException(status_code=502, detail="LLM provider error") from exc
    except Exception as exc:
        logger.exception("chat_completions_error", user_msg=user_msg[:100])
        await chat_guard.fail_turn(run, error="internal error")
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    await chat_guard.close_turn(run)
    return ChatCompletionResponse(
        model=request.model,
        choices=[
            Choice(message=ChatMessage(role="assistant", content=response_text)),
        ],
        run_id=run.run_id if run is not None else "",
    )
