"""Tests for BuildersLearningStrategy: Frank/Mason recon + diagnosis + react loop."""

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
    # Recon ran both shell finds plus the github failure-pattern lookup.
    assert (
        "github",
        {"action": "search_issues", "query": "is:pr is:closed label:rejected"},
    ) in calls


async def test_check_repository_state_no_executor_returns_empty(
    messages: list[dict[str, Any]],
) -> None:
    strategy = BuildersLearningStrategy()

    result = await strategy._check_repository_state()

    assert result == {"code": [], "tests": [], "failed_prs": []}


async def test_check_repository_state_handles_tool_exception() -> None:
    async def boom(_name: str, _args: dict[str, Any]) -> str:
        raise RuntimeError("shell unavailable")

    strategy = BuildersLearningStrategy()

    result = await strategy._check_repository_state(tool_executor=boom)

    assert result == {"code": [], "tests": [], "failed_prs": []}


async def test_check_repository_state_splits_lines_from_tool_output() -> None:
    async def fake(name: str, _args: dict[str, Any]) -> str:
        return "a.py\nb.py" if "find src" in _args["command"] else "test_a.py"

    strategy = BuildersLearningStrategy()

    result = await strategy._check_repository_state(tool_executor=fake)

    assert result == {"code": ["a.py", "b.py"], "tests": ["test_a.py"], "failed_prs": []}


async def test_analyze_failure_patterns_no_executor_returns_empty() -> None:
    strategy = BuildersLearningStrategy()

    result = await strategy._analyze_failure_patterns()

    assert result == {"similar_issues": [], "failures": [], "reasons": [], "lessons": []}


async def test_analyze_failure_patterns_handles_exception() -> None:
    async def boom(_name: str, _args: dict[str, Any]) -> str:
        raise RuntimeError("github unavailable")

    strategy = BuildersLearningStrategy()

    result = await strategy._analyze_failure_patterns(tool_executor=boom)

    assert result == {"similar_issues": [], "failures": [], "reasons": [], "lessons": []}


async def test_analyze_failure_patterns_truncates_to_ten_lines() -> None:
    lines = "\n".join(f"issue {i}" for i in range(20))

    async def fake(_name: str, _args: dict[str, Any]) -> str:
        return lines

    strategy = BuildersLearningStrategy()

    result = await strategy._analyze_failure_patterns(tool_executor=fake)

    assert len(result["failures"]) == 10
    assert result["failures"][0] == "issue 0"


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

    assert result.done is False
    assert result.response is not None
    assert "Self-diagnosis: Found 1 issues - must fix before PR" in result.response


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


async def test_run_pr_diagnostics_no_executor_returns_all_passed() -> None:
    strategy = BuildersLearningStrategy()

    result = await strategy._run_pr_diagnostics()

    assert result == {"all_passed": True, "issues": [], "has_critical_issues": False}


async def test_run_pr_diagnostics_each_tool_exception_recorded_as_issue() -> None:
    async def boom(_name: str, args: dict[str, Any]) -> str:
        raise RuntimeError(f"failed: {args['command'][:5]}")

    strategy = BuildersLearningStrategy()

    result = await strategy._run_pr_diagnostics(tool_executor=boom)

    assert result["has_critical_issues"] is True
    assert len(result["issues"]) == 3
    assert result["issues"][0].startswith("ruff: tool_executor failed")
    assert result["issues"][1].startswith("mypy: tool_executor failed")
    assert result["issues"][2].startswith("pytest: tool_executor failed")


async def test_run_pr_diagnostics_clean_all_passed() -> None:
    async def fake(_name: str, _args: dict[str, Any]) -> str:
        return "all good"

    strategy = BuildersLearningStrategy()

    result = await strategy._run_pr_diagnostics(tool_executor=fake)

    assert result == {"all_passed": True, "issues": [], "has_critical_issues": False}


async def test_run_pr_diagnostics_mypy_error_flagged() -> None:
    async def fake(_name: str, args: dict[str, Any]) -> str:
        if "mypy" in args["command"]:
            return "src/maistro/x.py:1: error: bad type"
        return "clean"

    strategy = BuildersLearningStrategy()

    result = await strategy._run_pr_diagnostics(tool_executor=fake)

    assert result["has_critical_issues"] is True
    assert any(issue.startswith("mypy:") for issue in result["issues"])


async def test_run_pr_diagnostics_pytest_failed_flagged() -> None:
    async def fake(_name: str, args: dict[str, Any]) -> str:
        if "pytest" in args["command"]:
            return "3 failed, 10 passed"
        return "clean"

    strategy = BuildersLearningStrategy()

    result = await strategy._run_pr_diagnostics(tool_executor=fake)

    assert result["has_critical_issues"] is True
    assert any("pytest:" in issue for issue in result["issues"])


def test_utc_now_returns_timezone_aware_datetime() -> None:
    from datetime import UTC

    strategy = BuildersLearningStrategy()

    now = strategy._utc_now()

    assert now.tzinfo == UTC


async def test_store_frank_learning_does_not_raise() -> None:
    from maistro.types.agent import ReasoningResult

    strategy = BuildersLearningStrategy()

    await strategy._store_frank_learning(
        {"code": ["a.py"], "tests": []}, {"failures": []}, ReasoningResult(response="x")
    )


async def test_store_mason_learning_does_not_raise() -> None:
    from maistro.types.agent import ReasoningResult

    strategy = BuildersLearningStrategy()

    await strategy._store_mason_learning(
        {"all_passed": True, "issues": []}, ReasoningResult(response="x", tool_history=[])
    )


def test_init_sets_defaults() -> None:
    strategy = BuildersLearningStrategy()

    assert strategy.max_rounds == 10
    assert strategy.force_tool_first is False
    assert strategy.enable_learning is True
    assert strategy.process is None
    assert strategy.build is None
