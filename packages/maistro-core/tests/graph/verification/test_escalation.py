"""Cheap-first, quality-triggered escalation decisions and policy parsing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maistro.graph.verification import (
    ModelLadder,
    QualityGate,
    decide_escalation,
    escalation_from_policy,
)


def test_ladder_orders_cheap_to_strong() -> None:
    ladder = ModelLadder(models=("flash", "pro", "ultra"))
    assert ladder.cheapest == "flash"
    assert ladder.strongest == "ultra"
    assert ladder.index_of("pro") == 1
    assert ladder.next_after("flash") == "pro"
    assert ladder.next_after("ultra") is None
    assert ladder.next_after("not-a-rung") is None


def test_ladder_rejects_duplicates_and_blank_rungs() -> None:
    with pytest.raises(ValidationError):
        ModelLadder(models=("flash", "flash"))
    with pytest.raises(ValidationError):
        ModelLadder(models=("flash", " "))


def test_gate_floor_is_inclusive() -> None:
    gate = QualityGate(floor=0.7)
    assert gate.passes(0.7)
    assert gate.passes(0.9)
    assert not gate.passes(0.69)


def test_quality_pass_means_no_escalation() -> None:
    decision = decide_escalation(
        ModelLadder(models=("cheap", "strong")),
        "cheap",
        0.9,
        QualityGate(floor=0.7),
    )
    assert not decision.escalate
    assert decision.to_model is None
    assert decision.reason == "quality gate passed"
    assert not decision.exhausted


def test_short_quality_escalates_one_rung() -> None:
    decision = decide_escalation(
        ModelLadder(models=("cheap", "strong")),
        "cheap",
        0.4,
        QualityGate(floor=0.7),
    )
    assert decision.escalate
    assert decision.from_model == "cheap"
    assert decision.to_model == "strong"


def test_first_visit_without_a_known_model_starts_from_the_cheapest_rung() -> None:
    decision = decide_escalation(
        ModelLadder(models=("cheap", "strong")),
        None,
        0.4,
        QualityGate(floor=0.7),
    )
    assert decision.escalate
    assert decision.to_model == "strong"


def test_exhausted_ladder_accepts_the_shortfall() -> None:
    decision = decide_escalation(
        ModelLadder(models=("cheap", "strong")),
        "strong",
        0.4,
        QualityGate(floor=0.7),
    )
    assert not decision.escalate
    assert decision.reason == "ladder exhausted"
    assert decision.exhausted


def test_policy_absent_returns_none() -> None:
    assert escalation_from_policy({}) is None
    assert escalation_from_policy({"max_attempts": 3}) is None


def test_policy_parses_ladder_and_floor() -> None:
    ladder, gate = escalation_from_policy(
        {"escalation_ladder": {"models": ["flash", "pro"], "quality_floor": 0.8}}
    )
    assert ladder.models == ("flash", "pro")
    assert gate.floor == 0.8


def test_policy_missing_models_raises() -> None:
    with pytest.raises(ValueError, match="models"):
        escalation_from_policy({"escalation_ladder": {"quality_floor": 0.8}})


def test_policy_missing_floor_raises() -> None:
    with pytest.raises(ValueError, match="quality_floor"):
        escalation_from_policy({"escalation_ladder": {"models": ["flash"]}})


def test_policy_non_mapping_raises() -> None:
    with pytest.raises(ValueError, match="mapping"):
        escalation_from_policy({"escalation_ladder": ["flash"]})


def test_policy_out_of_range_floor_raises() -> None:
    with pytest.raises(ValidationError):
        escalation_from_policy({"escalation_ladder": {"models": ["flash"], "quality_floor": 1.5}})
