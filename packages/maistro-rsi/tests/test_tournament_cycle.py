"""SPEC-070126-9d37 AC-6/7/8: select_with_fallback — the cycle's decision.

Wraps greedy_merge with a validation step: when 2+ candidates merge into a new
combined result, re-score it; if the combination regresses a gate, fall back to
the single highest-scored candidate (which is already known-good).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from maistro_rsi.merge import select_with_fallback


@dataclass
class _Cand:
    composite: float
    region: str


def _region_apply():
    occupied: set[str] = set()

    def apply(c: _Cand) -> bool:
        if c.region in occupied:
            return False
        occupied.add(c.region)
        return True

    return apply


@pytest.mark.ac("SPEC-070126-9d37/AC-6")
def test_same_region_promotes_single_best() -> None:
    cands = [_Cand(0.9, "X"), _Cand(0.7, "X"), _Cand(0.5, "X")]

    # rescore must never be consulted when only one candidate survives.
    def rescore(_kept):  # pragma: no cover - must not run
        raise AssertionError("rescore called for a single-candidate result")

    res = select_with_fallback(cands, _region_apply(), rescore, key=lambda c: c.composite)
    assert [c.composite for c in res.kept] == [0.9]
    assert res.merged is False
    assert res.fallback is False


@pytest.mark.ac("SPEC-070126-9d37/AC-7")
def test_complementary_pair_both_kept_when_merge_valid() -> None:
    cands = [_Cand(0.8, "A"), _Cand(0.6, "B")]
    res = select_with_fallback(cands, _region_apply(), lambda kept: True, key=lambda c: c.composite)
    assert [c.region for c in res.kept] == ["A", "B"]
    assert res.merged is True
    assert res.fallback is False


@pytest.mark.ac("SPEC-070126-9d37/AC-8")
def test_regressing_merge_falls_back_to_top() -> None:
    cands = [_Cand(0.8, "A"), _Cand(0.6, "B")]
    # The 2-way combination regresses a gate ⇒ keep only the top candidate.
    res = select_with_fallback(
        cands, _region_apply(), lambda kept: False, key=lambda c: c.composite
    )
    assert [c.composite for c in res.kept] == [0.8]
    assert res.fallback is True


def test_no_accepted_candidates_yields_empty() -> None:
    res = select_with_fallback([], _region_apply(), lambda kept: True, key=lambda c: c.composite)
    assert res.kept == []
    assert res.merged is False
