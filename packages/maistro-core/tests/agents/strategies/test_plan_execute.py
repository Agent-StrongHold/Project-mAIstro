"""Tests for PlanExecuteStrategy (stub planner -> single LLM call)."""

from __future__ import annotations

from typing import Any

from maistro.agents.strategies.plan_execute import PlanExecuteStrategy
from maistro.testing.faux_provider import FauxProvider, FauxResponse


async def test_reason_returns_llm_content_as_response() -> None:
    provider = FauxProvider(default_response=FauxResponse(content="1. Do X\n2. Do Y"))
    strategy = PlanExecuteStrategy()
    messages = [{"role": "user", "content": "build a widget"}]

    result = await strategy.reason(messages, "test-model", provider)

    assert result.response == "1. Do X\n2. Do Y"
    assert result.done is True


async def test_reason_prepends_system_plan_prompt_with_max_subtasks() -> None:
    provider = FauxProvider(default_response=FauxResponse(content="plan"))
    strategy = PlanExecuteStrategy(max_subtasks=5)
    messages: list[dict[str, Any]] = [{"role": "user", "content": "build a widget"}]

    await strategy.reason(messages, "test-model", provider)

    sent_messages = provider.last_messages()
    assert sent_messages is not None
    assert sent_messages[0]["role"] == "system"
    assert "max 5" in sent_messages[0]["content"]
    assert sent_messages[1] == {"role": "user", "content": "build a widget"}


async def test_reason_default_max_subtasks_is_ten() -> None:
    provider = FauxProvider(default_response=FauxResponse(content="plan"))
    strategy = PlanExecuteStrategy()

    await strategy.reason([{"role": "user", "content": "x"}], "test-model", provider)

    sent_messages = provider.last_messages()
    assert sent_messages is not None
    assert "max 10" in sent_messages[0]["content"]


async def test_reason_missing_choices_key_returns_empty_content() -> None:
    """response.get("choices", [{}])[0] only guards a *missing* "choices" key.

    NOTE: if "choices" is present but an empty list (e.g. {"choices": []}),
    .get() returns [] (the default is only used when the key is absent), and
    [0] raises IndexError -- see genuine bug noted in the final report
    (plan_execute.py:36). This test exercises the actually-guarded case: the
    key is absent entirely.
    """

    class _MissingChoicesProvider:
        async def complete(self, messages: list[dict[str, Any]], model: str) -> dict[str, Any]:
            return {}

    strategy = PlanExecuteStrategy()

    result = await strategy.reason(
        [{"role": "user", "content": "x"}], "m", _MissingChoicesProvider()
    )

    assert result.response == ""
    assert result.done is True
