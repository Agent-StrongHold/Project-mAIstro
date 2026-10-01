from __future__ import annotations

from typing import ClassVar

import pytest

from maistro_evolve.benchmarks.datasets import TAU_BENCH_SAMPLES
from maistro_evolve.benchmarks.tau_bench import (
    _extract_tool_calls_from_response,
    _score_tool_usage,
    _simulate_turns,
    run_tau_bench,
)

from .conftest import make_genome


class TestExtractToolCallsFromResponse:
    def test_json_list_of_dicts_extracts_in_order_deduped(self):
        # NOTE: extract_json_from_response tries the bare `\{[^{}]*\}` pattern
        # before the bare `\[[^\[\]]*\]` pattern, so an unfenced JSON array of
        # dicts like '[{"a":1}, {"b":2}]' actually gets matched as a single
        # dict by the brace pattern first (extracting only the first element).
        # Wrapping in a ```json fenced block makes the fenced-block pattern
        # (tried first) capture the whole array correctly.
        response = (
            '```json\n[{"name": "get_weather"}, {"function": "search_flights"}, '
            '{"action": "get_weather"}]\n```'
        )
        result = _extract_tool_calls_from_response(response)
        assert result == ["get_weather", "search_flights"]

    def test_bare_json_dict_single_call(self):
        response = '{"name": "get_account_balance"}'
        result = _extract_tool_calls_from_response(response)
        assert result == ["get_account_balance"]

    def test_action_regex_pattern(self):
        response = "I will call lookup_order to find the order."
        result = _extract_tool_calls_from_response(response)
        assert result == ["lookup_order"]

    def test_action_regex_pattern_variants(self):
        assert _extract_tool_calls_from_response("invoke refresh_token") == ["refresh_token"]
        assert _extract_tool_calls_from_response("use get_weather") == ["get_weather"]
        assert _extract_tool_calls_from_response("execute cancel_order") == ["cancel_order"]
        assert _extract_tool_calls_from_response("run search_flights") == ["search_flights"]

    def test_tool_call_regex_pattern(self):
        response = 'tool_call: "send_password_reset"'
        result = _extract_tool_calls_from_response(response)
        assert result == ["send_password_reset"]

    def test_function_call_and_action_keyword_patterns(self):
        assert _extract_tool_calls_from_response("function_call: lookup_order") == ["lookup_order"]
        assert _extract_tool_calls_from_response("action: cancel_order") == ["cancel_order"]

    def test_no_matches_returns_empty_list(self):
        response = "Sorry, I cannot help with that request at all."
        assert _extract_tool_calls_from_response(response) == []

    def test_dedup_across_sources_precise(self):
        # "get_weather" appears via JSON extraction AND via the action regex.
        # JSON source comes first in the concatenation, so it should win the
        # first-occurrence ordering, and the regex duplicate must be dropped.
        response = '{"name": "get_weather"} now I will call get_weather to confirm.'
        result = _extract_tool_calls_from_response(response)
        assert result == ["get_weather"]
        assert result.count("get_weather") == 1


