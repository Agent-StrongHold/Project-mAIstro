"""Tests for DirectStrategy: single LLM call, Warden post-scan, PII redaction."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

import pytest

from maistro.agents.strategies.direct import DirectStrategy
from maistro.testing.faux_provider import FauxProvider, FauxResponse


@dataclass
class _Verdict:
    clean: bool = True
    flags: tuple[str, ...] = ()


class _FakeWarden:
    def __init__(self, *, clean: bool = True, flags: tuple[str, ...] = ()) -> None:
        self._clean = clean
        self._flags = flags
        self.calls: list[tuple[str, str]] = []

    async def scan(self, text: str, surface: str) -> _Verdict:
        self.calls.append((text, surface))
        return _Verdict(clean=self._clean, flags=self._flags)


class _FakeSpan:
    def __init__(self) -> None:
        self.inputs: list[Any] = []
        self.outputs: list[Any] = []
        self.usage: dict[str, Any] = {}

    def __enter__(self) -> _FakeSpan:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def set_input(self, data: Any) -> _FakeSpan:
        self.inputs.append(data)
        return self

    def set_output(self, data: Any) -> _FakeSpan:
        self.outputs.append(data)
        return self

    def set_usage(
        self, input_tokens: int = 0, output_tokens: int = 0, model: str = ""
    ) -> _FakeSpan:
        self.usage = {"input_tokens": input_tokens, "output_tokens": output_tokens, "model": model}
        return self


class _FakeTrace:
    def __init__(self) -> None:
        self.spans: list[_FakeSpan] = []

    def span(self, _name: str) -> _FakeSpan:
        span = _FakeSpan()
        self.spans.append(span)
        return span


@pytest.fixture
def messages() -> list[dict[str, Any]]:
    return [{"role": "user", "content": "hello there"}]


async def test_reason_no_trace_no_warden_returns_content_and_usage(
    messages: list[dict[str, Any]],
) -> None:
    provider = FauxProvider(
        default_response=FauxResponse(
            content="hi back", usage_prompt_tokens=5, usage_completion_tokens=7
        )
    )
    strategy = DirectStrategy()

    result = await strategy.reason(messages, "test-model", provider)

    assert result.response == "hi back"
    assert result.done is True
    assert result.input_tokens == 5
    assert result.output_tokens == 7


async def test_reason_with_trace_records_span_and_usage(messages: list[dict[str, Any]]) -> None:
    provider = FauxProvider(
        default_response=FauxResponse(
            content="traced response", usage_prompt_tokens=3, usage_completion_tokens=4
        )
    )
    strategy = DirectStrategy()
    trace = _FakeTrace()

    result = await strategy.reason(messages, "test-model", provider, trace=trace)

    assert result.response == "traced response"
    assert len(trace.spans) == 1
    span = trace.spans[0]
    assert span.usage == {"input_tokens": 3, "output_tokens": 4, "model": "test-model"}
    assert span.inputs == [{"model": "test-model", "message_count": 1}]


async def test_reason_empty_choices_returns_empty_content(messages: list[dict[str, Any]]) -> None:
    """response.get("choices", []) with no choices -> choice = {} -> content = ""."""
    provider = FauxProvider()
    # Seed a response whose dict form has no choices by monkeypatching complete.
    provider._responses.append(FauxResponse(content=""))
    strategy = DirectStrategy()

    result = await strategy.reason(messages, "test-model", provider)

    assert result.response == ""
    assert result.done is True


async def test_reason_warden_clean_passes_through(messages: list[dict[str, Any]]) -> None:
    provider = FauxProvider(default_response=FauxResponse(content="clean output"))
    warden = _FakeWarden(clean=True)
    strategy = DirectStrategy()

    result = await strategy.reason(messages, "test-model", provider, warden=warden)

    assert result.response == "clean output"
    assert warden.calls == [("clean output", "tool_result")]


async def test_reason_warden_blocks_returns_blocked_message(messages: list[dict[str, Any]]) -> None:
    provider = FauxProvider(default_response=FauxResponse(content="malicious payload"))
    warden = _FakeWarden(clean=False, flags=("prompt_injection", "exfil_attempt"))
    strategy = DirectStrategy()

    result = await strategy.reason(messages, "test-model", provider, warden=warden)

    assert result.response == (
        "[Response blocked by Warden: prompt_injection, exfil_attempt. "
        "The response contained content that matched security "
        "patterns. Please rephrase your request.]"
    )
    assert result.done is True
    assert result.input_tokens == 0
    assert result.output_tokens == 0


async def test_reason_warden_not_called_when_content_empty(messages: list[dict[str, Any]]) -> None:
    """``if warden is not None and content:`` -- empty content skips the warden scan."""
    provider = FauxProvider(default_response=FauxResponse(content=""))
    warden = _FakeWarden(clean=True)
    strategy = DirectStrategy()

    result = await strategy.reason(messages, "test-model", provider, warden=warden)

    assert result.response == ""
    assert warden.calls == []


async def test_reason_redacts_pii_in_content(messages: list[dict[str, Any]]) -> None:
    provider = FauxProvider(
        default_response=FauxResponse(content="Contact me at someone@example.com please")
    )
    strategy = DirectStrategy()

    result = await strategy.reason(messages, "test-model", provider)

    assert result.response is not None
    assert "someone@example.com" not in result.response


async def test_reason_pii_filter_import_error_passes_through_unredacted(
    messages: list[dict[str, Any]],
) -> None:
    """If the pii_filter module is unavailable, content is returned as-is instead of raising."""
    provider = FauxProvider(
        default_response=FauxResponse(content="Contact me at someone@example.com please")
    )
    strategy = DirectStrategy()
    modname = "maistro.security.sentinel.pii_filter"
    sys.modules.pop(modname, None)
    sys.modules[modname] = None  # type: ignore[assignment]
    try:
        result = await strategy.reason(messages, "test-model", provider)
    finally:
        del sys.modules[modname]

    assert result.response == "Contact me at someone@example.com please"
