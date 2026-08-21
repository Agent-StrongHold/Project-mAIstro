"""HTTP-level tests for `HttpOpenAIProtocolLLM`.

This adapter is the process's hottest outbound path — every chat turn and every
graph node goes through it — and it had no coverage below the LLM-port
boundary. `test_chat_streaming.py` stubs `build_llm_port`, so it exercises the
callers and never reaches the httpx code here.

That gap is why two of the three sites this PR migrated to
`maistro.http.shared_client` were missed in the first pass and then survived a
full green suite: both `stream()` branches were written in the parenthesized
multi-line `async with` form, and nothing ran them.

These tests drive the adapter through a `MockTransport` installed with
`override_transport`, so the request construction, the SSE parsing and the
Responses→chat.completions fallback are all real; only the socket is not.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from adapters.llm_http import HttpOpenAIProtocolLLM
from models.schemas import ChatCompletionRequest

from maistro.http import get_shared_client, override_transport

pytestmark = pytest.mark.asyncio


def _sse(*payloads: str) -> bytes:
    return ("".join(f"data: {p}\n\n" for p in payloads) + "data: [DONE]\n\n").encode()


def _adapter(variant: str = "chat_completions") -> HttpOpenAIProtocolLLM:
    return HttpOpenAIProtocolLLM(
        base_url="https://gateway.invalid",
        api_key="k",
        variant=variant,  # type: ignore[arg-type]
    )


def _req(**kw: Any) -> ChatCompletionRequest:
    return ChatCompletionRequest(messages=[{"role": "user", "content": "hi"}], model="m", **kw)


class TestStreaming:
    """Both `stream()` branches — the two sites that had no coverage."""

    async def test_chat_completions_stream_yields_parsed_chunks(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                content=_sse(
                    '{"choices":[{"delta":{"content":"he"}}]}',
                    '{"choices":[{"delta":{"content":"llo"}}]}',
                ),
            )

        with override_transport(httpx.MockTransport(handler)):
            chunks = [c async for c in _adapter().stream(_req())]

        assert [c["choices"][0]["delta"]["content"] for c in chunks] == ["he", "llo"]
        assert str(seen[0].url) == "https://gateway.invalid/v1/chat/completions"
        assert seen[0].headers["Authorization"] == "Bearer k"

    async def test_responses_variant_streams_from_the_responses_endpoint(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(
                200, content=_sse('{"type":"response.output_text.delta","delta":"hi"}')
            )

        with override_transport(httpx.MockTransport(handler)):
            chunks = [c async for c in _adapter("responses").stream(_req())]

        assert seen == ["https://gateway.invalid/v1/responses"]
        assert chunks, "the Responses branch yielded nothing"

    async def test_auto_falls_back_to_chat_completions_when_responses_fails(self) -> None:
        """The `auto` fallback is the branch most likely to break silently: a
        4xx from /responses must not surface, it must retry the other endpoint."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            if request.url.path.endswith("/responses"):
                return httpx.Response(404, content=b"nope")
            return httpx.Response(200, content=_sse('{"choices":[{"delta":{"content":"x"}}]}'))

        with override_transport(httpx.MockTransport(handler)):
            chunks = [c async for c in _adapter("auto").stream(_req())]

        assert seen == ["/v1/responses", "/v1/chat/completions"]
        assert chunks[0]["choices"][0]["delta"]["content"] == "x"

    async def test_a_stream_error_is_not_swallowed(self) -> None:
        with (
            override_transport(httpx.MockTransport(lambda r: httpx.Response(500))),
            pytest.raises(httpx.HTTPStatusError),
        ):
            [c async for c in _adapter().stream(_req())]


class TestComplete:
    async def test_chat_completions_round_trip(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        with override_transport(httpx.MockTransport(handler)):
            out = await _adapter().complete(_req())

        assert out["choices"][0]["message"]["content"] == "ok"


class TestPooling:
    """The point of the migration: the client outlives the request.

    `shared_client` deliberately does not close on exit, so a streaming call —
    which holds the response open inside the same `async with` — must leave a
    reusable client behind rather than a closed one.
    """

    async def test_streaming_leaves_the_pooled_client_open_and_reused(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=_sse('{"choices":[{"delta":{"content":"a"}}]}'))

        with override_transport(httpx.MockTransport(handler)):
            before = get_shared_client(timeout=120.0)
            [c async for c in _adapter().stream(_req())]
            after = get_shared_client(timeout=120.0)

            assert after is before, "the streaming path replaced the pooled client"
            assert not after.is_closed, "exiting the stream closed the shared client"

    async def test_complete_and_stream_share_one_client(self) -> None:
        """Both use `timeout=120.0`, so they must land in the same pool bucket —
        otherwise the migration doubles the connection pools instead of
        collapsing them."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/chat/completions") and b'"stream": true' in (
                request.content or b""
            ):
                return httpx.Response(200, content=_sse('{"choices":[{"delta":{}}]}'))
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        with override_transport(httpx.MockTransport(handler)):
            await _adapter().complete(_req())
            first = get_shared_client(timeout=120.0)
            [c async for c in _adapter().stream(_req())]
            assert get_shared_client(timeout=120.0) is first
