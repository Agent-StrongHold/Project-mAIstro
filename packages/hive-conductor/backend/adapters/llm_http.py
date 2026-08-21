from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx
from models.schemas import ChatCompletionRequest

from maistro.http import shared_client


def stub_completion(req: ChatCompletionRequest) -> dict[str, Any]:
    from uuid import uuid4

    return {
        "id": str(uuid4()),
        "model": req.model,
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": (
                        "(stub) Set LITELLM_API_BASE (…/v1) and LITELLM_API_KEY to call your gateway "
                        "through the LLMPort adapter."
                    ),
                }
            }
        ],
    }


def _normalize_to_chat_completions(body: dict[str, Any]) -> dict[str, Any]:
    if "choices" in body:
        return body
    parts: list[str] = []
    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for c in item.get("content") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") in ("output_text", "input_text") and "text" in c:
                    parts.append(str(c["text"]))
                elif isinstance(c.get("text"), str):
                    parts.append(c["text"])
    text = "".join(parts).strip() or "(gateway returned /responses JSON without extractable text)"
    return {
        "id": str(body.get("id", "")),
        "model": str(body.get("model", "")),
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "_hive_protocol": "responses",
    }


def _responses_event_to_chunk(ev: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one OpenAI **Responses API** streaming event into the
    chat.completions-shaped chunk the rest of the pipeline consumes
    (``choices[].delta`` with ``content`` / ``reasoning_content``). Returns
    ``None`` for events we don't surface (item bookkeeping, etc.)."""
    t = ev.get("type", "")
    if t == "response.output_text.delta" and ev.get("delta"):
        return {"choices": [{"delta": {"content": ev["delta"]}, "finish_reason": None}]}
    if t in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta") and ev.get(
        "delta"
    ):
        return {"choices": [{"delta": {"reasoning_content": ev["delta"]}, "finish_reason": None}]}
    if t in ("response.completed", "response.output_text.done"):
        return {"choices": [{"delta": {}, "finish_reason": "stop"}]}
    return None


class StubLLMPort:
    async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]:
        return stub_completion(req)

    async def stream(self, req: ChatCompletionRequest) -> AsyncIterator[dict[str, Any]]:
        # Dev fallback: chunk the stub text word-by-word so local mode also "streams".
        text = stub_completion(req)["choices"][0]["message"]["content"]
        for word in text.split(" "):
            yield {"choices": [{"delta": {"content": word + " "}, "finish_reason": None}]}
        yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}


class HttpOpenAIProtocolLLM:
    """HTTP adapter: try OpenAI **Responses** (`POST …/v1/responses`) when useful, else **chat.completions**."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        variant: Literal["auto", "responses", "chat_completions"],
    ) -> None:
        base = base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = base + "/v1"
        self._base = base
        self._key = api_key
        self._variant = variant

    async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]:
        model = req.model
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

        async with shared_client(timeout=120.0) as client:
            if self._variant in ("auto", "responses") and not req.tools:
                r = await client.post(
                    f"{self._base}/responses",
                    headers=headers,
                    json={"model": model, "input": req.messages},
                )
                if r.is_success:
                    return _normalize_to_chat_completions(r.json())
                if self._variant == "responses":
                    r.raise_for_status()

            payload: dict[str, Any] = {
                "model": model,
                "messages": req.messages,
                "temperature": req.temperature,
                "stream": False,
            }
            if req.max_tokens is not None:
                payload["max_tokens"] = req.max_tokens
            if req.tools:
                payload["tools"] = req.tools
            r2 = await client.post(f"{self._base}/chat/completions", headers=headers, json=payload)
            r2.raise_for_status()
            return r2.json()

    async def stream(self, req: ChatCompletionRequest) -> AsyncIterator[dict[str, Any]]:
        """Token-by-token streaming, normalized to chat.completions-shaped chunks
        (``choices[].delta`` with ``content`` / ``reasoning_content`` / ``tool_calls``).

        Lane selection mirrors :meth:`complete`: tool-free requests under ``variant``
        auto/responses stream the **Responses API** (typed events normalized via
        :func:`_responses_event_to_chunk`); everything else — and an ``auto`` request
        whose Responses call fails — streams chat.completions.
        """
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

        if self._variant in ("auto", "responses") and not req.tools:
            async with (
                shared_client(timeout=120.0) as client,
                client.stream(
                    "POST",
                    f"{self._base}/responses",
                    headers=headers,
                    json={"model": req.model, "input": req.messages, "stream": True},
                ) as r,
            ):
                if r.is_success:
                    async for ev in self._aiter_sse_json(r):
                        chunk = _responses_event_to_chunk(ev)
                        if chunk is not None:
                            yield chunk
                    return
                if self._variant == "responses":
                    await r.aread()
                    r.raise_for_status()
                    # variant == "auto": fall through to chat.completions below

        payload: dict[str, Any] = {
            "model": req.model,
            "messages": req.messages,
            "temperature": req.temperature,
            "stream": True,
        }
        if req.max_tokens is not None:
            payload["max_tokens"] = req.max_tokens
        if req.tools:
            payload["tools"] = req.tools

        async with (
            shared_client(timeout=120.0) as client,
            client.stream(
                "POST", f"{self._base}/chat/completions", headers=headers, json=payload
            ) as r,
        ):
            r.raise_for_status()
            async for chunk in self._aiter_sse_json(r):
                yield chunk

    @staticmethod
    async def _aiter_sse_json(r: httpx.Response) -> AsyncIterator[dict[str, Any]]:
        """Yield parsed JSON objects from an SSE ``data:`` stream (stops at ``[DONE]``)."""
        async for line in r.aiter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if data == "[DONE]":
                return
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue
