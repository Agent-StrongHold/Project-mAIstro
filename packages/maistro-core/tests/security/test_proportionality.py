"""Tests for the proportionality ("need") critic in DAG shape review.

Covers the #1191 failure contract: explicit allow/deny judgments are
separable from judge unavailability (timeout, provider exception, malformed
envelope, malformed judgment), and no failure path is ever collapsed into an
affirmative allow.
"""

from __future__ import annotations

import json
from typing import Any

from maistro.security.dag_shape.proportionality import (
    LLMProportionalityJudge,
    ProportionalityJudge,
    ProportionalityVerdict,
    RuleProportionalityJudge,
)
from maistro.security.dag_shape.types import ProposedDagShape


def _shape() -> ProposedDagShape:
    return ProposedDagShape(
        objective="answer a one-line factual question",
        node_kinds=("scout", "coder", "reviewer", "architect", "extractor"),
        rationale="fan out to five specialists for a trivial lookup",
        estimated_cost=5.0,
    )


class _FakeLLMClient:
    def __init__(self, content: str) -> None:
        self._content = content

    async def complete(self, messages: list[dict[str, str]], model: str) -> dict[str, Any]:
        return {"choices": [{"message": {"content": self._content}}]}


class _RaisingLLMClient:
    async def complete(self, messages: list[dict[str, str]], model: str) -> dict[str, Any]:
        raise RuntimeError("provider unavailable")


class _TimingOutLLMClient:
    async def complete(self, messages: list[dict[str, str]], model: str) -> dict[str, Any]:
        raise TimeoutError("judge model did not answer in time")


class _ResponseLLMClient:
    """Returns a canned envelope verbatim, for malformed-envelope shapes."""

    def __init__(self, response: Any) -> None:
        self._response = response

    async def complete(self, messages: list[dict[str, str]], model: str) -> Any:
        return self._response


def test_rule_judge_always_justified() -> None:
    assert isinstance(RuleProportionalityJudge(), ProportionalityJudge)


async def test_rule_judge_returns_explicit_allow() -> None:
    verdict = await RuleProportionalityJudge().judge(_shape())
    assert verdict.justified is True
    assert verdict.disposition == "allow"


async def test_llm_judge_parses_explicit_allow_with_disposition() -> None:
    client = _FakeLLMClient(json.dumps({"justified": True, "add": [], "drop": [], "reason": "ok"}))
    judge = LLMProportionalityJudge(client)
    verdict = await judge.judge(_shape())
    assert verdict.justified is True
    assert verdict.disposition == "allow"
    assert verdict.reason == "ok"


async def test_unavailable_classmethod_is_not_affirmative_approval() -> None:
    """The unavailable verdict must fail safe on both readings: the boolean
    says not-justified and the disposition names the absence of a judgment."""
    verdict = ProportionalityVerdict.unavailable("judge_unavailable: anything")
    assert verdict.justified is False
    assert verdict.disposition == "unavailable"


async def test_llm_judge_parses_explicit_deny_with_disposition() -> None:
    payload = {
        "justified": False,
        "add": [],
        "drop": ["architect", "extractor"],
        "reason": "trivial lookup doesn't need five specialists",
    }
    client = _FakeLLMClient(json.dumps(payload))
    judge = LLMProportionalityJudge(client)
    verdict = await judge.judge(_shape())
    assert verdict.justified is False
    assert verdict.disposition == "deny"
    assert verdict.drop == ("architect", "extractor")
    assert "trivial" in verdict.reason


async def test_llm_judge_handles_fenced_json() -> None:
    payload = json.dumps({"justified": True, "add": [], "drop": [], "reason": "fine"})
    client = _FakeLLMClient(f"```json\n{payload}\n```")
    judge = LLMProportionalityJudge(client)
    verdict = await judge.judge(_shape())
    assert verdict.justified is True
    assert verdict.disposition == "allow"


