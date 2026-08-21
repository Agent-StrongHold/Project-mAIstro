"""Opt-in Anthropic prompt caching: LiteLLMCallable marks the stable prefix
(the system message, which fronts tools+system in Anthropic's canonical order)
with an ephemeral cache_control breakpoint — but only when caching is enabled AND
the routed model is Anthropic-family. Every other model keeps the byte-identical
legacy payload, so the marker can never perturb a non-Anthropic genome."""

from __future__ import annotations

from typing import Any

import pytest

import maistro_bootstrap.builders.responses_callable as rc
from maistro_bootstrap.builders.responses_callable import (
    LiteLLMCallable,
    _is_anthropic_model,
    _mark_prefix_cache,
)


class _FakeResp:
    status_code = 200
    text = ""

    def json(self) -> dict[str, Any]:
        return {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }


def _capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("LITELLM_URL", "http://gw:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-test")
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, json: dict[str, Any], headers: Any, timeout: Any) -> _FakeResp:
        captured.update(json)
        return _FakeResp()

    monkeypatch.setattr(rc.httpx, "post", fake_post)
    return captured


_MESSAGES = [
    {"role": "system", "content": "You are a precise coding assistant."},
    {"role": "user", "content": "improve foo.py"},
]


def _system(body: dict[str, Any]) -> dict[str, Any]:
    return next(m for m in body["messages"] if m["role"] == "system")


# --- pure-function units -------------------------------------------------


def test_is_anthropic_model_matches_family() -> None:
    for name in ("claude-sonnet-4-6", "claude-haiku-4-5", "cloud-opus", "anthropic/claude-x"):
        assert _is_anthropic_model(name)
    for name in ("qwen2.5-coder", "openrouter/free", "gpt-oss-120b", "gemini-2.5-pro"):
        assert not _is_anthropic_model(name)


def test_mark_prefix_cache_promotes_system_to_cached_part() -> None:
    marked = _mark_prefix_cache(list(_MESSAGES))
    system = next(m for m in marked if m["role"] == "system")
    assert isinstance(system["content"], list)
    part = system["content"][0]
    assert part["text"] == "You are a precise coding assistant."
    assert part["cache_control"] == {"type": "ephemeral"}
    # Only the system message is touched; the user turn is untouched.
    assert marked[1] == _MESSAGES[1]


def test_mark_prefix_cache_marks_only_first_system() -> None:
    msgs = [
        {"role": "system", "content": "a"},
        {"role": "system", "content": "b"},
    ]
    marked = _mark_prefix_cache(msgs)
    assert isinstance(marked[0]["content"], list)  # first marked
    assert marked[1]["content"] == "b"  # second left as plain string


def test_mark_prefix_cache_noop_without_system() -> None:
    msgs = [{"role": "user", "content": "hi"}]
    assert _mark_prefix_cache(msgs) == msgs


# --- end-to-end payload gating ------------------------------------------


def test_cache_control_present_for_anthropic_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture(monkeypatch)
    LiteLLMCallable(model="claude-sonnet-4-6", prompt_cache=True)(list(_MESSAGES))
    system = _system(captured)
    assert isinstance(system["content"], list)
    assert system["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_no_cache_control_for_non_anthropic_even_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture(monkeypatch)
    LiteLLMCallable(model="qwen2.5-coder", prompt_cache=True)(list(_MESSAGES))
    # Non-Anthropic keeps the plain string content — byte-identical legacy payload.
    assert _system(captured)["content"] == "You are a precise coding assistant."


def test_no_cache_control_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture(monkeypatch)
    LiteLLMCallable(model="claude-sonnet-4-6", prompt_cache=False)(list(_MESSAGES))
    assert _system(captured)["content"] == "You are a precise coding assistant."


def test_default_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture(monkeypatch)
    LiteLLMCallable(model="claude-sonnet-4-6")(list(_MESSAGES))  # prompt_cache defaults False
    assert _system(captured)["content"] == "You are a precise coding assistant."
