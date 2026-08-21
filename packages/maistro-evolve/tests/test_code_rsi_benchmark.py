"""SPEC-070126-9d37 AC-10/11: the code_rsi evolve benchmark.

A genome's code_rsi score = the composite of the RSI Scorecard for the code fix
that genome's config produced, with evolve hard-gate parity (a vetoed gate ⇒ 0)
and SPEC-202 honesty (never score against a stub/absent suite).
"""

from __future__ import annotations

import pytest

from maistro_evolve.code_rsi import code_rsi_score, evaluate_code_rsi
from maistro_evolve.types import EvalResult


@pytest.mark.ac("SPEC-070126-9d37/AC-10")
def test_score_is_composite_when_accepted() -> None:
    score, meta = code_rsi_score(accepted=True, composite=0.6355)
    assert score == 0.6355
    assert meta["accepted"] is True


@pytest.mark.ac("SPEC-070126-9d37/AC-10")
def test_score_is_zero_when_gate_vetoed() -> None:
    # A high composite is irrelevant if a gate failed — evolve hard-gate parity.
    score, meta = code_rsi_score(accepted=False, composite=0.9)
    assert score == 0.0
    assert meta["accepted"] is False


@pytest.mark.ac("SPEC-070126-9d37/AC-11")
def test_stub_signal_scores_zero_and_is_flagged() -> None:
    score, meta = code_rsi_score(accepted=True, composite=0.8, is_stub=True)
    assert score == 0.0
    assert meta["stub"] is True


@pytest.mark.ac("SPEC-070126-9d37/AC-10")
def test_evaluate_returns_eval_result() -> None:
    def run_and_score(genome, target):
        return (True, 0.62, False)  # accepted, composite, is_stub

    res = evaluate_code_rsi("genome-id", "packages/x/src/x.py", run_and_score)
    assert isinstance(res, EvalResult)
    assert res.benchmark == "code_rsi"
    assert res.score == 0.62


@pytest.mark.ac("SPEC-070126-9d37/AC-11")
def test_evaluate_stub_scores_zero() -> None:
    res = evaluate_code_rsi("g", "x.py", lambda g, t: (True, 0.7, True))
    assert res.score == 0.0
    assert res.metadata.get("stub") is True


@pytest.mark.ac("ADR-070126-6386/stage3")
def test_code_rsi_only_genome_drives_fitness() -> None:
    # A run need not cover all 8 standard benchmarks: a code_rsi-only genome must
    # pass the hard gate and get a real, code_rsi-driven fitness (was 0.0 when the
    # gate required every standard benchmark).
    from maistro_evolve.diversity import _random_genome
    from maistro_evolve.fitness import _check_hard_gate, _weighted_eval_score, compute_fitness

    genome = _random_genome()
    genome.eval_scores = {"code_rsi": 0.636}
    passed, failures = _check_hard_gate(genome)
    assert passed and not failures
    assert _weighted_eval_score(genome) == pytest.approx(0.636)
    assert compute_fitness(genome, [genome]).total > 0.0

    # An empty evaluation still fails the gate (never breed an unscored genome).
    genome.eval_scores = {}
    assert _check_hard_gate(genome)[0] is False
