"""SPEC-070126-9d37 AC-3/4/5: greedy_merge — competitive + complementary.

The merge takes candidates and an ``apply`` that reports whether a candidate's
patch lands cleanly onto the accumulating result. A clean land ⇒ kept (a
different region — complementary); a conflict ⇒ dropped (same region — the
higher-scored candidate already won). Candidates are applied highest-score first.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from maistro_rsi.merge import greedy_merge


@dataclass
class _Cand:
    composite: float
    region: str


def _region_apply():
    """A fake apply: a patch lands unless its region is already occupied."""
    occupied: set[str] = set()

    def apply(c: _Cand) -> bool:
        if c.region in occupied:
            return False
        occupied.add(c.region)
        return True

    return apply


@pytest.mark.ac("SPEC-070126-9d37/AC-3")
def test_all_complementary_are_kept() -> None:
    cands = [_Cand(0.6, "a"), _Cand(0.9, "b"), _Cand(0.7, "c")]
    kept = greedy_merge(cands, _region_apply(), key=lambda c: c.composite)
    # Distinct regions ⇒ all kept, in score-descending order.
    assert [c.region for c in kept] == ["b", "c", "a"]


@pytest.mark.ac("SPEC-070126-9d37/AC-4")
def test_same_region_keeps_only_highest() -> None:
    cands = [_Cand(0.5, "x"), _Cand(0.9, "x"), _Cand(0.7, "x")]
    kept = greedy_merge(cands, _region_apply(), key=lambda c: c.composite)
    assert len(kept) == 1
    assert kept[0].composite == 0.9


@pytest.mark.ac("SPEC-070126-9d37/AC-5")
def test_mixed_complementary_and_competitive() -> None:
    # Two compete on region A (0.9 wins, 0.7 dropped); B is disjoint and kept.
    cands = [_Cand(0.9, "A"), _Cand(0.7, "A"), _Cand(0.6, "B")]
    kept = greedy_merge(cands, _region_apply(), key=lambda c: c.composite)
    assert [(c.composite, c.region) for c in kept] == [(0.9, "A"), (0.6, "B")]


def test_default_key_is_composite_attr() -> None:
    cands = [_Cand(0.3, "a"), _Cand(0.8, "b")]
    kept = greedy_merge(cands, _region_apply())
    assert [c.composite for c in kept] == [0.8, 0.3]
