"""A turn's token total says how many calls it summed (#717).

`usage.get("prompt_tokens", 0)` gave the same answer to two different
questions. A provider that returned no `usage` object -- a local model, a
streaming adapter that drops the trailer, a gateway that strips it -- produced
`(0, 0)`, and so did a provider that returned `{"prompt_tokens": 0}`. The pair
is then summed over the calls of a turn and stored on the `Outcome`, so a
multi-step turn where two of three calls reported usage is stored as a turn that
cost what those two cost, with nothing saying the third was never measured.

`usage_reported_calls` is the count beside the value ADR-083026-a91e asks for.
The token fields stay `int`: making them optional would ripple through
twenty-seven non-test files to draw a distinction the count already draws.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.agents.strategies.direct import DirectStrategy
from maistro.agents.strategies.react import ReactStrategy
from maistro.types.memory import Outcome

pytestmark = [pytest.mark.contract("behavioral")]


class _Scripted:
    """An LLM client returning prepared payloads, one per call.

    Written here rather than taken from `FauxProvider` because the case under
    test is a response with *no* `usage` key at all, and `FauxProvider` always
    emits one -- which is exactly why the conflation survived as long as it did.
    """

    def __init__(self, *responses: dict[str, Any]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def complete(self, messages: list[dict[str, Any]], model: str, **kw: Any) -> Any:
        del messages, model, kw
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response


def _message(content: str = "done", tool_calls: list[dict[str, Any]] | None = None) -> Any:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}


def _with_usage(prompt: int, completion: int, **rest: Any) -> dict[str, Any]:
    payload = _message(**rest)
    payload["usage"] = {"prompt_tokens": prompt, "completion_tokens": completion}
    return payload


_CALL = [{"id": "c1", "type": "function", "function": {"name": "echo", "arguments": "{}"}}]
_TOOLS = [{"type": "function", "function": {"name": "echo", "parameters": {}}}]


async def _echo(name: str, args: dict[str, Any], **kw: Any) -> str:
    del name, args, kw
    return "ok"


class TestADirectTurnCountsWhatReportedUsage:
    @pytest.mark.ac("SPEC-083026-6cef/AC-3")
    async def test_a_reporting_call_is_counted(self) -> None:
        result = await DirectStrategy().reason(
            [{"role": "user", "content": "hi"}], "m", _Scripted(_with_usage(11, 7))
        )

        assert (result.input_tokens, result.output_tokens) == (11, 7)
        assert result.usage_reported_calls == 1

    @pytest.mark.ac("SPEC-083026-6cef/AC-3")
    async def test_a_call_that_reported_nothing_is_counted_as_none(self) -> None:
        """The case the old spelling erased: zero tokens over zero reporting
        calls, not zero tokens measured."""
        result = await DirectStrategy().reason(
            [{"role": "user", "content": "hi"}], "m", _Scripted(_message())
        )

        assert (result.input_tokens, result.output_tokens) == (0, 0)
        assert result.usage_reported_calls == 0

    @pytest.mark.ac("SPEC-083026-6cef/AC-3")
    async def test_a_call_that_reported_zero_is_distinguishable_from_it(self) -> None:
        """Both turns store `(0, 0)`. Only the count separates them, which is
        the whole reason the column exists."""
        measured = await DirectStrategy().reason(
            [{"role": "user", "content": "hi"}], "m", _Scripted(_with_usage(0, 0))
        )
        unmeasured = await DirectStrategy().reason(
            [{"role": "user", "content": "hi"}], "m", _Scripted(_message())
        )

        assert (measured.input_tokens, measured.output_tokens) == (
            unmeasured.input_tokens,
            unmeasured.output_tokens,
        )
        assert measured.usage_reported_calls == 1
        assert unmeasured.usage_reported_calls == 0

    async def test_a_malformed_usage_object_counts_as_unreported(self) -> None:
        """A `usage` that is not a mapping, or whose values are not numbers, is
        a provider that did not report usage -- not one that reported zero."""
        result = await DirectStrategy().reason(
            [{"role": "user", "content": "hi"}], "m", _Scripted({**_message(), "usage": "n/a"})
        )

        assert result.usage_reported_calls == 0

    async def test_a_blocked_response_still_reports_its_count(self) -> None:
        """Warden replaces the content; the turn still cost what it cost, and
        still knows whether that cost was measured."""

        class _Blocking:
            async def scan(self, text: str, surface: str) -> Any:
                del text, surface

                class _V:
                    clean = False
                    flags = ("injection",)

                return _V()

        result = await DirectStrategy().reason(
            [{"role": "user", "content": "hi"}],
            "m",
            _Scripted(_with_usage(11, 7)),
            warden=_Blocking(),
        )

        assert result.usage_reported_calls == 1
        assert result.input_tokens == 11


class TestAMultiStepTurnCountsEveryReportingCall:
    @pytest.mark.ac("SPEC-083026-6cef/AC-4")
    async def test_three_calls_two_reporting_sum_the_two_and_say_two(self) -> None:
        llm = _Scripted(
            _with_usage(10, 1, content="", tool_calls=_CALL),
            _message(content="", tool_calls=_CALL),
            _with_usage(5, 2, content="done"),
        )

        result = await ReactStrategy(max_rounds=3).reason(
            [{"role": "user", "content": "hi"}],
            "m",
            llm,
            tools=_TOOLS,
            tool_executor=_echo,
        )

        assert llm.calls == 3
        assert (result.input_tokens, result.output_tokens) == (15, 3)
        assert result.usage_reported_calls == 2

    @pytest.mark.ac("SPEC-083026-6cef/AC-4")
    async def test_a_loop_where_nothing_reported_says_zero_calls(self) -> None:
        llm = _Scripted(_message(content="", tool_calls=_CALL), _message(content="done"))

        result = await ReactStrategy(max_rounds=3).reason(
            [{"role": "user", "content": "hi"}],
            "m",
            llm,
            tools=_TOOLS,
            tool_executor=_echo,
        )

        assert llm.calls == 2
        assert (result.input_tokens, result.output_tokens) == (0, 0)
        assert result.usage_reported_calls == 0

    async def test_a_single_round_loop_counts_its_one_call(self) -> None:
        result = await ReactStrategy(max_rounds=3).reason(
            [{"role": "user", "content": "hi"}], "m", _Scripted(_with_usage(4, 6))
        )

        assert result.usage_reported_calls == 1


class TestTheRecordSaysItsTotalsAreASum:
    @pytest.mark.ac("SPEC-083026-6cef/AC-5")
    def test_the_outcome_documents_the_token_pair_as_a_per_turn_sum(self) -> None:
        doc = Outcome.__doc__ or ""

        assert "sum" in doc.lower()
        assert "#55" in doc

    @pytest.mark.ac("SPEC-083026-6cef/AC-5")
    def test_an_outcome_that_was_never_counted_says_none_not_zero(self) -> None:
        assert Outcome().usage_reported_calls is None
