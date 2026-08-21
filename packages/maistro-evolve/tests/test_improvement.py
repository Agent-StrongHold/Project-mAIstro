"""ImprovementKind taxonomy: budget tiers, the maturity-ladder ordering, parsing."""

from __future__ import annotations

from maistro_evolve.improvement import BudgetTier, ImprovementKind

_UNLOCKED = {ImprovementKind.SPEC, ImprovementKind.BACKLOG, ImprovementKind.FEATURE}


def test_spec_backlog_and_feature_unlock_the_big_budget() -> None:
    for kind in ImprovementKind:
        expected = BudgetTier.UNLOCKED if kind in _UNLOCKED else BudgetTier.BOUNDED
        assert kind.budget is expected, kind


def test_priority_is_correctness_then_contracted_then_proposed_then_growth() -> None:
    order = sorted(ImprovementKind, key=lambda k: k.priority)
    assert order[0] is ImprovementKind.BUG_FIX
    assert order[-1] is ImprovementKind.DOC
    # The maturity ladder: correctness → finish CONTRACTED spec work → propose
    # new contracts (backlog) → un-specced growth (feature) → edge.
    assert (
        ImprovementKind.BUG_FIX.priority
        < ImprovementKind.NEW_TEST.priority
        < ImprovementKind.ASSERTION.priority
        < ImprovementKind.SPEC.priority
        < ImprovementKind.BACKLOG.priority
        < ImprovementKind.FEATURE.priority
        < ImprovementKind.EDGE_CASE.priority
    )


def test_backlog_is_just_barely_below_spec() -> None:
    # Settled with the operator: formalising a new idea into a spec ranks
    # immediately after finishing an existing one — nothing sits between.
    assert ImprovementKind.BACKLOG.priority == ImprovementKind.SPEC.priority + 1


def test_from_str_is_lenient_and_falls_back_to_doc() -> None:
    assert ImprovementKind.from_str("FEATURE") is ImprovementKind.FEATURE
    assert ImprovementKind.from_str("  bug_fix ") is ImprovementKind.BUG_FIX
    assert ImprovementKind.from_str("spec") is ImprovementKind.SPEC
    assert ImprovementKind.from_str("backlog") is ImprovementKind.BACKLOG
    assert ImprovementKind.from_str("nonsense") is ImprovementKind.DOC
    assert ImprovementKind.from_str("") is ImprovementKind.DOC


def test_primary_signals_cover_every_kind() -> None:
    for kind in ImprovementKind:
        assert kind.primary_signals  # non-empty tuple for each
    assert "spec_completion" in ImprovementKind.SPEC.primary_signals
    assert "spec_proposed" in ImprovementKind.BACKLOG.primary_signals
