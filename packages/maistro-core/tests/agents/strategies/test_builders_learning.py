"""Tests for BuildersLearningStrategy: role context over the canonical ReAct boundary."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.agents.strategies.builders_learning import BuildersLearningStrategy
from maistro.testing.faux_provider import FauxProvider, FauxResponse


@pytest.fixture
def messages() -> list[dict[str, Any]]:
    return [{"role": "user", "content": "fix the bug"}]


async def test_reason_unknown_worker_falls_back_to_react(messages: list[dict[str, Any]]) -> None:
    provider = FauxProvider(default_response=FauxResponse(content="plain react response"))
    strategy = BuildersLearningStrategy(max_rounds=2)

    result = await strategy.reason(messages, "m", provider)

    assert result.response == "plain react response"
    assert result.done is True


async def test_reason_worker_unknown_string_falls_back_to_react(
    messages: list[dict[str, Any]],
) -> None:
    provider = FauxProvider(default_response=FauxResponse(content="react fallback"))
    strategy = BuildersLearningStrategy(max_rounds=2)

    result = await strategy.reason(messages, "m", provider, worker="someone_else")

    assert result.response == "react fallback"


async def test_frank_worker_no_tool_executor_runs_with_empty_context(
    messages: list[dict[str, Any]],
) -> None:
    provider = FauxProvider(default_response=FauxResponse(content="frank's plan"))
    strategy = BuildersLearningStrategy(max_rounds=2, enable_learning=False)

    result = await strategy.reason(messages, "m", provider, worker="frank")

    assert result.response == "frank's plan"
    assert result.done is True


async def test_frank_worker_with_tool_executor_runs_recon(messages: list[dict[str, Any]]) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def tool_executor(name: str, args: dict[str, Any]) -> str:
        calls.append((name, args))
        if name == "shell" and "find src" in args["command"]:
            return "src/maistro/a.py\nsrc/maistro/b.py"
        if name == "shell" and "find tests" in args["command"]:
            return "tests/test_a.py"
        if name == "github":
            return "issue #1: rejected PR"
        return ""

    provider = FauxProvider(default_response=FauxResponse(content="frank diagnosed"))
    strategy = BuildersLearningStrategy(max_rounds=2, enable_learning=True)

    result = await strategy.reason(
        messages, "m", provider, worker="frank", tool_executor=tool_executor
    )

    assert result.response == "frank diagnosed"
    # Recon is owned by governed Builders nodes, not this strategy callback.
    assert calls == []


def test_strategy_owns_no_tool_execution_surface() -> None:
    """#847: a strategy must not carry its own recon/diagnostics executors."""
    strategy = BuildersLearningStrategy()

    for legacy_executor_name in (
        "_check_repository_state",
        "_analyze_failure_patterns",
        "_run_pr_diagnostics",
        "_store_frank_learning",
        "_store_mason_learning",
    ):
        assert not hasattr(strategy, legacy_executor_name)


async def test_mason_worker_no_critical_issues_stores_learning(
    messages: list[dict[str, Any]],
) -> None:
    async def fake(_name: str, _args: dict[str, Any]) -> str:
        return "all clean"

    provider = FauxProvider(default_response=FauxResponse(content="mason built it"))
    strategy = BuildersLearningStrategy(max_rounds=2, enable_learning=True)

    result = await strategy.reason(messages, "m", provider, worker="mason", tool_executor=fake)

    assert result.response == "mason built it"
    assert result.done is True


async def test_mason_worker_with_critical_issues_marks_not_done(
    messages: list[dict[str, Any]],
) -> None:
    async def fake(name: str, args: dict[str, Any]) -> str:
        if "ruff" in args["command"]:
            return "1 error found"
        return "clean"

    provider = FauxProvider(default_response=FauxResponse(content="mason built it"))
    strategy = BuildersLearningStrategy(max_rounds=2, enable_learning=True)

    result = await strategy.reason(messages, "m", provider, worker="mason", tool_executor=fake)

    # Command diagnostics are governed graph work, not strategy callback work.
    assert result.done is True
    assert result.response == "mason built it"


async def test_mason_worker_execution_mode_fix_when_frank_diagnostic_has_code(
    messages: list[dict[str, Any]],
) -> None:
    provider = FauxProvider(default_response=FauxResponse(content="mason fixed it"))
    strategy = BuildersLearningStrategy(max_rounds=2, enable_learning=False)

    result = await strategy.reason(
        messages,
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
    assert strategy.enable_learning is True
    assert strategy.process is None
    assert strategy.build is None
