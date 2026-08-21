"""Coverage for memory/learnings/extractor.py."""

from __future__ import annotations

from typing import Any

from maistro.memory.learnings.extractor import (
    RCAExtractor,
    ToolCorrectionExtractor,
    _parse_rca_output,
)
from maistro.memory.types import MemoryScope


def test_parse_rca_output_extracts_category_and_prevention() -> None:
    text = "CATEGORY: rate_limit\nROOT CAUSE: too many requests\nPREVENTION: add backoff"
    category, prevention = _parse_rca_output(text)
    assert category == "rate_limit"
    assert prevention == "add backoff"


def test_parse_rca_output_defaults_unrecognized_category_to_unknown() -> None:
    text = "CATEGORY: not_a_real_category\nPREVENTION: x"
    category, _ = _parse_rca_output(text)
    assert category == "unknown"


def test_parse_rca_output_defaults_when_no_lines_match() -> None:
    category, prevention = _parse_rca_output("nothing useful here")
    assert category == "unknown"
    assert prevention == ""


def test_parse_rca_output_ignores_root_cause_line() -> None:
    text = "ROOT CAUSE: some cause\nCATEGORY: unknown\nPREVENTION: avoid it"
    category, prevention = _parse_rca_output(text)
    assert category == "unknown"
    assert prevention == "avoid it"


def test_extract_corrections_detects_fail_then_succeed() -> None:
    extractor = ToolCorrectionExtractor()
    history = [
        {"tool_name": "search", "result": "Error: not found", "arguments": {"q": "a"}},
        {"tool_name": "search", "result": "found it", "arguments": {"q": "b"}},
    ]
    learnings = extractor.extract_corrections("find the widget please", history)
    assert len(learnings) == 1
    learning = learnings[0]
    assert learning.category == "tool_correction"
    assert learning.tool_name == "search"
    assert learning.scope == MemoryScope.AGENT
    assert "fails with {'q': 'a'}" in learning.learning
    assert "succeeds with {'q': 'b'}" in learning.learning


def test_extract_corrections_skips_tools_with_fewer_than_two_calls() -> None:
    extractor = ToolCorrectionExtractor()
    history = [{"tool_name": "search", "result": "Error", "arguments": {}}]
    assert extractor.extract_corrections("text", history) == []


def test_extract_corrections_no_pattern_when_no_failure_then_success() -> None:
    extractor = ToolCorrectionExtractor()
    history = [
        {"tool_name": "search", "result": "ok1", "arguments": {}},
        {"tool_name": "search", "result": "ok2", "arguments": {}},
    ]
    assert extractor.extract_corrections("text", history) == []


def test_extract_corrections_no_pattern_when_failure_followed_by_failure() -> None:
    extractor = ToolCorrectionExtractor()
    history = [
        {"tool_name": "search", "result": "Error: bad", "arguments": {}},
        {"tool_name": "search", "result": "still has error", "arguments": {}},
    ]
    assert extractor.extract_corrections("text", history) == []


def test_extract_corrections_trigger_keys_filters_short_words_and_caps_at_five() -> None:
    extractor = ToolCorrectionExtractor()
    history = [
        {"tool_name": "search", "result": "Error", "arguments": {}},
        {"tool_name": "search", "result": "ok", "arguments": {}},
    ]
    learnings = extractor.extract_corrections(
        "a an the quickest brownest foxes jumped over lazy dogs", history
    )
    assert len(learnings[0].trigger_keys) == 5
    assert all(len(w) > 2 for w in learnings[0].trigger_keys)


def test_extract_positive_patterns_detects_first_try_success() -> None:
    extractor = ToolCorrectionExtractor()
    history = [{"tool_name": "search", "result": "found it", "arguments": {"q": "a"}, "round": 0}]
    learnings = extractor.extract_positive_patterns("vague query here", history)
    assert len(learnings) == 1
    learning = learnings[0]
    assert learning.category == "positive_pattern"
    assert learning.tool_name == "search"
    assert "succeeded on first try" in learning.learning