class TestScoreToolUsage:
    SAMPLE: ClassVar[dict[str, object]] = {
        "expected_tool_calls": ["get_account_balance"],
        "tools": [{"name": "get_account_balance"}],
    }

    def test_mentions_available_tool_by_substring_case_insensitive(self):
        response = "Sure, calling GET_ACCOUNT_BALANCE now."
        score = _score_tool_usage(response, self.SAMPLE)
        # mentioned via substring match (case-insensitive); also matched by exact equality
        # recall = 1/1 = 1.0, no wrong calls -> precision = 1.0
        assert score == pytest.approx(1.0 * 0.7 + 1.0 * 0.3)

    def test_no_mention_at_all_returns_zero(self):
        response = "I don't know what to do here."
        score = _score_tool_usage(response, self.SAMPLE)
        assert score == 0.0

    def test_exact_match_case_insensitive_and_underscore_stripped(self):
        sample = {
            "expected_tool_calls": ["get_account_balance"],
            "tools": [{"name": "GetAccountBalance"}],
        }
        # response mentions the tool exactly as-is (case differs, underscores differ)
        response = "I will call GetAccountBalance"
        score = _score_tool_usage(response, sample)
        # extracted via action regex -> "GetAccountBalance"; mentioned_tools via substring
        # match too. expected_name "get_account_balance" vs mentioned "GetAccountBalance":
        # lower() differs but replace("_","").lower() equality holds -> matched.
        assert score == pytest.approx(1.0)

    def test_wrong_calls_reduce_precision_with_clamp(self):
        sample = {
            "expected_tool_calls": ["get_account_balance"],
            "tools": [
                {"name": "get_account_balance"},
                {"name": "wrong_one"},
                {"name": "wrong_two"},
                {"name": "wrong_three"},
                {"name": "wrong_four"},
                {"name": "wrong_five"},
                {"name": "wrong_six"},
            ],
        }
        response = (
            "call get_account_balance call wrong_one call wrong_two call wrong_three "
            "call wrong_four call wrong_five call wrong_six"
        )
        score = _score_tool_usage(response, sample)
        # recall: matched = 1 (get_account_balance), expected len 1 -> recall = 1.0
        # wrong_calls = 6 -> precision = 1.0 - 6*0.2 = -0.2 -> clamped to 0.0
        assert score == pytest.approx(1.0 * 0.7 + 0.0 * 0.3)

    def test_exact_full_match_score(self):
        sample = {
            "expected_tool_calls": ["lookup_order", "cancel_order"],
            "tools": [{"name": "lookup_order"}, {"name": "cancel_order"}],
        }
        response = "call lookup_order call cancel_order"
        score = _score_tool_usage(response, sample)
        # recall = 2/2 = 1.0, no wrong calls -> precision = 1.0
        assert score == pytest.approx(1.0)

    def test_partial_match_with_one_wrong_call(self):
        sample = {
            "expected_tool_calls": ["lookup_order", "cancel_order"],
            "tools": [
                {"name": "lookup_order"},
                {"name": "cancel_order"},
                {"name": "unrelated_tool"},
            ],
        }
        response = "call lookup_order call unrelated_tool"
        score = _score_tool_usage(response, sample)
        # all_mentioned = ["lookup_order", "unrelated_tool"]
        # matched: lookup_order matches expected -> 1; cancel_order has no match -> 0
        # recall = 1/2 = 0.5
        # wrong_calls: unrelated_tool doesn't match any expected -> 1 wrong call
        # precision = 1.0 - 1*0.2 = 0.8
        assert score == pytest.approx(0.5 * 0.7 + 0.8 * 0.3)

    def test_zero_match_score(self):
        sample = {
            "expected_tool_calls": ["lookup_order"],
            "tools": [{"name": "lookup_order"}, {"name": "totally_different"}],
        }
        response = "call totally_different"
        score = _score_tool_usage(response, sample)
        # all_mentioned = ["totally_different"]; matched = 0 -> recall = 0/1 = 0.0
        # wrong_calls = 1 -> precision = 0.8
        assert score == pytest.approx(0.0 * 0.7 + 0.8 * 0.3)

    def test_expected_empty_defaults_recall_to_one(self):
        sample = {
            "expected_tool_calls": [],
            "tools": [{"name": "some_tool"}],
        }
        response = "call some_tool"
        score = _score_tool_usage(response, sample)
        # expected is empty -> recall = 1.0 (ternary default)
        # wrong_calls: "some_tool" mentioned but not any(e matches m) since expected is
        # empty -> any([]) is False -> not False -> True -> it IS a wrong call.
        # precision = 1.0 - 1*0.2 = 0.8
        assert score == pytest.approx(1.0 * 0.7 + 0.8 * 0.3)


class TestSimulateTurns:
    @pytest.fixture
    def sample(self):
        return TAU_BENCH_SAMPLES[0]  # tau_01: get_account_balance, max_turns=3

    @pytest.mark.asyncio
    async def test_no_tool_calls_breaks_immediately(self, sample):
        async def llm_call(messages, temperature, max_tokens):
            return "I'm sorry, I cannot help with that."

        messages = [{"role": "user", "content": "hi"}]
        response, cost = await _simulate_turns(sample, messages, llm_call, {}, max_turns=3)
        assert response == "I'm sorry, I cannot help with that."
        assert cost == pytest.approx(0.001)

    @pytest.mark.asyncio
    async def test_tool_call_matching_known_tool_continues_then_terminates(self, sample):
        calls = []

        async def llm_call(messages, temperature, max_tokens):
            calls.append(1)
            if len(calls) == 1:
                return "call get_account_balance"
            return "Here is your balance: $100. Done."

        messages = [{"role": "user", "content": "what's my balance?"}]
        response, cost = await _simulate_turns(sample, messages, llm_call, {}, max_turns=3)

        assert cost == pytest.approx(0.002)
        assert response == "Here is your balance: $100. Done."
        # turn 1 appended assistant + user (tool result) messages = 2 new messages
        assert len(messages) == 1 + 2

    @pytest.mark.asyncio
    async def test_unknown_tool_hits_for_else_tool_not_found_branch(self, sample):
        calls = []

        async def llm_call(messages, temperature, max_tokens):
            calls.append(1)
            if len(calls) == 1:
                return "call totally_unknown_tool_xyz"
            return "Done, no more tools needed."

        messages = [{"role": "user", "content": "do something"}]
        _response, cost = await _simulate_turns(sample, messages, llm_call, {}, max_turns=3)

        assert cost == pytest.approx(0.002)
        # the tool-result message (2nd appended message) should report "not found"
        tool_result_message = messages[2]
        assert "Tool not found" in tool_result_message["content"]
        assert "totally_unknown_tool_xyz" in tool_result_message["content"]

    @pytest.mark.asyncio
    async def test_max_turns_exhausted_without_break(self, sample):
        call_count = []

        async def llm_call(messages, temperature, max_tokens):
            call_count.append(1)
            return "call get_account_balance"

        messages = [{"role": "user", "content": "balance please"}]
        _response, cost = await _simulate_turns(sample, messages, llm_call, {}, max_turns=2)

        assert len(call_count) == 2
        assert cost == pytest.approx(0.002)

    @pytest.mark.asyncio
    async def test_exception_on_first_turn_breaks_with_empty_response(self, sample):
        async def llm_call(messages, temperature, max_tokens):
            raise RuntimeError("boom")

        messages = [{"role": "user", "content": "hi"}]
        response, cost = await _simulate_turns(sample, messages, llm_call, {}, max_turns=3)

        assert response == ""
        assert cost == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_exception_on_second_turn_keeps_partial_cost_and_last_response(self, sample):
        calls = []

        async def llm_call(messages, temperature, max_tokens):
            calls.append(1)
            if len(calls) == 1:
                return "call get_account_balance"
            raise RuntimeError("boom on turn 2")

        messages = [{"role": "user", "content": "balance"}]
        response, cost = await _simulate_turns(sample, messages, llm_call, {}, max_turns=3)

        assert response == "call get_account_balance"
        assert cost == pytest.approx(0.001)

    @pytest.mark.asyncio
    async def test_model_config_defaults_used_when_missing(self, sample):
        seen_kwargs = {}

        async def llm_call(messages, temperature, max_tokens):
            seen_kwargs["temperature"] = temperature
            seen_kwargs["max_tokens"] = max_tokens
            return "no tools here"

        messages = [{"role": "user", "content": "hi"}]
        await _simulate_turns(sample, messages, llm_call, {}, max_turns=1)

        assert seen_kwargs["temperature"] == 0.2
        assert seen_kwargs["max_tokens"] == 1024


