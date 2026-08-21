"""Coverage for graph/optimizer.py."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.graph.optimizer import (
    GraphOptimizer,
    _compute_bottleneck_score,
    _describe_pipeline,
    _role_name,
)
from maistro.graph.types import (
    AgentRole,
    GraphConfig,
    GraphEdge,
    GraphNodeResult,
    HyperagentOutput,
    NodeConfig,
    ReviewOutput,
)


def test_compute_bottleneck_score_with_known_review_score() -> None:
    score = _compute_bottleneck_score(
        success_rate=0.5, avg_review_score=5.0, avg_tokens=50.0, max_avg_tokens=100.0
    )
    # failure=0.5, quality_gap=0.5, token_waste=(0.5*0.5)=0.25
    assert score == pytest.approx(0.5 * 0.5 + 0.4 * 0.5 + 0.1 * 0.25)


def test_compute_bottleneck_score_uses_default_quality_gap_when_no_review_score() -> None:
    score = _compute_bottleneck_score(
        success_rate=1.0, avg_review_score=None, avg_tokens=10.0, max_avg_tokens=100.0
    )
    # failure=0, quality_gap default=0.5, token_waste=0
    assert score == pytest.approx(0.4 * 0.5)


def test_compute_bottleneck_score_clamped_to_one() -> None:
    score = _compute_bottleneck_score(
        success_rate=0.0, avg_review_score=0.0, avg_tokens=1000.0, max_avg_tokens=1.0
    )
    assert score == 1.0


def test_role_name_returns_empty_for_none() -> None:
    assert _role_name(None) == ""


def test_role_name_returns_value_for_agent_role() -> None:
    assert _role_name(AgentRole.CODER) == "coder"


def test_role_name_returns_raw_string_for_non_enum() -> None:
    assert _role_name("custom-node") == "custom-node"


def test_describe_pipeline_without_edges_joins_node_names() -> None:
    config = GraphConfig(nodes=[AgentRole.PLANNER, AgentRole.CODER], edges=[])
    assert _describe_pipeline(config) == "planner -> coder"


def test_describe_pipeline_with_edges_renders_arrows_and_conditions() -> None:
    config = GraphConfig(
        nodes=[AgentRole.PLANNER, AgentRole.CODER],
        edges=[
            GraphEdge(from_role=AgentRole.PLANNER, to_role=AgentRole.CODER),
            GraphEdge(
                from_role=AgentRole.CODER, to_role=AgentRole.REVIEWER, parallel=True, condition="ok"
            ),
            GraphEdge(from_role=AgentRole.REVIEWER, to_role=None),
        ],
    )
    desc = _describe_pipeline(config)
    assert "planner -> coder" in desc
    assert "coder >> reviewer [ok]" in desc
    assert "reviewer -> END" in desc


def _node_result(role: AgentRole, success: bool, tokens: int, output: str = "") -> GraphNodeResult:
    return GraphNodeResult(role=role, success=success, output=output, tokens_used=tokens)


def _trace(
    node_results: list[GraphNodeResult], review: ReviewOutput | None = None
) -> HyperagentOutput:
    return HyperagentOutput(node_results=node_results, review=review)


def _optimizer(llm_call: Any = None) -> GraphOptimizer:
    return GraphOptimizer(task_description="Build a feature", llm_call=llm_call)


def test_extract_signal_raises_when_no_traces() -> None:
    optimizer = _optimizer()
    with pytest.raises(ValueError, match="At least one trace"):
        optimizer.extract_signal([])


def test_extract_signal_computes_metrics_and_weakest_node() -> None:
    optimizer = _optimizer()
    traces = [
        _trace(
            [
                _node_result(AgentRole.PLANNER, True, 100),
                _node_result(AgentRole.CODER, False, 200),
            ],
            review=ReviewOutput(approved=False, score=3.0),
        ),
        _trace(
            [
                _node_result(AgentRole.PLANNER, True, 100),
                _node_result(AgentRole.CODER, True, 50),
            ],
        ),
    ]
    signal = optimizer.extract_signal(traces)
    assert signal.total_runs == 2
    assert signal.avg_review_score == 3.0
    by_role = {m.role: m for m in signal.node_metrics}
    assert by_role[AgentRole.PLANNER].success_rate == 1.0
    assert by_role[AgentRole.CODER].success_rate == 0.5
    assert signal.weakest_node == AgentRole.CODER


def test_extract_signal_reviewer_metric_gets_pipeline_avg_review_score() -> None:
    optimizer = _optimizer()
    traces = [
        _trace(
            [_node_result(AgentRole.REVIEWER, True, 10)],
            review=ReviewOutput(approved=True, score=8.0),
        )
    ]
    signal = optimizer.extract_signal(traces)
    reviewer_metric = next(m for m in signal.node_metrics if m.role == AgentRole.REVIEWER)
    assert reviewer_metric.avg_review_score == 8.0


def test_extract_signal_non_reviewer_metric_has_no_review_score() -> None:
    optimizer = _optimizer()
    traces = [
        _trace(
            [_node_result(AgentRole.PLANNER, True, 10)],
            review=ReviewOutput(approved=True, score=8.0),
        )
    ]
    signal = optimizer.extract_signal(traces)
    planner_metric = next(m for m in signal.node_metrics if m.role == AgentRole.PLANNER)
    assert planner_metric.avg_review_score is None


def test_extract_signal_ignores_non_review_output_review_field() -> None:
    optimizer = _optimizer()
    trace = HyperagentOutput(node_results=[_node_result(AgentRole.PLANNER, True, 10)])
    signal = optimizer.extract_signal([trace])
    assert signal.avg_review_score is None


def test_current_prompt_uses_node_config_system_prompt_when_present() -> None:
    optimizer = _optimizer()
    config = GraphConfig(
        nodes=[AgentRole.CODER],
        node_configs={"coder": NodeConfig(role=AgentRole.CODER, system_prompt="Custom prompt")},
    )
    assert optimizer._current_prompt(config, AgentRole.CODER) == "Custom prompt"


def test_current_prompt_falls_back_to_default_system_prompt() -> None:
    optimizer = _optimizer()
    config = GraphConfig(nodes=[AgentRole.CODER])
    prompt = optimizer._current_prompt(config, AgentRole.CODER)
    assert "expert software developer" in prompt


def test_current_prompt_returns_empty_for_unknown_role_string() -> None:
    optimizer = _optimizer()
    config = GraphConfig(nodes=["custom-kind"])
    assert optimizer._current_prompt(config, "custom-kind") == ""


def test_collect_failures_filters_by_role_and_success_and_truncates() -> None:
    optimizer = _optimizer()
    traces = [
        _trace([_node_result(AgentRole.CODER, False, 10, output="x" * 400)]),
        _trace([_node_result(AgentRole.PLANNER, False, 10, output="should not appear")]),
        _trace([_node_result(AgentRole.CODER, True, 10, output="success, not a failure")]),
    ]
    failures = optimizer._collect_failures(traces, AgentRole.CODER)
    assert len(failures) == 1
    assert len(failures[0]) == 300


def test_collect_failures_stops_at_five() -> None:
    optimizer = _optimizer()
    traces = [
        _trace([_node_result(AgentRole.CODER, False, 10, output=f"fail{i}")]) for i in range(10)
    ]
    failures = optimizer._collect_failures(traces, AgentRole.CODER)
    assert len(failures) == 5


def test_collect_failures_skips_results_with_no_output() -> None:
    optimizer = _optimizer()
    traces = [_trace([_node_result(AgentRole.CODER, False, 10, output="")])]
    assert optimizer._collect_failures(traces, AgentRole.CODER) == []


async def test_propose_prompt_raises_without_llm_call() -> None:
    optimizer = GraphOptimizer(task_description="t", llm_call=None)
    config = GraphConfig(nodes=[AgentRole.CODER])
    signal = optimizer.extract_signal([_trace([_node_result(AgentRole.CODER, True, 10)])])
    with pytest.raises(RuntimeError, match="llm_call is required"):
        await optimizer._propose_prompt(config, signal, AgentRole.CODER, "current", [])


async def test_propose_prompt_builds_meta_prompt_and_returns_stripped_result() -> None:
    captured: dict[str, Any] = {}

    async def llm_call(messages: list[dict[str, str]], *, model: str) -> str:
        captured["messages"] = messages
        captured["model"] = model
        return "  improved prompt  \n"

    optimizer = GraphOptimizer(task_description="Build a feature", model="gpt-5", llm_call=llm_call)
    config = GraphConfig(nodes=[AgentRole.PLANNER, AgentRole.CODER])
    signal = optimizer.extract_signal(
        [
            _trace(
                [_node_result(AgentRole.CODER, False, 10, output="boom")],
                review=ReviewOutput(approved=False, score=4.0),
            )
        ]
    )

    result = await optimizer._propose_prompt(
        config, signal, AgentRole.CODER, "old prompt", ["boom"]
    )

    assert result == "improved prompt"
    assert captured["model"] == "gpt-5"
    messages = captured["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    user_content = messages[1]["content"]
    assert "Build a feature" in user_content
    assert "old prompt" in user_content
    assert "Pipeline average review score: 4.0/10" in user_content
    assert "[1] boom" in user_content
    assert "CODER" in user_content


async def test_propose_prompt_omits_review_context_when_avg_review_score_none() -> None:
    captured: dict[str, Any] = {}

    async def llm_call(messages: list[dict[str, str]], *, model: str) -> str:
        captured["messages"] = messages
        return "x"

    optimizer = GraphOptimizer(task_description="t", llm_call=llm_call)
    config = GraphConfig(nodes=[AgentRole.CODER])
    signal = optimizer.extract_signal([_trace([_node_result(AgentRole.CODER, True, 10)])])
    await optimizer._propose_prompt(config, signal, AgentRole.CODER, "p", [])

    assert "Pipeline average review score" not in captured["messages"][1]["content"]


async def test_propose_prompt_uses_no_recorded_failures_text_when_empty() -> None:
    captured: dict[str, Any] = {}

    async def llm_call(messages: list[dict[str, str]], *, model: str) -> str:
        captured["messages"] = messages
        return "x"

    optimizer = GraphOptimizer(task_description="t", llm_call=llm_call)
    config = GraphConfig(nodes=[AgentRole.CODER])
    signal = optimizer.extract_signal([_trace([_node_result(AgentRole.CODER, True, 10)])])
    await optimizer._propose_prompt(config, signal, AgentRole.CODER, "p", [])
    assert "No recorded failures." in captured["messages"][1]["content"]


async def test_propose_prompt_lists_other_nodes_or_none() -> None:
    captured: dict[str, Any] = {}

    async def llm_call(messages: list[dict[str, str]], *, model: str) -> str:
        captured["messages"] = messages
        return "x"

    optimizer = GraphOptimizer(task_description="t", llm_call=llm_call)
    config = GraphConfig(nodes=[AgentRole.CODER])
    signal = optimizer.extract_signal([_trace([_node_result(AgentRole.CODER, True, 10)])])
    await optimizer._propose_prompt(config, signal, AgentRole.CODER, "p", [])
    assert "Other nodes: none" in captured["messages"][1]["content"]

    config2 = GraphConfig(nodes=[AgentRole.CODER, AgentRole.PLANNER])
    await optimizer._propose_prompt(config2, signal, AgentRole.CODER, "p", [])
    assert "Other nodes: planner" in captured["messages"][1]["content"]


async def test_propose_prompt_handles_unknown_role_string_for_upstream_output_downstream() -> None:
    captured: dict[str, Any] = {}

    async def llm_call(messages: list[dict[str, str]], *, model: str) -> str:
        captured["messages"] = messages
        return "x"

    optimizer = GraphOptimizer(task_description="t", llm_call=llm_call)
    config = GraphConfig(nodes=["custom-kind"])
    signal = optimizer.extract_signal([_trace([_node_result("custom-kind", True, 10)])])
    await optimizer._propose_prompt(config, signal, "custom-kind", "p", [])
    content = captured["messages"][1]["content"]
    assert "task inputs" in content
    assert "structured output" in content
    assert "next pipeline node" in content


async def test_optimize_returns_config_unchanged_when_no_traces() -> None:
    optimizer = _optimizer()
    config = GraphConfig(nodes=[AgentRole.CODER])
    result = await optimizer.optimize(config, [])
    assert result is config


async def test_optimize_updates_node_config_with_improved_prompt() -> None:
    async def llm_call(messages: list[dict[str, str]], *, model: str) -> str:
        return "improved prompt"

    optimizer = GraphOptimizer(task_description="t", llm_call=llm_call)
    config = GraphConfig(nodes=[AgentRole.PLANNER, AgentRole.CODER])
    traces = [
        _trace(
            [
                _node_result(AgentRole.PLANNER, True, 10),
                _node_result(AgentRole.CODER, False, 200, output="boom"),
            ]
        )
    ]
    result = await optimizer.optimize(config, traces)
    assert result is not config
    assert result.node_configs["coder"].system_prompt == "improved prompt"
    # original config untouched
    assert "coder" not in config.node_configs
