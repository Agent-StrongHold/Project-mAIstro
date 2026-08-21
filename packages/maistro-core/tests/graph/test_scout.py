"""Coverage for graph/scout.py."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from maistro.graph.scout import _scout_prompt, _strip_json_block, run_scout
from maistro.graph.types import GraphBlackboard, GraphTask, OptimizationSignal

VALID_SCOUT_JSON = json.dumps(
    {
        "relevant_files": ["a.py", "b.py"],
        "patterns": "uses repository pattern",
        "dependency_map": {"a.py": ["b.py"]},
        "similar_implementations": ["c.py"],
        "summary": "Scouted the workspace.",
    }
)


def _task(description: str = "Build a thing") -> GraphTask:
    return GraphTask(description=description, workspace="/ws")


def _blackboard(**kwargs: Any) -> GraphBlackboard:
    return GraphBlackboard(task_objective="obj", workspace="/ws", **kwargs)


def test_strip_json_block_extracts_fenced_json() -> None:
    text = '```json\n{"a": 1}\n```'
    assert _strip_json_block(text) == '{"a": 1}'


def test_strip_json_block_extracts_fenced_block_without_json_tag() -> None:
    text = '```\n{"a": 1}\n```'
    assert _strip_json_block(text) == '{"a": 1}'


def test_strip_json_block_returns_stripped_text_when_no_fence() -> None:
    text = '  {"a": 1}  '
    assert _strip_json_block(text) == '{"a": 1}'


def test_scout_prompt_without_optimization_history() -> None:
    prompt = _scout_prompt(_task(), _blackboard())
    assert "Task: Build a thing" in prompt
    assert "Workspace: /ws" in prompt
    assert "Iteration: 0" in prompt
    assert "Optimization history" not in prompt


def test_scout_prompt_includes_weakest_node_and_score() -> None:
    signal = OptimizationSignal(
        node_metrics=[], weakest_node="coder", total_runs=5, avg_review_score=7.5
    )
    blackboard = _blackboard(iteration=2, optimization_history=[signal])
    prompt = _scout_prompt(_task(), blackboard)
    assert "weakest node was coder, avg review 7.5/10" in prompt
    assert "Focus especially on context relevant to coder" in prompt


def test_scout_prompt_omits_score_when_avg_review_score_is_none() -> None:
    signal = OptimizationSignal(node_metrics=[], weakest_node="coder", total_runs=5)
    blackboard = _blackboard(optimization_history=[signal])
    prompt = _scout_prompt(_task(), blackboard)
    assert "weakest node was coder. " in prompt


def test_scout_prompt_omits_history_summary_when_weakest_node_falsy() -> None:
    signal = OptimizationSignal(node_metrics=[], weakest_node="", total_runs=5)
    blackboard = _blackboard(optimization_history=[signal])
    prompt = _scout_prompt(_task(), blackboard)
    assert "Optimization history" not in prompt


async def test_run_scout_returns_updated_blackboard_on_success() -> None:
    async def llm_call(
        messages: list[dict[str, str]], *, model: str, temperature: float | None
    ) -> str:
        assert model == "default"
        return f"```json\n{VALID_SCOUT_JSON}\n```"

    blackboard = _blackboard()
    result = await run_scout(_task(), blackboard, llm_call)

    assert result.scout_context is not None
    assert result.scout_context.relevant_files == ["a.py", "b.py"]
    assert result.scout_context.patterns == "uses repository pattern"
    assert result.scout_context.dependency_map == {"a.py": ["b.py"]}
    assert result.scout_context.similar_implementations == ["c.py"]
    assert result.scout_context.raw_findings == "Scouted the workspace."


async def test_run_scout_passes_model_and_temperature_through() -> None:
    captured: dict[str, Any] = {}

    async def llm_call(
        messages: list[dict[str, str]], *, model: str, temperature: float | None
    ) -> str:
        captured["model"] = model
        captured["temperature"] = temperature
        return VALID_SCOUT_JSON

    await run_scout(_task(), _blackboard(), llm_call, model="gpt-5", temperature=0.7)
    assert captured == {"model": "gpt-5", "temperature": 0.7}


async def test_run_scout_returns_unchanged_blackboard_on_invalid_json() -> None:
    async def llm_call(
        messages: list[dict[str, str]], *, model: str, temperature: float | None
    ) -> str:
        return "not json"

    blackboard = _blackboard()
    result = await run_scout(_task(), blackboard, llm_call)
    assert result.scout_context is None
    assert result is blackboard


async def test_run_scout_returns_unchanged_blackboard_on_validation_error() -> None:
    async def llm_call(
        messages: list[dict[str, str]], *, model: str, temperature: float | None
    ) -> str:
        return json.dumps({"patterns": "x"})

    blackboard = _blackboard()
    result = await run_scout(_task(), blackboard, llm_call)
    assert result.scout_context is None
    assert result is blackboard


async def test_run_scout_returns_unchanged_blackboard_on_timeout() -> None:
    async def llm_call(
        messages: list[dict[str, str]], *, model: str, temperature: float | None
    ) -> str:
        await asyncio.sleep(10)
        return VALID_SCOUT_JSON

    blackboard = _blackboard()
    result = await run_scout(_task(), blackboard, llm_call, timeout=0.01)
    assert result is blackboard


async def test_run_scout_returns_unchanged_blackboard_when_llm_call_raises() -> None:
    async def llm_call(
        messages: list[dict[str, str]], *, model: str, temperature: float | None
    ) -> str:
        raise RuntimeError("llm down")

    blackboard = _blackboard()
    result = await run_scout(_task(), blackboard, llm_call)
    assert result is blackboard
