from __future__ import annotations

import pytest

from maistro.graph.compaction import CompactionConfig, ContextCompactor
from maistro.graph.types import GraphBlackboard


def _make_blackboard(**overrides) -> GraphBlackboard:
    defaults = {"task_objective": "Test objective", "workspace": "/tmp/test"}
    defaults.update(overrides)
    return GraphBlackboard(**defaults)


def _large_blackboard() -> GraphBlackboard:
    return _make_blackboard(
        task_objective="x" * 5000,
        node_annotations={f"key_{i}": "v" * 200 for i in range(20)},
        metadata={"context": "y" * 5000},
    )


class TestShouldCompact:
    @pytest.mark.ac("ADR-066/AC-9")
    def test_under_threshold(self):
        config = CompactionConfig(threshold_tokens=10000)
        compactor = ContextCompactor(config)
        bb = _make_blackboard()
        assert compactor.should_compact(bb) is False

    def test_over_threshold(self):
        config = CompactionConfig(threshold_tokens=100)
        compactor = ContextCompactor(config)
        bb = _large_blackboard()
        assert compactor.should_compact(bb) is True


class TestSimpleCompact:
    def test_truncates_long_fields(self):
        config = CompactionConfig(threshold_tokens=100)
        compactor = ContextCompactor(config)
        bb = _make_blackboard(node_annotations={"key": "v" * 1000})
        result = compactor._simple_compact(bb)
        assert len(result.node_annotations["key"]) == 500

    def test_adds_compaction_summary(self):
        config = CompactionConfig(threshold_tokens=100)
        compactor = ContextCompactor(config)
        bb = _make_blackboard()
        result = compactor._simple_compact(bb)
        assert "_compaction_summary" in result.metadata

    def test_trims_optimization_history(self):
        config = CompactionConfig(threshold_tokens=100)
        compactor = ContextCompactor(config)
        bb = _make_blackboard(optimization_history=list(range(10)))
        result = compactor._simple_compact(bb)
        assert len(result.optimization_history) == 2

    def test_preserves_task_objective(self):
        config = CompactionConfig(threshold_tokens=100)
        compactor = ContextCompactor(config)
        bb = _make_blackboard(task_objective="Important objective")
        result = compactor._simple_compact(bb)
        assert result.task_objective == "Important objective"


class TestLlmCompact:
    def test_uses_llm_call(self):
        config = CompactionConfig(threshold_tokens=100)
        compactor = ContextCompactor(config)
        bb = _make_blackboard(node_annotations={"k": "v" * 1000})

        def mock_llm(prompt: str) -> str:
            return "LLM summary of context"

        result = compactor.compact(bb, llm_call=mock_llm)
        assert result.metadata["_compaction_summary"] == "LLM summary of context"

    @pytest.mark.ac("ADR-066/AC-11")
    def test_stores_previous_summary(self):
        compactor = ContextCompactor(CompactionConfig(threshold_tokens=100))
        bb = _make_blackboard(node_annotations={"k": "v" * 1000})

        call_count = 0

        def mock_llm(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"Summary {call_count}"

        result1 = compactor.compact(bb, llm_call=mock_llm)
        assert result1.metadata["_previous_summary"] is None
        assert result1.metadata["_compaction_summary"] == "Summary 1"

        result2 = compactor.compact(bb, llm_call=mock_llm)
        assert result2.metadata["_previous_summary"] == "Summary 1"
        assert result2.metadata["_compaction_summary"] == "Summary 2"


class TestBuildCompactionPrompt:
    def test_without_previous_summary(self):
        compactor = ContextCompactor()
        bb = _make_blackboard()
        prompt = compactor._build_compaction_prompt(None, bb)
        assert "Goal" in prompt
        assert "Test objective" in prompt
        assert "Progress So Far" not in prompt

    @pytest.mark.ac("ADR-066/AC-11")
    def test_with_previous_summary(self):
        compactor = ContextCompactor()
        bb = _make_blackboard()
        prompt = compactor._build_compaction_prompt("Previous work done", bb)
        assert "Progress So Far" in prompt
        assert "Previous work done" in prompt

    def test_includes_annotations(self):
        compactor = ContextCompactor()
        bb = _make_blackboard(node_annotations={"decision": "chose python"})
        prompt = compactor._build_compaction_prompt(None, bb)
        assert "Key Decisions Made" in prompt
        assert "chose python" in prompt

    def test_includes_metadata(self):
        compactor = ContextCompactor()
        bb = _make_blackboard(metadata={"critical": "do not delete"})
        prompt = compactor._build_compaction_prompt(None, bb)
        assert "Critical Context" in prompt
        assert "do not delete" in prompt


class TestCompactIntegration:
    def test_compact_without_llm_uses_simple(self):
        config = CompactionConfig(threshold_tokens=100)
        compactor = ContextCompactor(config)
        bb = _make_blackboard(node_annotations={"k": "v" * 1000})
        result = compactor.compact(bb)
        assert "_compaction_summary" in result.metadata
        assert len(result.node_annotations["k"]) == 500

    def test_respects_max_summaries(self):
        config = CompactionConfig(threshold_tokens=100, max_summaries=2)
        compactor = ContextCompactor(config)
        bb = _make_blackboard(node_annotations={"k": "v" * 1000})

        compactor.compact(bb)
        compactor.compact(bb)
        compactor.compact(bb)

        assert len(compactor._summaries) == 2
