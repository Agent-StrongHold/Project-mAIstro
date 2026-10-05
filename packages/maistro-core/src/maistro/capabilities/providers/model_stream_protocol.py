"""Chat-completion SSE framing and result assembly; no HTTP or effect authority."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any


class ModelStreamProtocolError(RuntimeError):
    """The Provider stream did not prove a complete chat-completion outcome."""


async def sse_data(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """Join data fields by SSE event; EOF is not an implicit terminal event."""
    fields: list[str] = []
    async for line in lines:
        if not line:
            if fields:
                yield "\n".join(fields)
                fields.clear()
        elif line.startswith("data:"):
            fields.append(line[5:].removeprefix(" "))
    if fields:
        raise ModelStreamProtocolError("model stream ended inside an SSE event")


def parse_chunk(data: str) -> dict[str, Any]:
    try:
        chunk = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ModelStreamProtocolError("model stream returned invalid JSON") from exc
    if not isinstance(chunk, dict):
        raise ModelStreamProtocolError("model stream returned a non-object event")
    if "error" in chunk:
        # Never persist a provider's arbitrary error payload (it can contain secrets).
        raise ModelStreamProtocolError("model gateway reported a streaming error")
    return chunk


def _index(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ModelStreamProtocolError("model stream returned an invalid choice/tool index")
    return value


def _merge_fields(target: dict[str, Any], fragment: dict[str, Any]) -> None:
    """Accumulate text and function fragments without concatenating metadata."""
    for key, value in fragment.items():
        if value is None or key == "index":
            continue
        _merge_value(target, key, value)


def _merge_value(target: dict[str, Any], key: str, value: Any) -> None:
    if key in {"id", "role", "type"}:
        _merge_metadata(target, key, value)
        return
    if key in {"content", "refusal", "reasoning_content", "name", "arguments"} and not isinstance(
        value, str
    ):
        raise ModelStreamProtocolError("model stream returned a non-text fragment")
    if isinstance(value, dict):
        nested = target.setdefault(key, {})
        if not isinstance(nested, dict):
            raise ModelStreamProtocolError("model stream changed a fragment's type")
        _merge_fields(nested, value)
    elif isinstance(value, str):
        prior = target.get(key, "")
        if not isinstance(prior, str):
            raise ModelStreamProtocolError("model stream changed a text fragment's type")
        target[key] = prior + value
    else:
        target[key] = value


def _merge_metadata(target: dict[str, Any], key: str, value: Any) -> None:
    if not isinstance(value, str):
        raise ModelStreamProtocolError("model stream returned non-text metadata")
    prior = target.get(key, "")
    if prior and value and prior != value:
        raise ModelStreamProtocolError("model stream changed fragment metadata")
    target[key] = prior or value


class ChatStreamAccumulator:
    """Persistable result of the raw chunks, with explicit completion evidence."""

    def __init__(self) -> None:
        self.body: dict[str, Any] = {}
        self.choices: dict[int, dict[str, Any]] = {}
        self.tools: dict[int, dict[int, dict[str, Any]]] = {}

    def add(self, chunk: dict[str, Any]) -> None:
        for key in ("id", "model", "created", "system_fingerprint", "service_tier"):
            if key in chunk:
                self.body[key] = chunk[key]
        usage = chunk.get("usage")
        if isinstance(usage, dict) and all(
            isinstance(usage.get(key), int) and not isinstance(usage[key], bool) and usage[key] >= 0
            for key in ("prompt_tokens", "completion_tokens")
        ):
            self.body["usage"] = dict(usage)
        choices = chunk.get("choices")
        if not isinstance(choices, list):
            raise ModelStreamProtocolError("model stream omitted its choices array")
        for choice in choices:
            self._add_choice(choice)

    def _add_choice(self, choice: Any) -> None:
        if not isinstance(choice, dict) or not isinstance(choice.get("delta"), dict):
            raise ModelStreamProtocolError("model stream returned an invalid choice")
        index = _index(choice.get("index"))
        result = self.choices.setdefault(
            index, {"index": index, "message": {"role": "assistant"}, "finish_reason": None}
        )
        if result["finish_reason"] is not None:
            raise ModelStreamProtocolError("model stream continued a finished choice")
        delta = dict(choice["delta"])
        fragments = delta.pop("tool_calls", None)
        _merge_fields(result["message"], delta)
        if fragments is not None:
            self._add_tools(index, fragments)
        finish = choice.get("finish_reason")
        if finish is not None:
            if not isinstance(finish, str) or not finish:
                raise ModelStreamProtocolError("model stream returned an invalid finish reason")
            result["finish_reason"] = finish

    def _add_tools(self, choice_index: int, fragments: Any) -> None:
        if not isinstance(fragments, list):
            raise ModelStreamProtocolError("model stream returned invalid tool fragments")
        tools = self.tools.setdefault(choice_index, {})
        for fragment in fragments:
            if not isinstance(fragment, dict):
                raise ModelStreamProtocolError("model stream returned an invalid tool fragment")
            tool = tools.setdefault(_index(fragment.get("index")), {})
            _merge_fields(tool, fragment)

    def finish(self) -> dict[str, Any]:
        if not self.choices or any(
            choice["finish_reason"] is None for choice in self.choices.values()
        ):
            raise ModelStreamProtocolError("model stream ended without finished choices")
        for index, tools in self.tools.items():
            self.choices[index]["message"]["tool_calls"] = [tools[i] for i in sorted(tools)]
        return {**self.body, "choices": [self.choices[i] for i in sorted(self.choices)]}
