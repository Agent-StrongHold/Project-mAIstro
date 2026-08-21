"""Coverage for maistro.security.warden.llm_classifier (Layer 3 LLM tool-result classification)."""

from __future__ import annotations

from typing import Any

from maistro.security.warden.llm_classifier import (
    _FEW_SHOT_EXAMPLES,
    _build_classification_prompt,
    classify_tool_result,
)


class _StubLLMClient:
    def __init__(self, response: dict[str, Any] | None = None, exc: Exception | None = None):
        self._response = response
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    async def complete(self, messages: list[dict[str, str]], model: str) -> dict[str, Any]:
        self.calls.append({"messages": messages, "model": model})
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def _resp(content: str, total_tokens: int | None = None) -> dict[str, Any]:
    resp: dict[str, Any] = {"choices": [{"message": {"content": content}}]}
    if total_tokens is not None:
        resp["usage"] = {"total_tokens": total_tokens}
    return resp


# ─── _build_classification_prompt ──────────────────────────────────────────────


def test_prompt_structure_has_system_then_fewshot_pairs_then_final_user():
    messages = _build_classification_prompt("some tool result text")
    assert len(messages) == 1 + len(_FEW_SHOT_EXAMPLES) * 2 + 1
    assert messages[0]["role"] == "system"
    for i, ex in enumerate(_FEW_SHOT_EXAMPLES):
        user_msg = messages[1 + i * 2]
        assistant_msg = messages[2 + i * 2]
        assert user_msg["role"] == "user"
        assert ex["text"] in user_msg["content"]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["content"] == ex["label"]
    final = messages[-1]
    assert final["role"] == "user"
    assert "some tool result text" in final["content"]


def test_prompt_truncates_text_to_2000_chars():
    long_text = "y" * 3000
    messages = _build_classification_prompt(long_text)
    final_content = messages[-1]["content"]
    assert "y" * 2000 in final_content
    assert "y" * 2001 not in final_content


# ─── classify_tool_result ───────────────────────────────────────────────────────


async def test_response_containing_suspicious_word_is_classified_suspicious():
    client = _StubLLMClient(_resp("suspicious"))
    result = await classify_tool_result("text", client)
    assert result["label"] == "suspicious"


async def test_response_not_containing_suspicious_defaults_to_safe():
    client = _StubLLMClient(_resp("totally unexpected garbage output"))
    result = await classify_tool_result("text", client)
    assert result["label"] == "safe"


async def test_safe_label_response_is_classified_safe():
    client = _StubLLMClient(_resp("safe"))
    result = await classify_tool_result("text", client)
    assert result["label"] == "safe"


async def test_usage_tokens_passed_through():
    client = _StubLLMClient(_resp("safe", total_tokens=512))
    result = await classify_tool_result("text", client)
    assert result["tokens"] == 512


async def test_missing_usage_key_defaults_tokens_to_zero():
    client = _StubLLMClient(_resp("safe"))
    result = await classify_tool_result("text", client)
    assert result["tokens"] == 0


async def test_missing_choices_defaults_content_empty_and_safe():
    client = _StubLLMClient({})
    result = await classify_tool_result("text", client)
    assert result["label"] == "safe"
    assert result["tokens"] == 0


async def test_exception_from_llm_client_is_swallowed_and_inconclusive():
    client = _StubLLMClient(exc=RuntimeError("provider down"))
    result = await classify_tool_result("text", client, model="fast-model")
    assert result == {
        "label": "inconclusive",
        "model": "fast-model",
        "tokens": 0,
        "error": "classification_failed",
    }


async def test_model_param_passed_through_to_client_and_result():
    client = _StubLLMClient(_resp("safe"))
    result = await classify_tool_result("text", client, model="fast-model")
    assert client.calls[0]["model"] == "fast-model"
    assert result["model"] == "fast-model"


async def test_default_model_is_auto():
    client = _StubLLMClient(_resp("safe"))
    result = await classify_tool_result("text", client)
    assert result["model"] == "auto"
