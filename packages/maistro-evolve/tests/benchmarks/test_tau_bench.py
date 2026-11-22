"""tau-bench proxy scoring tests — structured observed calls only (#852).

The historical implementation scored tool *mentions*: any available tool's
name appearing anywhere in the response counted as a call, so "I cannot
invoke refund_order" scored identically to invoking it, and prose patterns
like "call get_weather" were extracted as calls. These tests pin the
structured-only contract: only JSON call objects (`name`/`function`/
`action`) are observed, in scoring and in the turn simulator.
"""

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

    def test_prose_call_phrases_are_not_calls(self):
        # #852: the action/tool_call regexes are gone. Mentioning a tool in
        # prose — affirmatively or as a negation — is not an observed call.
        assert _extract_tool_calls_from_response("I will call lookup_order to find it.") == []
        assert _extract_tool_calls_from_response("I cannot invoke refund_order.") == []
        assert _extract_tool_calls_from_response("invoke refresh_token now") == []
        assert _extract_tool_calls_from_response('tool_call: "send_password_reset"') == []
        assert _extract_tool_calls_from_response("function_call: lookup_order") == []

    def test_name_concatenation_in_prose_is_not_a_call(self):
        response = "To do this you need get_account_balance and then search_flights."
        assert _extract_tool_calls_from_response(response) == []

    def test_no_matches_returns_empty_list(self):
        response = "Sorry, I cannot help with that request at all."
        assert _extract_tool_calls_from_response(response) == []

    def test_dedup_between_list_and_object_forms(self):
        response = '```json\n[{"name": "get_weather"}]\n```\nand separately {"name": "get_weather"}'
        result = _extract_tool_calls_from_response(response)
        assert result == ["get_weather"]


