"""Documentation-regression detector: a docstring made *vaguer* is flagged, but
adding a docstring or faithfully rewording one is not (so it can back a veto)."""

from __future__ import annotations

from maistro_evolve.doc_regression import doc_regressions

_PRECISE = '''
"""Reflective prompt evolution.

Adopts GEPA (reflective prompt evolution) and MIPROv2 (grounded instruction
proposal) without a DSPy dependency. Per SPEC-202, candidates verified only by
`stub` benchmark scores are never accepted.
"""
'''

_VAGUE = '''
"""This module improves prompts.

It refines things over time and keeps the good ones.
"""
'''


def test_vaguer_docstring_is_flagged() -> None:
    regs = doc_regressions(_PRECISE, _VAGUE)
    assert regs, "a docstring that dropped GEPA/MIPROv2/DSPy/SPEC-202 and shrank should be flagged"
    assert "<module>" in regs[0]


def test_adding_a_docstring_is_not_a_regression() -> None:
    before = "def f():\n    return 1\n"
    after = 'def f():\n    """Return the constant 1 for `callers`."""\n    return 1\n'
    assert doc_regressions(before, after) == []


def test_faithful_reword_keeps_specifics_and_is_not_flagged() -> None:
    # Same references (GEPA, MIPROv2, SPEC-202), comparable length → not a regression.
    reworded = '''
"""Prompt evolution via reflection.

Uses GEPA (reflective prompt evolution) plus MIPROv2 (grounded instruction
proposal), no DSPy needed. SPEC-202: never accept a `stub`-only candidate.
"""
'''
    assert doc_regressions(_PRECISE, reworded) == []


def test_missing_symbol_or_removed_docstring_is_not_this_checks_job() -> None:
    # Candidate drops the docstring entirely (or the symbol) → not flagged here
    # (that's coverage's job, not specificity's).
    assert doc_regressions(_PRECISE, "x = 1\n") == []
