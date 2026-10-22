"""BFCL scoring tests — structured calls only (#852).

The historical implementation awarded partial credit for prose: 0.25 when
the expected function name appeared anywhere in the text, 0.5 when a missing
parameter's value appeared in the response, and it parsed
``call name(args...)`` out of free text. Those paths are removed; these
tests pin the structured-only contract, including the adversarial cases that
used to score.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro_evolve.benchmarks.bfcl import (
    _extract_tool_call,
    _name_score,
    _param_score,
    _score_numeric_param,
    _score_single_param,
    _score_tool_call,
    run_bfcl,
)
from maistro_evolve.benchmarks.datasets import BFCL_SAMPLES

from .conftest import make_genome


class TestExtractToolCall:
    def test_json_object_extracted(self):
        response = '```json\n{"name": "get_weather", "loc": "NYC"}\n```'
        assert _extract_tool_call(response) == {"name": "get_weather", "loc": "NYC"}

    def test_json_list_takes_first_element(self):
        # must be wrapped in a ```json``` block: a bare list-of-dicts response would
        # instead get matched by extract_json_from_response's earlier flat-dict regex
        # (which grabs the inner {"name": "get_weather"} substring directly as a dict,
        # never reaching the list branch at all)
        response = '```json\n[{"name": "get_weather"}, {"name": "other"}]\n```'
        assert _extract_tool_call(response) == {"name": "get_weather"}

    def test_bare_json_dict_extracted(self):
        assert _extract_tool_call('{"name": "refresh", "parameters": {}}') == {
            "name": "refresh",
            "parameters": {},
        }

    def test_prose_call_syntax_is_not_a_call(self):
        # #852: free-text call syntax used to be parsed into a structured
        # call; mentioning the tool in prose no longer qualifies.
        assert _extract_tool_call("I will call get_weather(location=NYC, unit=celsius)") is None
        assert _extract_tool_call("invoke refresh()") is None

    def test_no_match_returns_none(self):
        assert _extract_tool_call("just plain text, nothing useful") is None


class TestNameScore:
    def test_exact_match(self):
        assert _name_score("get_weather", "get_weather") == 1.0

    def test_substring_of_de_underscored(self):
        # Structured-name fuzz only: actual comes from a parsed JSON call.
        assert _name_score("getweather", "get_weather") == 0.8

    def test_space_joined_substring(self):
        assert _name_score("get weather extra", "get_weather") == 0.6

    def test_no_match(self):
        assert _name_score("totally_different", "get_weather") == 0.0


class TestScoreNumericParam:
    def test_exact_match(self):
        assert _score_numeric_param(5, 5) == 1.0

    def test_close_but_not_exact(self):
        assert _score_numeric_param(5.5, 5.0) == 0.5

    def test_far_off(self):
        assert _score_numeric_param(100, 5) == 0.0

    def test_non_numeric_values_earn_nothing(self):
        # #852: the old except-branch awarded 0.5 for substring coincidence.
        assert _score_numeric_param("around five", 5) == 0.0
        assert _score_numeric_param("the value is five", "five") == 0.0
        assert _score_numeric_param("the value is nope", "five") == 0.0


class TestScoreSingleParam:
    def test_missing_parameter_scores_zero(self):
        # #852: a missing parameter used to earn 0.5 when the expected value
        # appeared anywhere in the raw response text.
        assert _score_single_param(None, "tokyo") == 0.0
        assert _score_single_param(None, 42) == 0.0

    def test_bool_expected_match(self):
        assert _score_single_param(True, True) == 1.0
        assert _score_single_param("true", True) == 1.0

    def test_bool_expected_no_match(self):
        assert _score_single_param(False, True) == 0.0

    def test_numeric_expected_delegates_to_numeric_scorer(self):
        assert _score_single_param(5, 5) == 1.0
        assert _score_single_param(100, 5) == 0.0

    def test_string_expected_exact_match(self):
        assert _score_single_param("Tokyo", "tokyo") == 1.0

    def test_string_expected_substring_match(self):
        assert _score_single_param("Tokyo, Japan", "tokyo") == 0.7

    def test_string_expected_no_match(self):
        assert _score_single_param("Paris", "tokyo") == 0.0

    def test_unhandled_expected_type_returns_zero(self):
        # expected_val is a list — none of the isinstance branches match
        assert _score_single_param(["a"], ["a", "b"]) == 0.0


class TestParamScore:
    def test_empty_expected_params_returns_one(self):
        assert _param_score({"parameters": {}}, {}) == 1.0

    def test_non_dict_actual_params_means_missing(self):
        # #852: with params coerced to empty, every expected key is missing
        # and must score 0.0 — not 0.5 via a response-text fallback.
        call = {"parameters": "not-a-dict"}
        assert _param_score(call, {"location": "tokyo"}) == 0.0

    def test_matches_via_parameters_key(self):
        call = {"parameters": {"location": "Tokyo"}}
        assert _param_score(call, {"location": "tokyo"}) == 1.0

    def test_matches_via_arguments_key_fallback(self):
        call = {"arguments": {"location": "Tokyo"}}
        assert _param_score(call, {"location": "tokyo"}) == 1.0

    def test_matches_via_args_key_fallback(self):
        call = {"args": {"location": "Tokyo"}}
        assert _param_score(call, {"location": "tokyo"}) == 1.0

    def test_missing_key_counts_as_zero_in_average(self):
        call = {"parameters": {"location": "Tokyo"}}
        # unit is missing entirely -> 0.0 for that key (was 0.5 via prose).
        assert _param_score(call, {"location": "tokyo", "unit": "celsius"}) == 0.5

    def test_partial_match_averages(self):
        call = {"parameters": {"location": "Tokyo", "unit": "kelvin"}}
        result = _param_score(call, {"location": "tokyo", "unit": "celsius"})
        assert result == 0.5


class TestScoreToolCall:
    def test_function_call_match_short_circuits(self):
        # expected_params=None makes function_call_match return 1.0 on name match alone,
        # avoiding extract_json_from_response's non-nesting-brace limitation
        sample = {"expected_name": "refresh", "expected_params": None}
        response = '{"name": "refresh"}'
        assert _score_tool_call(response, sample) == 1.0

    def test_prose_name_mention_scores_zero(self):
        # #852: the 0.25 prose fallback is gone — a response that never
        # produces a structured call cannot clear the 0.20 hard gate.
        sample = BFCL_SAMPLES[0]
        response = "I should call get weather but I can't parse this as json"
        assert _score_tool_call(response, sample) == 0.0

    def test_no_extraction_and_no_name_mentioned(self):
        sample = BFCL_SAMPLES[0]
        response = "I have no idea what to do here"
        assert _score_tool_call(response, sample) == 0.0

    def test_json_call_with_matching_params_scores_full(self):
        sample = BFCL_SAMPLES[0]  # get_weather / {"location": "Tokyo"}
        response = '{"name": "get_weather", "parameters": {"location": "Tokyo"}}'
        assert _score_tool_call(response, sample) == 1.0

    def test_json_call_with_wrong_param_scores_name_only(self):
        sample = BFCL_SAMPLES[0]
        response = '{"name": "get_weather", "parameters": {"location": "Paris"}}'
        assert _score_tool_call(response, sample) == pytest.approx(1.0 * 0.4 + 0.0 * 0.6)

    def test_prose_call_syntax_scores_zero(self):
        # #852: 'call get_weather(location=Tokyo)' used to parse as a call
        # and score 1.0; prose is no longer a call.
        sample = BFCL_SAMPLES[0]
        assert _score_tool_call("call get_weather(location=Tokyo)", sample) == 0.0

    def test_weighted_blend_no_expected_params_means_param_score_one(self):
        sample = {
            "expected_name": "do_thing",
            "expected_params": None,
        }
        response = '{"name": "do_thing"}'
        # function_call_match short-circuits at 1.0 for name-only matching.
        assert _score_tool_call(response, sample) == 1.0


class TestRunBfcl:
    async def test_llm_call_none_raises(self):
        genome = make_genome()
        with pytest.raises(ValueError, match="requires an llm_call"):
            await run_bfcl(genome, None)

    async def test_llm_call_scores_via_function_call_match(self):
        genome = make_genome()

        async def llm_call(
            messages: list[dict[str, Any]], temperature: float = 0.1, max_tokens: int = 1024
        ) -> str:
            return '{"name": "get_weather", "parameters": {"location": "Tokyo"}}'

        result = await run_bfcl(genome, llm_call)
        assert result.samples_evaluated == len(BFCL_SAMPLES)
        # only bfcl_01 expects get_weather/Tokyo; others score lower or zero, but all evaluated
        assert result.cost_usd == round(0.001 * len(BFCL_SAMPLES), 4)
        assert result.score > 0.0

    async def test_prose_only_responses_score_zero(self):
        # Empty-body/no-call candidates cannot clear the 0.20 hard gate
        # through scorer fallbacks (#852 acceptance).
        genome = make_genome()

        async def llm_call(
            messages: list[dict[str, Any]], temperature: float = 0.1, max_tokens: int = 1024
        ) -> str:
            return (
                "I would use get_weather for Tokyo and also recommend "
                "lookup_order; nothing structured here."
            )

        result = await run_bfcl(genome, llm_call)
        assert result.score == 0.0

    async def test_llm_call_timeout_error_only_increments_evaluated(self):
        genome = make_genome()

        async def llm_call(
            messages: list[dict[str, Any]], temperature: float = 0.1, max_tokens: int = 1024
        ) -> str:
            raise TimeoutError("boom")

        result = await run_bfcl(genome, llm_call)
        assert result.samples_evaluated == len(BFCL_SAMPLES)
        assert result.score == 0.0
        assert result.cost_usd == 0.0

    async def test_llm_call_generic_exception_only_increments_evaluated(self):
        genome = make_genome()

        async def llm_call(
            messages: list[dict[str, Any]], temperature: float = 0.1, max_tokens: int = 1024
        ) -> str:
            raise ValueError("kaboom")

        result = await run_bfcl(genome, llm_call)
        assert result.samples_evaluated == len(BFCL_SAMPLES)
        assert result.score == 0.0
        assert result.cost_usd == 0.0

    async def test_llm_call_receives_model_config_kwargs(self):
        genome = make_genome(temperature=0.42, max_tokens=777)
        seen: dict[str, Any] = {}

        async def llm_call(
            messages: list[dict[str, Any]], temperature: float = 0.1, max_tokens: int = 1024
        ) -> str:
            seen["temperature"] = temperature
            seen["max_tokens"] = max_tokens
            return "no match here"

        await run_bfcl(genome, llm_call)
        assert seen == {"temperature": 0.42, "max_tokens": 777}
