"""Exponential-moving-average score folding: repeat samples damp noise instead of
the last sample overwriting (a genome scored 0.76 then 0.0 across two identical
evals in a live run — raw overwrite made fitness a lottery over the last roll)."""

from __future__ import annotations

from maistro_evolve.cycle import EvolutionConfig, EvolutionCycle
from maistro_evolve.diversity import _random_genome


def _fold(genome, score, stub=False, alpha=0.5):
    EvolutionCycle._fold_score(genome, "code_rsi", score, stub, alpha)


def test_first_sample_stands_alone() -> None:
    g = _random_genome()
    _fold(g, 0.76)
    assert g.eval_scores["code_rsi"] == 0.76
    assert g.harness_params["eval_samples"]["code_rsi"] == 1


def test_resample_blends_instead_of_overwriting() -> None:
    g = _random_genome()
    _fold(g, 0.76)
    _fold(g, 0.0)  # the live noise case: same genome, unlucky second roll
    assert g.eval_scores["code_rsi"] == 0.38  # 0.5*0.0 + 0.5*0.76 — not 0.0
    _fold(g, 0.8)
    assert g.eval_scores["code_rsi"] == 0.59  # keeps damping toward the signal
    assert g.harness_params["eval_samples"]["code_rsi"] == 3


def test_alpha_one_restores_raw_overwrite() -> None:
    g = _random_genome()
    _fold(g, 0.76, alpha=1.0)
    _fold(g, 0.1, alpha=1.0)
    assert g.eval_scores["code_rsi"] == 0.1


def test_stub_never_dilutes_real_signal() -> None:
    g = _random_genome()
    _fold(g, 0.76)
    _fold(g, 0.0, stub=True)  # gateway hiccup — noise, not evidence (SPEC-202)
    assert g.eval_scores["code_rsi"] == 0.76
    assert g.harness_params["eval_samples"]["code_rsi"] == 1  # not counted


def test_stub_stands_in_only_when_no_real_score_exists() -> None:
    g = _random_genome()
    _fold(g, 0.0, stub=True)
    assert g.eval_scores["code_rsi"] == 0.0  # placeholder until a real sample
    _fold(g, 0.6)  # first real sample blends with the standing value
    assert g.eval_scores["code_rsi"] == 0.3


def test_config_validates_alpha_range() -> None:
    assert EvolutionConfig(eval_ema_alpha=1.0).eval_ema_alpha == 1.0
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EvolutionConfig(eval_ema_alpha=0.0)
    with pytest.raises(ValidationError):
        EvolutionConfig(eval_ema_alpha=1.5)
