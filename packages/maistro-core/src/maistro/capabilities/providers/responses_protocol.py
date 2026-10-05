"""Tool-free Responses normalization, without transport or effect authority.

Native schemas: https://developers.openai.com/api/reference/resources/responses/
streaming-events and OpenAI's generated ResponseReasoningItem/ResponseOutputRefusal
in https://github.com/openai/openai-node/blob/main/src/resources/responses/responses.ts.
"""

from __future__ import annotations

from typing import Any

from maistro.capabilities.providers.model_stream_protocol import ModelStreamProtocolError

_FIELDS = ("text", "refusal", "reasoning", "summary")
_EVENT_FIELDS = {
    "response.output_text.delta": "text",
    "response.refusal.delta": "refusal",
    "response.reasoning_summary_text.delta": "summary",
    "response.reasoning_text.delta": "reasoning",
}


def _text_parts(parts: Any, kind: str) -> str:
    if not isinstance(parts, list):
        raise ModelStreamProtocolError("Responses content is not an array")
    text = []
    for part in parts:
        if not isinstance(part, dict) or part.get("type") != kind:
            raise ModelStreamProtocolError("Responses returned invalid text content")
        value = part.get("text")
        if not isinstance(value, str):
            raise ModelStreamProtocolError("Responses returned invalid text content")
        text.append(value)
    return "".join(text)


def _message_fields(parts: Any) -> dict[str, str]:
    if not isinstance(parts, list):
        raise ModelStreamProtocolError("Responses message content is not an array")
    fields = {"text": "", "refusal": ""}
    for part in parts:
        if not isinstance(part, dict) or part.get("type") not in {"output_text", "refusal"}:
            raise ModelStreamProtocolError("Responses returned unsupported message content")
        key = "refusal" if part["type"] == "refusal" else "text"
        value = part.get(key)
        if not isinstance(value, str):
            raise ModelStreamProtocolError("Responses returned invalid message text")
        fields[key] += value
    return fields


def _item_fields(item: Any) -> dict[str, str]:
    if not isinstance(item, dict) or item.get("status") not in {None, "completed"}:
        raise ModelStreamProtocolError("Responses returned an invalid or unfinished output item")
    if item.get("type") == "message":
        return _message_fields(item.get("content"))
    if item.get("type") == "reasoning":
        content = item.get("content")
        return {
            "summary": _text_parts(item.get("summary", []), "summary_text"),
            "reasoning": _text_parts([] if content is None else content, "reasoning_text"),
        }
    raise ModelStreamProtocolError("Responses returned unsupported output")


def _output_fields(output: list[Any]) -> dict[str, str]:
    fields = dict.fromkeys(_FIELDS, "")
    for item in output:
        for key, value in _item_fields(item).items():
            fields[key] += value
    return fields


def _message(output: list[Any]) -> dict[str, Any]:
    fields = _output_fields(output)
    # Refusal text remains visible to existing content-only consumers; the
    # separate refusal field preserves its meaning for consumers that inspect it.
    message: dict[str, Any] = {"role": "assistant", "content": fields["text"] + fields["refusal"]}
    if fields["refusal"]:
        message["refusal"] = fields["refusal"]
    reasoning = fields["reasoning"] + fields["summary"]
    if reasoning:
        message["reasoning_content"] = reasoning
    return message


def normalize_response(body: dict[str, Any]) -> dict[str, Any]:
    """Require whole-response completion, retaining only actual reported usage."""
    if (
        body.get("status") != "completed"
        or not isinstance(body.get("output"), list)
        or body.get("error") is not None
        or body.get("incomplete_details") is not None
    ):
        raise ModelStreamProtocolError("Responses did not prove a completed outcome")
    message = _message(body["output"])
    result: dict[str, Any] = {
        key: body[key] for key in ("id", "model", "created_at", "service_tier") if key in body
    }
    result["choices"] = [{"index": 0, "message": message, "finish_reason": "stop"}]
    usage = _usage(body.get("usage"))
    if usage is not None:
        result["usage"] = usage
    return result


def _usage(usage: Any) -> dict[str, Any] | None:
    if isinstance(usage, dict) and all(
        type(usage.get(key)) is int and usage[key] >= 0 for key in ("input_tokens", "output_tokens")
    ):
        return {
            **usage,
            "prompt_tokens": usage["input_tokens"],
            "completion_tokens": usage["output_tokens"],
        }
    return None


def response_text_format(format_: dict[str, object]) -> dict[str, object]:
    """Translate Chat's nested JSON-schema option to Responses' text format."""
    schema = format_.get("json_schema")
    if format_.get("type") == "json_schema" and isinstance(schema, dict):
        return {**schema, "type": "json_schema"}
    return dict(format_)


def _chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def _normalized_field(native: str) -> str:
    return "content" if native in {"text", "refusal"} else "reasoning_content"


class ResponsesStream:
    """Normalize deltas; only response.completed establishes success."""

    def __init__(self) -> None:
        self.result: dict[str, Any] | None = None
        self._seen = dict.fromkeys(_FIELDS, "")
        self._emitted = {"content": "", "reasoning_content": ""}

    def add(self, event: dict[str, Any]) -> dict[str, Any] | None:
        kind = event.get("type")
        if not isinstance(kind, str):
            raise ModelStreamProtocolError("Responses event omitted its type")
        if kind in {"error", "response.failed", "response.incomplete"}:
            raise ModelStreamProtocolError("Responses reported an unsuccessful outcome")
        if kind == "response.completed":
            return self._complete(event)
        native = _EVENT_FIELDS.get(kind)
        if native is None:
            return None
        delta = event.get("delta")
        if not isinstance(delta, str):
            raise ModelStreamProtocolError("Responses returned an invalid delta")
        self._seen[native] += delta
        field = _normalized_field(native)
        self._emitted[field] += delta
        output = {field: delta}
        if native == "refusal":
            output["refusal"] = delta
        return _chunk(output)

    def _complete(self, event: dict[str, Any]) -> dict[str, Any]:
        response = event.get("response")
        if not isinstance(response, dict):
            raise ModelStreamProtocolError("Responses completion omitted its result")
        result = normalize_response(response)
        delta = self._remaining(_output_fields(response["output"]))
        message = result["choices"][0]["message"]
        message.update({key: value for key, value in self._emitted.items() if value})
        self.result = result
        return {**{k: v for k, v in result.items() if k != "choices"}, **_chunk(delta, "stop")}

    def _remaining(self, final: dict[str, str]) -> dict[str, str]:
        """Validate separate native channels before combining normalized text."""
        delta: dict[str, str] = {}
        for native, seen in self._seen.items():
            if seen and final[native] != seen:
                raise ModelStreamProtocolError("Responses completion disagrees with its deltas")
            if final[native] and not seen:
                field = _normalized_field(native)
                delta[field] = delta.get(field, "") + final[native]
                self._emitted[field] += final[native]
                if native == "refusal":
                    delta["refusal"] = final[native]
        return delta