def test_extract_positive_patterns_skips_failures() -> None:
    extractor = ToolCorrectionExtractor()
    history = [{"tool_name": "search", "result": "Error: bad", "arguments": {}, "round": 0}]
    assert extractor.extract_positive_patterns("text", history) == []


def test_extract_positive_patterns_skips_non_round_zero() -> None:
    extractor = ToolCorrectionExtractor()
    history = [{"tool_name": "search", "result": "ok", "arguments": {}, "round": 1}]
    assert extractor.extract_positive_patterns("text", history) == []


def test_extract_positive_patterns_defaults_round_to_zero_when_missing() -> None:
    extractor = ToolCorrectionExtractor()
    history = [{"tool_name": "search", "result": "ok", "arguments": {}}]
    learnings = extractor.extract_positive_patterns("text here", history)
    assert len(learnings) == 1


async def test_extract_rca_returns_none_when_no_failures() -> None:
    rca = RCAExtractor()
    result = await rca.extract_rca("text", [{"tool_name": "x", "result": "ok"}])
    assert result is None


async def test_extract_rca_returns_none_when_llm_unavailable() -> None:
    rca = RCAExtractor(llm_client=None)
    history = [{"tool_name": "search", "result": "Error: boom", "arguments": {}}]
    result = await rca.extract_rca("text", history)
    assert result is None


async def test_extract_rca_builds_learning_from_llm_response() -> None:
    class _StubClient:
        async def complete(self, messages: list[dict[str, Any]], model: str, **kwargs: Any) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "CATEGORY: rate_limit\n"
                                "ROOT CAUSE: too many calls\n"
                                "PREVENTION: throttle requests"
                            )
                        }
                    }
                ]
            }

        def stream(self, messages: list[dict[str, Any]], model: str, **kwargs: Any) -> Any:
            raise NotImplementedError

    rca = RCAExtractor(llm_client=_StubClient(), rca_model="fast-model")
    history = [
        {"tool_name": "search", "result": "Error: boom", "arguments": {"q": "a"}},
        {"tool_name": "fetch", "result": "ok", "arguments": {}},
    ]
    result = await rca.extract_rca("please find the thing", history)

    assert result is not None
    assert result.category == "rca"
    assert result.rca_category == "rate_limit"
    assert result.rca_prevention == "throttle requests"
    assert result.tool_name == "search"
    assert result.scope == MemoryScope.AGENT
    assert "too many calls" in result.learning


async def test_extract_rca_returns_none_when_llm_returns_empty_content() -> None:
    class _StubClient:
        async def complete(self, messages: list[dict[str, Any]], model: str, **kwargs: Any) -> dict:
            return {"choices": []}

        def stream(self, messages: list[dict[str, Any]], model: str, **kwargs: Any) -> Any:
            raise NotImplementedError

    rca = RCAExtractor(llm_client=_StubClient())
    history = [{"tool_name": "search", "result": "Error: boom", "arguments": {}}]
    result = await rca.extract_rca("text", history)
    assert result is None


async def test_call_llm_returns_none_when_client_is_not_llm_client_protocol() -> None:
    rca = RCAExtractor(llm_client=object())
    result = await rca._call_llm("prompt")
    assert result is None


async def test_call_llm_swallows_exceptions_and_returns_none() -> None:
    class _BrokenClient:
        async def complete(self, messages: list[dict[str, Any]], model: str, **kwargs: Any) -> dict:
            raise RuntimeError("boom")

        def stream(self, messages: list[dict[str, Any]], model: str, **kwargs: Any) -> Any:
            raise NotImplementedError

    rca = RCAExtractor(llm_client=_BrokenClient())
    result = await rca._call_llm("prompt")
    assert result is None


def test_rca_categories_contains_expected_set() -> None:
    from maistro.memory.learnings.extractor import RCA_CATEGORIES

    assert (
        frozenset(
            {
                "missing_precondition",
                "tool_contract_mismatch",
                "permission_gap",
                "rate_limit",
                "input_validation",
                "ambiguous_intent",
                "unknown",
            }
        )
        == RCA_CATEGORIES
    )