class TestRunTauBench:
    @pytest.mark.asyncio
    async def test_llm_call_none_raises(self):
        genome = make_genome()
        with pytest.raises(ValueError, match="requires an llm_call"):
            await run_tau_bench(genome, None)

    @pytest.mark.asyncio
    async def test_normal_flow_with_fake_llm_call_yields_nonzero_score(self):
        genome = make_genome()

        async def llm_call(messages, temperature, max_tokens):
            # Respond by naming the first expected tool call for whatever sample
            # is currently being processed, inferred from the system prompt's
            # tools list isn't directly accessible here, so just always emit a
            # generic tool-call phrase that matches across samples via name.
            # We inspect the most recent user message content embedded tool names
            # indirectly isn't feasible; instead always terminate after one turn
            # with a response naming common tool keywords across samples.
            return (
                "call get_account_balance call search_flights call get_weather_forecast "
                "call send_password_reset call lookup_order call cancel_order "
                "call get_return_policy call initiate_return call check_availability "
                "call create_meeting call check_known_issues call create_support_ticket "
                "call update_shipping_address call search_products call list_accounts "
                "call create_recurring_transfer call search_restaurants call book_restaurant "
                "call subscribe_newsletter"
            )

        result = await run_tau_bench(genome, llm_call)

        assert result.benchmark == "proxy_tau_bench"
        assert result.samples_evaluated == 12
        assert result.metadata == {"total_samples": 12, "fidelity": "proxy"}
        assert result.cost_usd > 0.0
        assert result.score > 0.0

    @pytest.mark.asyncio
    async def test_outer_except_reachable_via_malformed_sample(self, monkeypatch):
        """
        The outer `except (TimeoutError, Exception): evaluated += 1` around the
        per-sample loop body in run_tau_bench is NOT reachable through
        _simulate_turns under normal conditions, because _simulate_turns has its
        own internal try/except that swallows all (TimeoutError, Exception)
        errors from llm_call and always returns a (str, float) tuple normally.

        However, the loop body also calls `sample.get("max_turns", 3)` (safe,
        .get with default) and `_score_tool_usage(all_responses or response, sample)`
        which indexes sample["expected_tool_calls"] and sample["tools"] directly
        with `[]` (not `.get`). A malformed sample missing "tools" raises a
        KeyError *inside* the try block in run_tau_bench (but outside
        _simulate_turns, since _simulate_turns's exceptions are already caught
        internally) -- demonstrating the outer except is reachable, just not via
        _simulate_turns's failure modes.
        """
        monkeypatch.setattr(
            "maistro_evolve.benchmarks.tau_bench.TAU_BENCH_SAMPLES",
            [
                {
                    "id": "malformed",
                    "conversation": [{"role": "user", "content": "hi"}],
                    "expected_tool_calls": ["x"],
                    # "tools" key intentionally omitted -> KeyError in _score_tool_usage
                    "max_turns": 1,
                }
            ],
        )

        async def llm_call(messages, temperature, max_tokens):
            return "no tools mentioned"

        genome = make_genome()
        result = await run_tau_bench(genome, llm_call)

        # The KeyError is caught by the outer except, evaluated still increments,
        # but no score is added for that sample.
        assert result.samples_evaluated == 1
        assert result.score == 0.0
        assert result.metadata == {"total_samples": 1, "fidelity": "proxy"}
