from __future__ import annotations

from maistro_evolve.benchmarks.scoring import (
    extract_json_from_response,
    function_call_match,
)


class TestExtractJsonFromResponseRegressions:
    """Phase 16.5 item 1: extract_json_from_response pattern-order bugs.

    The old implementation tried a non-nesting flat-dict regex before the
    flat-list regex, and used [^{}]* character classes that can't span
    nested braces. Both silently dropped data; see scoring.py history.
    """

    def test_unfenced_multi_call_array_captures_all_elements(self):
        response = 'Sure, here are the calls: [{"name": "first"}, {"name": "second"}]'
        result = extract_json_from_response(response)
        assert result == [{"name": "first"}, {"name": "second"}]

    def test_unfenced_nested_parameters_keeps_outer_name_key(self):
        response = 'Calling it now: {"name": "get_weather", "parameters": {"location": "nyc"}}'
        result = extract_json_from_response(response)
        assert result == {
            "name": "get_weather",
            "parameters": {"location": "nyc"},
        }

    def test_single_unfenced_object_still_works(self):
        response = 'Result: {"status": "ok"}'
        assert extract_json_from_response(response) == {"status": "ok"}

    def test_single_unfenced_list_still_works(self):
        response = "Items: [1, 2, 3]"
        assert extract_json_from_response(response) == [1, 2, 3]

    def test_fenced_json_block_still_preferred_over_balanced_scan(self):
        response = '```json\n{"name": "fenced"}\n```\nAlso mentions {"name": "decoy"} in passing.'
        assert extract_json_from_response(response) == {"name": "fenced"}

    def test_bare_json_with_no_surrounding_text(self):
        response = '{"name": "bare"}'
        assert extract_json_from_response(response) == {"name": "bare"}

    def test_no_json_present_returns_none(self):
        assert extract_json_from_response("just plain text, no json here") is None

    def test_unparseable_braces_returns_none(self):
        assert extract_json_from_response("{not valid json at all") is None


class TestFunctionCallMatchWithNestedParameters:
    """End-to-end: function_call_match relies on extract_json_from_response,
    so the nested-parameter bug previously broke name matching here too."""

    def test_nested_parameters_name_still_matches(self):
        response = 'Calling it now: {"name": "get_weather", "parameters": {"location": "nyc"}}'
        score = function_call_match(response, "get_weather", {"location": "nyc"})
        assert score == 1.0

    def test_multi_call_array_matches_against_first_call(self):
        response = '[{"name": "get_weather"}, {"name": "get_time"}]'
        score = function_call_match(response, "get_weather")
        assert score == 1.0
