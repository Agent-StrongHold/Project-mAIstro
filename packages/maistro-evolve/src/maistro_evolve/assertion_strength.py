"""Assertion strength: how *demanding* a test's assertions are.

Coverage says a line ran; red->green says the test drives the code. Neither
catches a test that runs the code and then barely checks it — ``assert result
is not None`` passes for almost any behaviour. Assertion strength grades that:
weak checks (bare truthiness, ``is not None``, ``== True``) score low; exact-
value and structural checks score high; a test with no assertions at all is
vacuous.

It's the measurable precondition for the generative TDD move: find a weakly-
asserted test, strengthen the assertion, and re-run — if it now fails, the
stronger assertion just exposed a latent bug in the code, which you then fix
(improved test + improved code). So this signal both scores test quality and
*points that play at the right targets*.

Pure AST — no tool, deterministic.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

# Strength of a single check, 0 (vacuous) .. 1 (exact/structural).
_VACUOUS = 0.0  # assert True, assert 1
_WEAK = 0.3  # bare truthiness, is/is-not None, == True/False, plain call
_MEDIUM = 0.6  # isinstance/hasattr, ordering/containment, is/is-not <non-None>
_RAISES = 0.8  # with pytest.raises(...) / pytest.warns(...)
_STRONG = 1.0  # == / != against a concrete value


@dataclass
class AssertionStrength:
    score: float | None  # None when the file has no test functions
    n_tests: int = 0
    n_assertions: int = 0
    weak: int = 0
    strong: int = 0


def _assert_strength(node: ast.Assert) -> float:
    t = node.test
    if isinstance(t, ast.Constant):
        return _VACUOUS
    if isinstance(t, ast.Compare):
        op = t.ops[0]
        comp = t.comparators[0] if t.comparators else None
        if isinstance(op, ast.Is | ast.IsNot):
            if isinstance(comp, ast.Constant) and comp.value is None:
                return _WEAK  # is / is not None — only existence
            return _MEDIUM
        if isinstance(op, ast.Eq | ast.NotEq):
            if isinstance(comp, ast.Constant) and isinstance(comp.value, bool):
                return _WEAK  # == True / == False — truthiness in disguise
            return _STRONG  # exact value / structural equality
        return _MEDIUM  # <, >, <=, >=, in, not in
    if isinstance(t, ast.Call):
        fn = t.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", "")
        return _MEDIUM if name in ("isinstance", "hasattr", "issubclass") else _WEAK
    # Name / Attribute / BoolOp / `not x` — bare truthiness.
    return _WEAK


def _is_raises_with(node: ast.With | ast.AsyncWith) -> bool:
    for item in node.items:
        call = item.context_expr
        if isinstance(call, ast.Call):
            name = getattr(call.func, "attr", None) or getattr(call.func, "id", "")
            if name in ("raises", "warns"):
                return True
    return False


def _test_strengths(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[float]:
    strengths: list[float] = []
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Assert):
            strengths.append(_assert_strength(sub))
        elif isinstance(sub, ast.With | ast.AsyncWith) and _is_raises_with(sub):
            strengths.append(_RAISES)
    return strengths


def score_assertions(path: str | Path) -> AssertionStrength:
    """Score the assertion strength of the test functions in a file (0..1)."""
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError, ValueError):
        return AssertionStrength(score=None)

    test_scores: list[float] = []
    n_assertions = weak = strong = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.name.startswith("test"):
            continue
        strengths = _test_strengths(node)
        n_assertions += len(strengths)
        weak += sum(1 for s in strengths if s <= _WEAK)
        strong += sum(1 for s in strengths if s >= _STRONG)
        # A test with no assertions is vacuous (0); otherwise its mean strength.
        test_scores.append(sum(strengths) / len(strengths) if strengths else _VACUOUS)

    if not test_scores:
        return AssertionStrength(score=None)
    return AssertionStrength(
        score=round(sum(test_scores) / len(test_scores), 4),
        n_tests=len(test_scores),
        n_assertions=n_assertions,
        weak=weak,
        strong=strong,
    )
