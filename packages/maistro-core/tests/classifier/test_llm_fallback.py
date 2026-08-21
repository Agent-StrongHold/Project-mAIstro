"""Coverage for maistro.classifier.llm_fallback.llm_classify (was 0%)."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.classifier.llm_fallback import _VALID_CATEGORIES, llm_classify


class _StubLLMClient:
    def __init__(self, response: dict[str, Any] | None = None, exc: Exception | None = None):
        self._response = response
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def _resp(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


async def test_returns_category_when_first_word_is_exact_match():
    client = _StubLLMClient(_resp("code"))
    result = await llm_classify("write me a script", client)
    assert result == "code"


async def test_strips_whitespace_and_lowercases_response():
    client = _StubLLMClient(_resp("  Code\n"))
    result = await llm_classify("write me a script", client)
    assert result == "code"


async def test_falls_back_to_substring_match_when_first_word_not_exact():
    client = _StubLLMClient(_resp("the category is creative"))
    result = await llm_classify("write me a poem", client)
    assert result == "creative"


async def test_returns_none_when_no_valid_category_found_anywhere():
    client = _StubLLMClient(_resp("I cannot classify this message"))
    result = await llm_classify("???", client)
    assert result is None


async def test_returns_none_on_empty_content():
    client = _StubLLMClient(_resp(""))
    result = await llm_classify("hello", client)
    assert result is None


async def test_returns_none_on_whitespace_only_content():
    client = _StubLLMClient(_resp("   "))
    result = await llm_classify("hello", client)
    assert result is None


async def test_returns_none_and_swallows_exception_from_llm_client():
    client = _StubLLMClient(exc=RuntimeError("provider down"))
    result = await llm_classify("hello", client)
    assert result is None


async def test_malformed_response_missing_choices_returns_none():
    client = _StubLLMClient({})
    result = await llm_classify("hello", client)
    assert result is None


async def test_prompt_truncates_user_text_to_200_chars():
    client = _StubLLMClient(_resp("chat"))
    long_text = "x" * 500
    await llm_classify(long_text, client)

    sent_prompt = client.calls[0]["messages"][0]["content"]
    # Only the first 200 chars of user_text should appear in the prompt.
    assert "x" * 200 in sent_prompt
    assert "x" * 201 not in sent_prompt


async def test_passes_through_model_and_fixed_sampling_params():
    client = _StubLLMClient(_resp("chat"))
    await llm_classify("hello", client, model="fast-model")

    call = client.calls[0]
    assert call["model"] == "fast-model"
    assert call["max_tokens"] == 10
    assert call["temperature"] == 0.0


async def test_default_model_is_auto():
    client = _StubLLMClient(_resp("chat"))
    await llm_classify("hello", client)
    assert client.calls[0]["model"] == "auto"


@pytest.mark.parametrize("category", sorted(_VALID_CATEGORIES))
async def test_every_valid_category_is_recognized_as_first_word(category: str) -> None:
    client = _StubLLMClient(_resp(category))
    result = await llm_classify("anything", client)
    assert result == category