class TestScoreToolUsage:
    SAMPLE: ClassVar[dict[str, object]] = {
        "expected_tool_calls": ["get_account_balance"],
        "tools": [{"name": "get_account_balance"}],
    }

    def test_structured_call_scores_full(self):
        response = '```json\n{"name": "get_account_balance", "parameters": {}}\n```'
        score = _score_tool_usage(response, self.SAMPLE)
        assert score == pytest.approx(1.0)

    def test_prose_only_mention_scores_zero(self):
        # #852: "Sure, calling GET_ACCOUNT_BALANCE now." used to score full
        # marks through the substring mention path.
        response = "Sure, calling GET_ACCOUNT_BALANCE now."
        assert _score_tool_usage(response, self.SAMPLE) == 0.0

    def test_negation_prose_scores_zero(self):
        # #852 headline exploit: a refusal mentioning the tool must not pass.
        response = "I cannot invoke refund_order for you."
        sample = {
            "expected_tool_calls": ["refund_order"],
            "tools": [{"name": "refund_order"}],
        }
        assert _score_tool_usage(response, sample) == 0.0

    def test_case_insensitive_underscore_insensitive_name_match(self):
        sample = {
            "expected_tool_calls": ["get_account_balance"],
            "tools": [{"name": "GetAccountBalance"}],
        }
        response = '{"name": "GetAccountBalance"}'
        assert _score_tool_usage(response, sample) == pytest.approx(1.0)

    def test_wrong_structured_calls_reduce_precision_with_clamp(self):
        sample = {
            "expected_tool_calls": ["get_account_balance"],
            "tools": [{"name": f"wrong_{i}"} for i in range(6)],
        }
        calls = [{"name": "get_account_balance"}] + [{"name": f"wrong_{i}"} for i in range(6)]
        import json

        response = "```json\n" + json.dumps(calls) + "\n```"
        score = _score_tool_usage(response, sample)
        # recall 1.0; six wrong calls -> precision clamped to 0.0
        assert score == pytest.approx(1.0 * 0.7 + 0.0 * 0.3)

    def test_exact_full_match_score(self):
        sample = {
            "expected_tool_calls": ["lookup_order", "cancel_order"],
            "tools": [{"name": "lookup_order"}, {"name": "cancel_order"}],
        }
        response = '```json\n[{"name": "lookup_order"}, {"name": "cancel_order"}]\n```'
        assert _score_tool_usage(response, sample) == pytest.approx(1.0)

    def test_partial_match_with_one_wrong_call(self):
        sample = {
            "expected_tool_calls": ["lookup_order", "cancel_order"],
            "tools": [
                {"name": "lookup_order"},
                {"name": "cancel_order"},
                {"name": "unrelated_tool"},
            ],
        }
        response = '```json\n[{"name": "lookup_order"}, {"name": "unrelated_tool"}]\n```'
        # recall = 1/2, precision = 1 - 1*0.2 = 0.8
        assert _score_tool_usage(response, sample) == pytest.approx(0.5 * 0.7 + 0.8 * 0.3)

    def test_zero_match_score(self):
        sample = {
            "expected_tool_calls": ["lookup_order"],
            "tools": [{"name": "lookup_order"}, {"name": "totally_different"}],
        }
        response = '{"name": "totally_different"}'
        # recall 0.0, one wrong call -> precision 0.8
        assert _score_tool_usage(response, sample) == pytest.approx(0.0 * 0.7 + 0.8 * 0.3)

    def test_expected_empty_defaults_recall_to_one(self):
        sample = {
            "expected_tool_calls": [],
            "tools": [{"name": "some_tool"}],
        }
        response = '{"name": "some_tool"}'
        # recall defaults 1.0; some_tool is not expected -> precision 0.8
        assert _score_tool_usage(response, sample) == pytest.approx(1.0 * 0.7 + 0.8 * 0.3)

    def test_no_calls_at_all_scores_zero(self):
        assert _score_tool_usage("I don't know what to do here.", self.SAMPLE) == 0.0


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
    async def test_prose_mention_does_not_trigger_fake_tool_feedback(self, sample):
        # #852: "call get_account_balance" in prose used to be treated as an
        # invocation and fed a fabricated "Success" result back into the
        # conversation. Only structured JSON triggers the tool loop now.
        async def llm_call(messages, temperature, max_tokens):
            return "I will call get_account_balance for you."

        messages = [{"role": "user", "content": "what's my balance?"}]
        response, cost = await _simulate_turns(sample, messages, llm_call, {}, max_turns=3)
        assert response == "I will call get_account_balance for you."
        assert cost == pytest.approx(0.001)
        assert len(messages) == 1  # no fabricated tool-result turns appended

    @pytest.mark.asyncio
    async def test_structured_call_continues_then_terminates(self, sample):
        calls = []

        async def llm_call(messages, temperature, max_tokens):
            calls.append(1)
            if len(calls) == 1:
                return '{"name": "get_account_balance"}'
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
                return '{"name": "totally_unknown_tool_xyz"}'
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
            return '{"name": "get_account_balance"}'

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
                return '{"name": "get_account_balance"}'
            raise RuntimeError("boom on turn 2")

        messages = [{"role": "user", "content": "balance"}]
        response, cost = await _simulate_turns(sample, messages, llm_call, {}, max_turns=3)

        assert response == '{"name": "get_account_balance"}'
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
    async def test_structured_calls_yield_nonzero_score(self):
        genome = make_genome()

        # Emit a structured superset of every sample's expected calls so the
        # same response works across samples: recall may be < 1 on precision,
        # but the aggregate must stay positive now that prose mentions count
        # for nothing.
        all_tools = sorted(
            {tool["name"] for sample in TAU_BENCH_SAMPLES for tool in sample["tools"]}
        )
        payload = [{"name": name} for name in all_tools]

        async def llm_call(messages, temperature, max_tokens):
            import json

            return "```json\n" + json.dumps(payload) + "\n```"

        result = await run_tau_bench(genome, llm_call)

        assert result.benchmark == "proxy_tau_bench"
        assert result.samples_evaluated == len(TAU_BENCH_SAMPLES)
        assert result.metadata == {
            "total_samples": len(TAU_BENCH_SAMPLES),
            "fidelity": "proxy",
            "evidence": {"method": "structured-call-match", "outcomes": "simulated"},
        }
        assert result.cost_usd > 0.0
        assert result.score > 0.0

    @pytest.mark.asyncio
    async def test_prose_only_conversation_scores_zero(self):
        # #852 acceptance: prose-only tool names (and the historical
        # name-superset prose response) must score 0.0.
        genome = make_genome()

        async def llm_call(messages, temperature, max_tokens):
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
        assert result.samples_evaluated == len(TAU_BENCH_SAMPLES)
        assert result.score == 0.0

    @pytest.mark.asyncio
    async def test_outer_except_reachable_via_malformed_sample(self, monkeypatch):
        """
        The outer `except (TimeoutError, Exception): evaluated += 1` around the
        per-sample loop body in run_tau_bench is NOT reachable through
        _simulate_turns under normal conditions, because _simulate_turns has
        its own internal try/except that swallows all (TimeoutError, Exception)
        errors from llm_call and always returns a (str, float) tuple normally.

        However, the loop body also calls `_score_tool_usage(all_responses or
        response, sample)` which indexes sample["expected_tool_calls"]
        directly with `[]` (not `.get`). A malformed sample missing that key
        raises a KeyError *inside* the try block in run_tau_bench (but outside
        _simulate_turns, since _simulate_turns's exceptions are already caught
        internally).
        """
        monkeypatch.setattr(
            "maistro_evolve.benchmarks.tau_bench.TAU_BENCH_SAMPLES",
            [
                {
                    "id": "malformed",
                    "conversation": [{"role": "user", "content": "hi"}],
                    # "expected_tool_calls" intentionally omitted -> KeyError
                    # in _score_tool_usage
                    "tools": [{"name": "x"}],
                    "max_turns": 1,
                }
            ],
        )

        async def llm_call(messages, temperature, max_tokens):
            return '{"name": "x"}'

        genome = make_genome()
        result = await run_tau_bench(genome, llm_call)

        # The KeyError is caught by the outer except, evaluated still increments,
        # but no score is added for that sample.
        assert result.samples_evaluated == 1
        assert result.score == 0.0
        assert result.metadata == {
            "total_samples": 1,
            "fidelity": "proxy",
            "evidence": {"method": "structured-call-match", "outcomes": "simulated"},
        }
