"""OpenAI-compatible /v1/chat/completions endpoint for Open WebUI integration.

This translates between OpenAI chat format and the Maistro conductor pipeline.
Supports streaming SSE responses.

**The turn goes through the Conduit** (#142, ADR-082426-2192). It used to call
`maistro.agents.conductor.run_task` directly — the executor the `TaskRunner`
invokes, not an entry point — so it skipped the classifier, the intent registry,
the router and the session store. `Container.route_request` is the seam every
other chat turn in the process uses, and this door now uses it too.

That seam also owns the two things #150 had to build here for want of a
Container, so they are gone from this module rather than maintained beside it:

- **The Gate scan.** `CLAUDE.md`'s sixth decision is that all input is untrusted
  and the Warden scans at every trust boundary. `Conduit.route_request` scans
  first and answers a refusal as an ordinary OpenAI-shaped assistant message
  with `finish_reason="content_filter"` — a refusal is a normal answer, not a
  500 — and never reaches an agent.
- **The canonical Run.** One Run per turn (ADR-082326-c126), terminalized by
  `Container.route_request` however the turn ends, with `run_id` returned
  additively.

What stays here is what is genuinely this endpoint's: the OpenAI request and
response shapes, the SSE framing, the `X-Maistro-Run-Id` header, the
abandoned-stream cleanup, and the 502/504 sanitisation that keeps upstream
detail out of client-visible errors.

Two lifecycle notes that do not move.

`Container.route_request` closes the Run before returning, so by the time the
stream starts the Run is already terminal — a client that disconnects mid-stream
cannot leave one open. `_close_if_open` remains for the one case it cannot
cover: a client that disconnects at the very first `yield`, before
`route_request` is ever called, would otherwise strand a Run this module
admitted for the response header.

The Run is admitted here, not by `route_request`, for exactly that header: the
streaming branch has to name the Run before the first byte, and the seam cannot
hand it back until the turn is over. `route_request` is told about it so it does
not admit a second.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from maistro.agents.types import LLMProviderError
from maistro.constants import STREAM_CHUNK_SIZE
from maistro.runs.model import TERMINAL_RUN_STATUSES, Run, RunStatus
from maistro.security._types import AuthContext
from maistro_server.api.auth import RequireAuth
from maistro_server.api.principal import AuthenticatedPrincipal

logger = structlog.get_logger()

router = APIRouter(prefix="/v1", tags=["openai-compat"])

#: OpenAI's own finish_reason for a refusal, so a client that already handles
#: moderation needs no Maistro-specific case.
CONTENT_FILTER = "content_filter"

#: Response header naming a streamed turn's canonical Run. Listed in the app's
#: CORS `expose_headers`, without which a browser client is sent it and then
#: cannot read it.
RUN_ID_HEADER = "X-Maistro-Run-Id"

#: What a failed turn records on its Run — re-exported from core, which now
#: owns the mapping because `Container.route_request` is what writes it (#142).
#: Kept as names here so a test or a client reading this module still finds
#: them where they were.

#: The process's Container (#142). None before the lifespan installs one, and
#: in tests that exercise the response shapes without wiring a runtime.
_container: Any = None


def configure_container(container: Any) -> None:
    """Install the Container this endpoint routes through, from the lifespan.

    One object rather than the three #150 installed separately (a Gate, an
    admitter, a store). The Container carries all of them, already agreeing
    with each other and with the rest of the process — which is the point of
    building one, and why a Gate this module wired itself would now be the odd
    one out rather than the safe default it was.
    """
    global _container
    _container = container


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


def _auth_context(auth: AuthenticatedPrincipal | None) -> AuthContext | None:
    """The identity every strike path keys on.

    Built rather than passed through: handing the pipeline an object that
    merely happens to have a `user_id` would work until one of those paths
    reached for anything else. `Container.route_request` also refuses to run
    with `auth=None` while a permission table or strike tracker is armed, so
    this is what keeps an authenticated caller from tripping that refusal.
    """
    if auth is None:
        return None
    return AuthContext(user_id=auth.user_id, roles=auth.roles)


async def _admit_turn(
    request: ChatCompletionRequest,
    auth: AuthenticatedPrincipal | None,
) -> Run | None:
    """Admit this turn as a canonical Run, or None when none can be.

    Admitted here rather than left to `Container.route_request` because the
    streaming branch names the Run in a response header, and headers go out
    before the first byte — the seam cannot hand one back until the turn is
    over. The Run is then passed to `route_request`, which adopts it instead
    of admitting a second.

    Never refuses the turn. The chat path has no receipt to fall back on, so
    failing here would turn "this process cannot record the turn" into "this
    process cannot answer" — the same rule the seam itself follows.
    """
    if _container is None or _container.chat_admitter is None:
        return None
    try:
        run = await _container.chat_admitter.admit(
            [m.model_dump() for m in request.messages],
            actor_principal_id=auth.user_id if auth else None,
        )
        await _container.run_store.transition_run(run.run_id, RunStatus.QUEUED)
        running: Run = await _container.run_store.transition_run(run.run_id, RunStatus.RUNNING)
        return running
    except Exception:
        logger.exception("chat_completions_run_admission_failed")
        return None


async def _route(
    request: ChatCompletionRequest,
    auth: AuthenticatedPrincipal | None,
    run: Run | None,
) -> tuple[str, str]:
    """The turn's answer and its finish reason, from the Conduit.

    `route_request` scans, classifies, resolves an agent, and terminalizes the
    Run — including when the turn raises. So there is nothing to close here on
    either path, and a refusal arrives as an ordinary answer carrying
    `content_filter` rather than as a separate branch this module has to
    recognise.

    A turn that reaches here without a Container has nowhere to go. That is a
    wiring failure, not a request failure, so it raises and the caller maps it
    to a 500 like any other.
    """
    if _container is None:
        raise RuntimeError("chat completions received a request before a Container was wired")
    result = await _container.route_request(
        [m.model_dump() for m in request.messages],
        auth=_auth_context(auth),
        run=run,
    )
    return _answer_of(result)


def _answer_of(result: dict[str, Any]) -> tuple[str, str]:
    """The assistant text and finish reason inside an OpenAI-shaped result.

    Defensive at every hop rather than indexing through: the shape comes from
    whichever agent handled the turn, and a malformed one should degrade to an
    empty answer that a client can render, not to a `KeyError` that becomes a
    500 after the work already succeeded.
    """
    choices = result.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else {}
    if not isinstance(first, dict):
        return "", "stop"
    message = first.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    finish = first.get("finish_reason")
    return (
        content if isinstance(content, str) else "",
        finish if isinstance(finish, str) else "stop",
    )


def _text_chunks(chunk_id: str, model: str, text: str) -> Iterator[str]:
    """The SSE content chunks for one answer, one at a time.

    A generator, not a list: each frame carries `STREAM_CHUNK_SIZE`
    characters, so a long answer becomes thousands of separate Pydantic models
    and JSON strings. Building them all before yielding the first one holds
    many times the answer's own size in memory and delays the first frame for
    no reason.
    """
    for i in range(0, len(text), STREAM_CHUNK_SIZE):
        chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(content=text[i : i + STREAM_CHUNK_SIZE]))],
        )
        yield f"data: {chunk.model_dump_json()}\n\n"


#: What an abandoned turn's Run records. Cancelled, not failed: nothing went
#: wrong with the work, the reader left before it was done.
ABANDONED = "stream abandoned before the turn completed"

#: Strong references to in-flight cleanup writes, so the loop cannot collect
#: one mid-write. Discarded as each finishes.
_pending_closes: set[asyncio.Task[None]] = set()


async def _close_if_open(run: Run) -> None:
    """Terminalize a Run nothing else closed.

    Idempotent by design: every ordinary path closes its own Run, so this reads
    the Run back and does nothing when it is already terminal.
    """
    if _container is None:
        return
    try:
        current = await _container.run_store.get_run(run.run_id)
        if current is None or current.status in TERMINAL_RUN_STATUSES:
            return
        await _container.run_store.transition_run(run.run_id, RunStatus.CANCELLED, error=ABANDONED)
    except Exception:
        logger.exception("chat_completions_abandoned_run_close_failed", run_id=run.run_id)


async def _stream_conductor_response(
    request: ChatCompletionRequest,
    auth: AuthenticatedPrincipal | None = None,
    run: Run | None = None,
) -> AsyncIterator[str]:
    """Stream the turn, and close its Run however the stream ends.

    The Run is RUNNING from before the generator starts — it is admitted in the
    route handler so the header can carry it — which means a client that
    disconnects at the very first `yield`, before the scan or the conductor
    runs, would strand it there forever. `ChatRunAdmitter` refuses to sweep a
    non-terminal Run, so repeated early disconnects would grow the store
    without bound as well as lying about a process that died.

    The cleanup is started as a task before being awaited, so it completes even
    when this frame is torn down by `GeneratorExit`, where awaiting is not
    allowed to suspend.
    """
    try:
        async for chunk in _stream_turn(request, auth, run):
            yield chunk
    finally:
        if run is not None:
            closing = asyncio.ensure_future(_close_if_open(run))
            _pending_closes.add(closing)
            closing.add_done_callback(_pending_closes.discard)
            with contextlib.suppress(BaseException):
                await asyncio.shield(closing)


async def _stream_turn(
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

    # The whole answer is computed and then chunked — the endpoint has always
    # worked this way, and routing through the Conduit does not change it. The
    # refusal path is no longer separate: a Gate block arrives as an ordinary
    # answer carrying `content_filter`, so it streams like any other.
    user_msg = _extract_user_message(request)

    try:
        response_text, finish_reason = await _route(request, auth, run)
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
        choices=[StreamChoice(delta=DeltaMessage(), finish_reason=finish_reason)],
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
            headers[RUN_ID_HEADER] = run.run_id
        return StreamingResponse(
            _stream_conductor_response(request, auth, run),
            media_type="text/event-stream",
            headers=headers,
        )

    # Non-streaming: route the turn and return the whole answer. A Gate block
    # needs no branch of its own — it arrives as an ordinary answer carrying
    # `content_filter`, which is what a moderation-aware client already reads.
    user_msg = _extract_user_message(request)

    try:
        response_text, finish_reason = await _route(request, auth, run)
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

    return _answer(request, response_text, run, finish_reason=finish_reason)


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
