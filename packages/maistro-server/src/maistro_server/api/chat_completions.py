"""OpenAI-compatible /v1/chat/completions endpoint for Open WebUI integration.

This translates between OpenAI chat format and the Maistro conductor pipeline.
Supports streaming SSE responses.
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
from maistro.tasks.models import TaskCreate
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


async def _stream_conductor_response(
    request: ChatCompletionRequest,
) -> AsyncIterator[str]:
    """Stream the conductor response as SSE chunks."""
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"

    # Send role chunk
    role_chunk = ChatCompletionChunk(
        id=chunk_id,
        model=request.model,
        choices=[StreamChoice(delta=DeltaMessage(role="assistant"))],
    )
    yield f"data: {role_chunk.model_dump_json()}\n\n"

    # For Phase 1, run the conductor and stream the final_answer in chunks.
    user_msg = _extract_user_message(request)

    try:
        response_text = await _run_conductor(user_msg)
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
    for i in range(0, len(response_text), STREAM_CHUNK_SIZE):
        text_chunk = response_text[i : i + STREAM_CHUNK_SIZE]
        content_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=request.model,
            choices=[StreamChoice(delta=DeltaMessage(content=text_chunk))],
        )
        yield f"data: {content_chunk.model_dump_json()}\n\n"

    # Send finish chunk
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
    _auth: RequireAuth,
) -> ChatCompletionResponse | StreamingResponse:
    if request.stream:
        return StreamingResponse(
            _stream_conductor_response(request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming: run conductor and return full response
    user_msg = _extract_user_message(request)

    try:
        response_text = await _run_conductor(user_msg)
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

    return ChatCompletionResponse(
        model=request.model,
        choices=[
            Choice(message=ChatMessage(role="assistant", content=response_text)),
        ],
    )
