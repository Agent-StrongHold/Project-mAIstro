"""The tiered base-fixer scaffold and the test-path heuristic (W4)."""

from __future__ import annotations

from maistro_evolve.improvement import ImprovementKind
from maistro_rsi.fail_first import (
    DOC_CONTRACT,
    FAIL_FIRST_CLAUSE,
    REFACTOR_CONTRACT,
    SPEC_DRAFT_CONTRACT,
)
from maistro_rsi.local_loop import _fixer_objective, _guess_test_path


def test_feature_tier_is_ambitious_and_multi_file() -> None:
    obj = _fixer_objective("pkg/mod.py", ImprovementKind.FEATURE, "add a streaming API")
    assert "add a streaming API" in obj
    assert "ambitious" in obj.lower()
    assert "multiple" in obj.lower() or "across the files" in obj.lower()
    assert "NEW tests written first" in obj
    assert FAIL_FIRST_CLAUSE in obj


def test_bounded_behavior_kinds_require_fail_first() -> None:
    for kind in (
        ImprovementKind.BUG_FIX,
        ImprovementKind.NEW_TEST,
        ImprovementKind.ASSERTION,
        ImprovementKind.EDGE_CASE,
        ImprovementKind.PERF,
        ImprovementKind.SPEC,
    ):
        obj = _fixer_objective("pkg/mod.py", kind, "do the thing")
        assert "do the thing" in obj
        assert FAIL_FIRST_CLAUSE in obj
        assert "minimal" in obj.lower() or kind is ImprovementKind.SPEC


def test_refactor_and_doc_use_alternative_contracts() -> None:
    refactor = _fixer_objective("pkg/mod.py", ImprovementKind.REFACTOR, "do the thing")
    assert REFACTOR_CONTRACT in refactor
    assert FAIL_FIRST_CLAUSE not in refactor
    assert "only this module" in refactor

    doc = _fixer_objective("pkg/mod.py", ImprovementKind.DOC, "do the thing")
    assert DOC_CONTRACT in doc
    assert FAIL_FIRST_CLAUSE not in doc

    backlog = _fixer_objective("pkg/mod.py", ImprovementKind.BACKLOG, "do the thing")
    assert SPEC_DRAFT_CONTRACT in backlog
    assert FAIL_FIRST_CLAUSE not in backlog
    assert "docs/specs/" in backlog


def test_guess_test_path_maps_src_to_tests() -> None:
    assert (
        _guess_test_path("packages/maistro-evolve/src/maistro_evolve/mutate.py")
        == "packages/maistro-evolve/tests/test_mutate.py"
    )
    # Windows separators tolerated.
    assert _guess_test_path("a\\src\\pkg\\x.py") == "a/tests/test_x.py"
    # No src/ segment → repo-root tests dir.
    assert _guess_test_path("foo/bar.py") == "tests/test_bar.py"
