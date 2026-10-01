from __future__ import annotations

from maistro_evolve.benchmarks.scoring import (
    contains_all,
    contains_any,
    ends_with,
    exact_match,
    extract_json_from_response,
    function_call_match,
    is_valid_json,
    json_field_match,
    judge_score,
    not_contains,
    sentence_count,
    starts_with,
    word_count,
)


class TestExactMatch:
    def test_matching(self):
        assert exact_match("Paris", "Paris") == 1.0

    def test_case_insensitive(self):
        assert exact_match("paris", "Paris") == 1.0

    def test_whitespace_stripped(self):
        assert exact_match("  Paris  ", "Paris") == 1.0

    def test_non_matching(self):
        assert exact_match("London", "Paris") == 0.0


class TestContains:
    def test_contains_any_found(self):
        assert contains_any("the quick brown fox", ["fox"]) == 1.0

    def test_contains_any_missing(self):
        assert contains_any("hello world", ["fox"]) == 0.0

    def test_contains_all(self):
        assert (
            contains_all("superposition and entanglement", ["superposition", "entanglement"]) == 1.0
        )

    def test_contains_all_partial(self):
        assert contains_all("superposition only", ["superposition", "entanglement"]) == 0.0


class TestNotContains:
    def test_absent(self):
        assert not_contains("hello world", ["evaporation"]) == 1.0

    def test_present(self):
        assert not_contains("evaporation happens", ["evaporation"]) == 0.0


class TestStartsEndsWith:
    def test_starts_with(self):
        assert starts_with("ANSWER: Paris", "ANSWER:") == 1.0

    def test_starts_with_fail(self):
        assert starts_with("Paris is the answer", "ANSWER:") == 0.0

    def test_ends_with(self):
        assert ends_with("The answer [END]", "[END]") == 1.0

    def test_ends_with_fail(self):
        assert ends_with("The answer", "[END]") == 0.0


class TestJsonValidation:
    def test_valid_json(self):
        assert is_valid_json('{"key": "value"}') == 1.0

    def test_invalid_json(self):
        assert is_valid_json("not json") == 0.0

    def test_json_field_match(self):
        assert json_field_match('{"name": "test"}', "name", "test") == 1.0

    def test_json_field_wrong_value(self):
        assert json_field_match('{"name": "other"}', "name", "test") == 0.0

    def test_json_field_missing(self):
        assert json_field_match('{"age": 5}', "name", "test") == 0.0


class TestSentenceWordCount:
    def test_sentence_count(self):
        assert sentence_count("First. Second. Third.") == 3

    def test_sentence_count_single(self):
        assert sentence_count("Just one") == 1

    def test_word_count(self):
        assert word_count("hello world foo") == 3


class TestExtractJson:
    def test_plain_json(self):
        result = extract_json_from_response('{"name": "test"}')
        assert result == {"name": "test"}

    def test_json_in_code_block(self):
        result = extract_json_from_response('```json\n{"name": "test"}\n```')
        assert result == {"name": "test"}

    def test_no_json(self):
        result = extract_json_from_response("no json here")
        assert result is None


class TestFunctionCallMatch:
    def test_json_simple_match(self):
        response = '{"name": "get_weather"}'
        score = function_call_match(response, "get_weather")
        assert score > 0.5

    def test_json_flat_params(self):
        response = '{"name": "set_timer", "duration": 30}'
        score = function_call_match(response, "set_timer")
        assert score > 0.5

    def test_completely_wrong(self):
        response = "I don't know"
        score = function_call_match(response, "get_weather")
        assert score == 0.0

    def test_wrong_function(self):
        response = '{"name": "send_email", "parameters": {"to": "a@b.com"}}'
        score = function_call_match(response, "get_weather")
        assert score < 0.3

    def test_no_json(self):
        score = function_call_match("I don't know", "get_weather")
        assert score == 0.0


class TestJudgeScore:
    def test_numeric_score(self):
        assert judge_score("Score: 8") >= 0.7

    def test_yes_no_ratio(self):
        assert judge_score("yes yes yes no") >= 0.5

    def test_correct_keyword(self):
        assert judge_score("This is correct.") >= 0.7

    def test_partially_keyword(self):
        assert judge_score("This is partially right.") >= 0.3

    def test_incorrect_keyword(self):
        assert judge_score("This is wrong.") <= 0.4

    def test_yes_no_uses_word_boundaries(self):
        # "yes"/"no" must be matched as whole words, not as substrings of
        # other words. "eyes" contains "yes" and "knowledge" contains "no",
        # but neither expresses a yes/no vote, so both should fall through to
        # the neutral default rather than skewing the ratio.
        assert judge_score("eyes") == 0.3
        assert judge_score("knowledge") == 0.3
