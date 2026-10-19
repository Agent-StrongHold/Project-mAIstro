"""Tests for BuildersLearningStrategy after #847 retired its authored effects.

The strategy used to invoke a raw ``tool_executor`` callback itself with
``shell``/``github`` commands (recon, failure analysis, ruff/mypy/pytest
diagnostics) before any allowlist or contract admission -- and the gathered
context was never consumed by the downstream ReAct loop. These tests pin the
retirement: even when a caller supplies a perfectly capable executor, the
strategy performs no tool effects of its own.
"""

from __future__ import annotations

from typing import Any

from maistro.agents.strategies.builders_learning import BuildersLearningStrategy
from maistro.testing.faux_provider import FauxProvider, FauxResponse


class _InstrumentedExecutor:
    """Records every call; the #847 bypass would show up here."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, name: str, args: dict[str, Any]) -> str:
        self.calls.append((name, args))
        return "should never be reached"


def _messages() -> list[dict[str, Any]]:
    return [{"role": "user", "content": "fix the bug"}]


async def test_reason_unknown_worker_falls_back_to_react() -> None:
    provider = FauxProvider(default_response=FauxResponse(content="plain react response"))
    strategy = BuildersLearningStrategy(max_rounds=2)

    result = await strategy.reason(_messages(), "m", provider)

    assert result.response == "plain react response"
    assert result.done is True


async def test_reason_worker_unknown_string_falls_back_to_react() -> None:
    provider = FauxProvider(default_response=FauxResponse(content="react fallback"))
    strategy = BuildersLearningStrategy(max_rounds=2)

    result = await strategy.reason(_messages(), "m", provider, worker="someone_else")

    assert result.response == "react fallback"


async def test_frank_worker_performs_no_tool_effects_even_with_executor() -> None:
    """#847: the Frank recon bypass is retired, not merely piped through."""
    executor = _InstrumentedExecutor()
    provider = FauxProvider(default_response=FauxResponse(content="frank's plan"))
    strategy = BuildersLearningStrategy(max_rounds=2)

    result = await strategy.reason(
        _messages(), "m", provider, worker="frank", tool_executor=executor
    )

    assert result.response == "frank's plan"
    assert result.done is True
    assert executor.calls == []


async def test_mason_worker_performs_no_tool_effects_even_with_executor() -> None:
    """#847: the Mason diagnostics bypass is retired, not merely piped through."""
    executor = _InstrumentedExecutor()
    provider = FauxProvider(default_response=FauxResponse(content="mason built it"))
    strategy = BuildersLearningStrategy(max_rounds=2)

    result = await strategy.reason(
        _messages(), "m", provider, worker="mason", tool_executor=executor
    )

    assert result.response == "mason built it"
    assert result.done is True
    assert executor.calls == []


async def test_frank_worker_still_delegates_model_selected_tools_to_react() -> None:
    """Model-selected tool traffic still flows through the governed ReAct loop."""
    executor = _InstrumentedExecutor()
    provider = FauxProvider()
    provider.seed_tool_call("read_file", {"path": "a.py"})
    provider.seed(FauxResponse(content="done"))
    strategy = BuildersLearningStrategy(max_rounds=2)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "test tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    result = await strategy.reason(
        _messages(),
        "m",
        provider,
        worker="frank",
        tools=tools,
        tool_executor=executor,
        allowed_tools=frozenset({"read_file"}),
        security_pipeline=True,
    )

    assert result.response == "done"
    # The executor saw exactly the model-selected call, nothing else.
    assert executor.calls == [("read_file", {"path": "a.py"})]


async def test_mason_worker_ignores_frank_diagnostic_and_runs_react() -> None:
    provider = FauxProvider(default_response=FauxResponse(content="mason fixed it"))
    strategy = BuildersLearningStrategy(max_rounds=2)

    result = await strategy.reason(
        _messages(),
        "m",
        provider,
        worker="mason",
        frank_diagnostic={"existing_code": ["a.py"]},
    )

    assert result.response == "mason fixed it"


def test_init_sets_defaults() -> None:
    strategy = BuildersLearningStrategy()

    assert strategy.max_rounds == 10
    assert strategy.force_tool_first is False
    assert isinstance(strategy._react, object)


def test_strategy_has_no_effect_performing_helpers() -> None:
    """#847: the raw recon/diagnostics helpers must not silently return."""
    import inspect

    from maistro.agents.strategies import builders_learning

    source = inspect.getsource(builders_learning)
    for helper in ("_check_repository_state", "_analyze_failure_patterns", "_run_pr_diagnostics"):
        assert helper not in source, f"retired helper {helper} reappeared"
    # No strategy-authored shell/github dispatch of any shape.
    assert "tool_executor(" not in source
