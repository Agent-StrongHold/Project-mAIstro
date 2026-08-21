"""SPEC-070126-9d37 AC-1: Competitor parsing.

A competitor is a fixer configuration (a projection of an evolve NodeGenome):
a model alias and an optional temperature. `parse_competitors` reads the
`model@temp,model,...` CLI form.
"""

from __future__ import annotations

import pytest

from maistro_rsi.competitors import Competitor, parse_competitors


@pytest.mark.ac("SPEC-070126-9d37/AC-1")
def test_parse_models_and_temps() -> None:
    got = parse_competitors("devstral-medium@0.2, codestral , mistral-medium@0.9")
    assert got == [
        Competitor(model="devstral-medium", temperature=0.2),
        Competitor(model="codestral", temperature=None),
        Competitor(model="mistral-medium", temperature=0.9),
    ]


@pytest.mark.ac("SPEC-070126-9d37/AC-1")
def test_empty_string_is_empty_list() -> None:
    assert parse_competitors("") == []
    assert parse_competitors("   ") == []


def test_bare_model_has_no_temperature() -> None:
    (c,) = parse_competitors("codestral")
    assert c.model == "codestral"
    assert c.temperature is None


def test_label_defaults_to_model_and_temp() -> None:
    (c,) = parse_competitors("codestral@0.5")
    assert "codestral" in c.label and "0.5" in c.label


def test_reasoning_effort_participates_in_equality_prompt_and_label_do_not() -> None:
    base = Competitor(model="o3", reasoning_effort="high")
    assert base == Competitor(model="o3", reasoning_effort="high")
    assert base != Competitor(model="o3", reasoning_effort="low")
    assert base == Competitor(
        model="o3", reasoning_effort="high", prompt="ignored", label="ignored"
    )
