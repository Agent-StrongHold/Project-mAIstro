"""The tiered base-fixer scaffold and the test-path heuristic (W4)."""

from __future__ import annotations

from maistro_evolve.improvement import ImprovementKind
from maistro_rsi.local_loop import _fixer_objective, _guess_test_path


def test_feature_tier_is_ambitious_and_multi_file() -> None:
    obj = _fixer_objective("pkg/mod.py", ImprovementKind.FEATURE, "add a streaming API")
    assert "add a streaming API" in obj
    assert "ambitious" in obj.lower()
    assert "multiple" in obj.lower() or "across the files" in obj.lower()
    assert "NEW tests written first" in obj


def test_bounded_tiers_are_test_first_and_minimal() -> None:
    for kind in (
        ImprovementKind.BUG_FIX,
        ImprovementKind.NEW_TEST,
        ImprovementKind.ASSERTION,
        ImprovementKind.EDGE_CASE,
        ImprovementKind.PERF,
    ):
        obj = _fixer_objective("pkg/mod.py", kind, "do the thing")
        assert "do the thing" in obj
        assert "test-first" in obj.lower()
        assert "minimal" in obj.lower()
        assert "only this module and its test file" in obj
        # The enforced fail-first proof (#392): the scaffold must demand a test
        # that fails for the reason the change cures, and must name the harness
        # verification that voids already-passing (characterization) evidence.
        assert "fails against the current code" in obj
        assert "reverting" in obj or "reverts" in obj


def test_refactor_and_doc_tiers_are_behavior_preserving_polish() -> None:
    # Declared REFACTOR/DOC work owes the ALTERNATIVE evidence contract (#392):
    # measured code-quality improvement, behavior preserved, no manufactured
    # failing test.
    for kind in (ImprovementKind.REFACTOR, ImprovementKind.DOC):
        obj = _fixer_objective("pkg/mod.py", kind, "do the thing")
        assert "do the thing" in obj
        assert "without changing behavior" in obj.lower()
        assert "do not manufacture a failing test" in obj.lower()
        assert "code-quality score measurably improves" in obj
        assert "only this module and its test file" in obj


def test_guess_test_path_maps_src_to_tests() -> None:
    assert (
        _guess_test_path("packages/maistro-evolve/src/maistro_evolve/mutate.py")
        == "packages/maistro-evolve/tests/test_mutate.py"
    )
    # Windows separators tolerated.
    assert _guess_test_path("a\\src\\pkg\\x.py") == "a/tests/test_x.py"
    # No src/ segment → repo-root tests dir.
    assert _guess_test_path("foo/bar.py") == "tests/test_bar.py"
