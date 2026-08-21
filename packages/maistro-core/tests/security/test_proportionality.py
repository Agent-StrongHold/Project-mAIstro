"""Tests for the proportionality ("need") critic in DAG shape review."""

from __future__ import annotations

import json
from typing import Any

from maistro.security.dag_shape.proportionality import (
    LLMProportionalityJudge,
    ProportionalityJudge,
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


def test_rule_judge_always_justified() -> None:
    assert isinstance(RuleProportionalityJudge(), ProportionalityJudge)


async def test_rule_judge_returns_justified() -> None:
    verdict = await RuleProportionalityJudge().judge(_shape())
    assert verdict.justified is True


async def test_llm_judge_parses_justified_response() -> None:
    client = _FakeLLMClient(json.dumps({"justified": True, "add": [], "drop": [], "reason": "ok"}))
    judge = LLMProportionalityJudge(client)
    verdict = await judge.judge(_shape())
    assert verdict.justified is True
    assert verdict.reason == "ok"


async def test_llm_judge_parses_unjustified_with_add_drop() -> None:
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
    assert verdict.drop == ("architect", "extractor")
    assert "trivial" in verdict.reason


async def test_llm_judge_handles_fenced_json() -> None:
    payload = json.dumps({"justified": True, "add": [], "drop": [], "reason": "fine"})
    client = _FakeLLMClient(f"```json\n{payload}\n```")
    judge = LLMProportionalityJudge(client)
    verdict = await judge.judge(_shape())
    assert verdict.justified is True


async def test_llm_judge_unparseable_defaults_to_justified() -> None:
    client = _FakeLLMClient("not json at all")
    judge = LLMProportionalityJudge(client)
    verdict = await judge.judge(_shape())
    assert verdict.justified is True
    assert verdict.reason == "unparseable_judgment"


async def test_llm_judge_provider_error_defaults_to_justified() -> None:
    judge = LLMProportionalityJudge(_RaisingLLMClient())
    verdict = await judge.judge(_shape())
    assert verdict.justified is True
    assert verdict.reason == "judgment_failed"


async def test_llm_judge_missing_fields_default_sanely() -> None:
    client = _FakeLLMClient(json.dumps({}))
    judge = LLMProportionalityJudge(client)
    verdict = await judge.judge(_shape())
    assert verdict.justified is True
    assert verdict.add == ()
    assert verdict.drop == ()