async def test_llm_judge_timeout_is_unavailable_not_allow() -> None:
    """A model timeout is the absence of a judgment (#1191): disposition
    "unavailable", justified False — never ordinary allow evidence."""
    judge = LLMProportionalityJudge(_TimingOutLLMClient())
    verdict = await judge.judge(_shape())
    assert verdict.justified is False
    assert verdict.disposition == "unavailable"
    assert verdict.reason.startswith("judge_unavailable")
    assert "TimeoutError" in verdict.reason


async def test_llm_judge_provider_exception_is_unavailable_not_allow() -> None:
    judge = LLMProportionalityJudge(_RaisingLLMClient())
    verdict = await judge.judge(_shape())
    assert verdict.justified is False
    assert verdict.disposition == "unavailable"
    assert verdict.reason.startswith("judge_unavailable")
    assert "RuntimeError" in verdict.reason


async def test_llm_judge_malformed_response_envelope_is_unavailable() -> None:
    judge = LLMProportionalityJudge(_ResponseLLMClient({"choices": []}))
    verdict = await judge.judge(_shape())
    assert verdict.justified is False
    assert verdict.disposition == "unavailable"
    assert "envelope" in verdict.reason


async def test_llm_judge_non_string_content_is_unavailable() -> None:
    judge = LLMProportionalityJudge(
        _ResponseLLMClient({"choices": [{"message": {"content": {"justified": True}}}]})
    )
    verdict = await judge.judge(_shape())
    assert verdict.disposition == "unavailable"


async def test_llm_judge_non_dict_envelope_is_unavailable() -> None:
    judge = LLMProportionalityJudge(_ResponseLLMClient("503 Service Unavailable"))
    verdict = await judge.judge(_shape())
    assert verdict.disposition == "unavailable"


async def test_llm_judge_unparseable_judgment_is_unavailable_not_allow() -> None:
    """The old contract collapsed this into justified=True; #1191 makes it an
    explicit unavailability so it can never read as affirmative approval."""
    client = _FakeLLMClient("not json at all")
    judge = LLMProportionalityJudge(client)
    verdict = await judge.judge(_shape())
    assert verdict.justified is False
    assert verdict.disposition == "unavailable"
    assert "malformed judgment" in verdict.reason


async def test_llm_judge_missing_justified_key_is_unavailable_not_allow() -> None:
    """A JSON object that never states a verdict judged nothing; defaulting
    the key to True (the old behavior) was a silent allow."""
    client = _FakeLLMClient(json.dumps({"reason": "looks fine to me"}))
    judge = LLMProportionalityJudge(client)
    verdict = await judge.judge(_shape())
    assert verdict.justified is False
    assert verdict.disposition == "unavailable"


async def test_llm_judge_non_boolean_justified_is_unavailable() -> None:
    """`bool("false")` is True — coercing the field allowed a string no-reply
    to become an affirmative allow. Only an explicit boolean judges."""
    client = _FakeLLMClient(json.dumps({"justified": "false"}))
    judge = LLMProportionalityJudge(client)
    verdict = await judge.judge(_shape())
    assert verdict.justified is False
    assert verdict.disposition == "unavailable"


async def test_llm_judge_non_dict_json_is_unavailable() -> None:
    client = _FakeLLMClient('["justified", true]')
    judge = LLMProportionalityJudge(client)
    verdict = await judge.judge(_shape())
    assert verdict.disposition == "unavailable"


async def test_llm_judge_missing_add_drop_fields_default_sanely() -> None:
    client = _FakeLLMClient(json.dumps({"justified": True}))
    judge = LLMProportionalityJudge(client)
    verdict = await judge.judge(_shape())
    assert verdict.justified is True
    assert verdict.disposition == "allow"
    assert verdict.add == ()
    assert verdict.drop == ()


async def test_llm_judge_non_list_add_drop_is_tolerated() -> None:
    """A boolean verdict with junk add/drop fields still judges; the junk is
    dropped rather than raising out of parsing."""
    client = _FakeLLMClient(json.dumps({"justified": False, "add": 3, "drop": "scout"}))
    judge = LLMProportionalityJudge(client)
    verdict = await judge.judge(_shape())
    assert verdict.justified is False
    assert verdict.disposition == "deny"
    assert verdict.add == ()
    assert verdict.drop == ()
