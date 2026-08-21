from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


@dataclass
class ToolCallDef:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""


@dataclass
class FauxResponse:
    content: str = ""
    tool_calls: list[ToolCallDef] = field(default_factory=list)
    finish_reason: str = "stop"
    usage_prompt_tokens: int = 0
    usage_completion_tokens: int = 0
    model: str = "faux://test-model"
    latency_ms: float = 0.0
    error: Exception | None = None


def _make_openai_response(fr: FauxResponse) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": fr.content}
    if fr.tool_calls:
        message["tool_calls"] = [
            {
                "id": tc.call_id or f"call_{i}",
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for i, tc in enumerate(fr.tool_calls)
        ]
    return {
        "id": "faux-response",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": fr.model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": fr.finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": fr.usage_prompt_tokens,
            "completion_tokens": fr.usage_completion_tokens,
            "total_tokens": fr.usage_prompt_tokens + fr.usage_completion_tokens,
        },
    }


def _make_stream_chunk(fr: FauxResponse, token: str, is_last: bool = False) -> dict[str, Any]:
    delta: dict[str, Any] = {} if is_last else {"content": token}

    return {
        "id": "faux-stream",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": fr.model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": fr.finish_reason if is_last else None,
            }
        ],
    }


class FauxProvider:
    def __init__(
        self,
        responses: list[FauxResponse] | None = None,
        default_response: FauxResponse | None = None,
    ) -> None:
        if responses is not None:
            self._responses = list(responses)
        else:
            self._responses = []
        self._default = default_response or FauxResponse(
            content='{"summary": "faux plan", "subtasks": [], "estimated_files": []}',
            usage_prompt_tokens=10,
            usage_completion_tokens=20,
        )
        self._call_log: list[dict[str, Any]] = []
        self._index = 0

    @property
    def call_count(self) -> int:
        return len(self._call_log)

    @property
    def call_log(self) -> list[dict[str, Any]]:
        return list(self._call_log)

    def last_call(self) -> dict[str, Any] | None:
        return self._call_log[-1] if self._call_log else None

    def last_messages(self) -> list[dict[str, Any]] | None:
        entry = self.last_call()
        return entry["messages"] if entry else None

    def seed(self, *responses: FauxResponse) -> FauxProvider:
        self._responses.extend(responses)
        return self

    def seed_json(self, *objs: BaseModel | dict[str, Any]) -> FauxProvider:
        for obj in objs:
            data = obj.model_dump() if isinstance(obj, BaseModel) else obj
            self._responses.append(
                FauxResponse(
                    content=json.dumps(data),
                    usage_prompt_tokens=10,
                    usage_completion_tokens=max(1, len(json.dumps(data)) // 4),
                )
            )
        return self

    def seed_error(self, exc: Exception) -> FauxProvider:
        self._responses.append(FauxResponse(error=exc))
        return self

    def seed_tool_call(self, name: str, arguments: dict[str, Any] | None = None) -> FauxProvider:
        self._responses.append(
            FauxResponse(
                content="",
                tool_calls=[ToolCallDef(name=name, arguments=arguments or {})],
                finish_reason="tool_calls",
            )
        )
        return self

    def reset(self) -> None:
        self._call_log.clear()
        self._index = 0

    def _next_response(self) -> FauxResponse:
        if self._index < len(self._responses):
            resp = self._responses[self._index]
            self._index += 1
            return resp
        return self._default

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str = "faux://test-model",
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
        metadata: dict[str, Any] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        # Tolerate (and record) forward-compatible kwargs the graph node passes
        # through `llm_call`, e.g. `response_schema`. A test double must accept
        # the same call contract as the real provider rather than TypeError on
        # an unknown keyword.
        entry: dict[str, Any] = {
            "messages": messages,
            "model": model,
            "tools": tools,
            "tool_choice": tool_choice,
            "stream": stream,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "metadata": metadata,
            "extra": extra,
            "timestamp": time.monotonic(),
        }
        self._call_log.append(entry)

        resp = self._next_response()

        if resp.latency_ms > 0:
            await asyncio.sleep(resp.latency_ms / 1000.0)

        if resp.error is not None:
            raise resp.error

        return _make_openai_response(resp)

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str = "faux://test-model",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        entry: dict[str, Any] = {
            "messages": messages,
            "model": model,
            "stream": True,
            "timestamp": time.monotonic(),
            **kwargs,
        }
        self._call_log.append(entry)

        resp = self._next_response()

        if resp.error is not None:
            raise resp.error

        content = resp.content
        chunk_size = max(1, len(content) // 4) if content else 1

        for i in range(0, max(1, len(content)), chunk_size):
            token = content[i : i + chunk_size]
            chunk = _make_stream_chunk(resp, token)
            yield f"data: {json.dumps(chunk)}\n\n"
            if resp.latency_ms > 0:
                await asyncio.sleep(resp.latency_ms / 1000.0 / max(1, len(content) / chunk_size))

        final = _make_stream_chunk(resp, "", is_last=True)
        yield f"data: {json.dumps(final)}\n\n"
        yield "data: [DONE]\n\n"

    async def __call__(
        self,
        messages: list[dict[str, Any]],
        model: str = "faux://test-model",
        **kwargs: Any,
    ) -> str:
        resp_dict = await self.complete(messages, model, **kwargs)
        choice = resp_dict["choices"][0]
        content: str = choice["message"]["content"]
        return content


def plan_output(
    summary: str = "faux plan",
    subtasks: list[dict[str, str]] | None = None,
    estimated_files: list[str] | None = None,
) -> FauxResponse:
    data: dict[str, Any] = {
        "summary": summary,
        "subtasks": subtasks or [],
        "estimated_files": estimated_files or [],
    }
    return FauxResponse(
        content=json.dumps(data), usage_prompt_tokens=10, usage_completion_tokens=20
    )


def code_output(
    files_changed: list[str] | None = None,
    description: str = "faux implementation",
    tests_added: bool = True,
) -> FauxResponse:
    data: dict[str, Any] = {
        "files_changed": files_changed or ["main.py"],
        "description": description,
        "tests_added": tests_added,
    }
    return FauxResponse(
        content=json.dumps(data), usage_prompt_tokens=10, usage_completion_tokens=20
    )


def review_output(
    approved: bool = True,
    score: float = 8.0,
    issues: list[str] | None = None,
    suggestions: list[str] | None = None,
) -> FauxResponse:
    data: dict[str, Any] = {
        "approved": approved,
        "score": score,
        "issues": issues or [],
        "suggestions": suggestions or [],
    }
    return FauxResponse(
        content=json.dumps(data), usage_prompt_tokens=10, usage_completion_tokens=20
    )


def scout_output(
    relevant_files: list[str] | None = None,
    patterns: str = "faux patterns",
    summary: str = "faux scout summary",
) -> FauxResponse:
    data: dict[str, Any] = {
        "relevant_files": relevant_files or ["main.py"],
        "patterns": patterns,
        "dependency_map": {},
        "similar_implementations": [],
        "summary": summary,
    }
    return FauxResponse(
        content=json.dumps(data), usage_prompt_tokens=10, usage_completion_tokens=20
    )
