"""Tests for maistro.security.sentinel.token_optimizer — tool-result size compression."""

from __future__ import annotations

import json

from maistro.security.sentinel.token_optimizer import (
    MAX_RESULT_LENGTH,
    TRUNCATION_MARKER,
    optimize_result,
)


class TestOptimizeResult:
    def test_short_result_returned_unchanged(self) -> None:
        result = "short result"
        assert optimize_result(result) == result

    def test_result_at_exact_max_length_returned_unchanged(self) -> None:
        result = "x" * MAX_RESULT_LENGTH
        assert optimize_result(result) == result

    def test_long_json_compacted_when_compaction_fits(self) -> None:
        data = {"items": list(range(500))}
        result = json.dumps(data, indent=4)
        compact = json.dumps(data, separators=(",", ":"))
        assert len(result) > MAX_RESULT_LENGTH > len(compact)
        optimized = optimize_result(result)
        assert json.loads(optimized) == data
        assert optimized == compact

    def test_long_json_still_too_big_after_compaction_gets_truncated(self) -> None:
        data = {"key": "x" * 10000}
        result = json.dumps(data, indent=4)
        optimized = optimize_result(result)
        assert optimized.endswith(TRUNCATION_MARKER)
        assert len(optimized) == MAX_RESULT_LENGTH

    def test_long_non_json_string_gets_truncated(self) -> None:
        result = "not json " * 1000
        optimized = optimize_result(result)
        assert optimized.endswith(TRUNCATION_MARKER)
        assert len(optimized) == MAX_RESULT_LENGTH

    def test_long_digit_string_invalid_json_gets_truncated(self) -> None:
        result = "5" * (MAX_RESULT_LENGTH + 1)
        optimized = optimize_result(result)
        assert optimized.endswith(TRUNCATION_MARKER)

    def test_tool_name_argument_accepted_and_ignored(self) -> None:
        result = "not json " * 1000
        optimized = optimize_result(result, tool_name="my_tool")
        assert optimized.endswith(TRUNCATION_MARKER)
