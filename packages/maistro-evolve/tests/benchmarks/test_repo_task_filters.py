"""Admission filters for the repo-history corpus (SPEC-281 §4).

These predicates decide what the exam contains, which makes them worth pinning
as tightly as the grader itself. Each filter here exists because the first
generated corpus admitted something it should not have, and each rejects for a
*different* reason — size, signal, and independence are three separate failures
that no single threshold catches.

The tests use synthetic commit messages rather than real shas so they keep
working as the repository's history moves.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "generate_repo_tasks.py"

pytestmark = pytest.mark.skipif(not _SCRIPT.is_file(), reason="generator script not present")


def _generator():
    """Import the script as a module (it lives in scripts/, not the package)."""
    if str(_SCRIPT.parent) not in sys.path:
        sys.path.insert(0, str(_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("generate_repo_tasks", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_repo_tasks"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _generator()


def test_generator_wrapper_preserves_benchmark_compatibility_surface(gen) -> None:
    expected = {
        "_DEFAULT_MAX_ISSUE_CHARS",
        "_DEFAULT_MAX_PATCH_LINES",
        "_DEFAULT_MAX_SRC_FILES",
        "_DEFAULT_MIN_ISSUE_CHARS",
        "_SELF_AUTHORED_RE",
        "_classify",
    }
    assert all(hasattr(gen, name) for name in expected)


class TestSelfAuthoredFilter:
    """Independence, not quality.

    RSI-loop commits are genuine fail-to-pass transitions with real messages, so
    no size or length filter catches them. Scoring the loop on bugs it
    introduced and then fixed measures it against its own homework: fix and
    failure are drawn from the same distribution, so a genome sharing its
    predecessor's blind spots is flattered rather than tested.
    """

    @pytest.mark.parametrize(
        "subject",
        [
            "RSI cycle 3 [glm-5.2]: Improve the module packages/maistro-core",
            "RSI cycle 25 [spawn-046158#afcfbf]: Make exactly one small change",
            "rsi cycle 7: lowercase variant",
            "autorun cycle 12: another shape",
        ],
    )
    def test_loop_authored_subjects_are_matched(self, gen, subject: str) -> None:
        assert gen._SELF_AUTHORED_RE.match(subject)

    @pytest.mark.parametrize(
        "subject",
        [
            "fix(conductor): make optional router failures observable",
            "fix(sandbox): close run_command absolute-path escape",
            "feat(rsi): local fallback tier — a never-idle floor",
            # Human commits that merely mention RSI must not be swept up.
            "fix(rsi): cap oversized tool_use inputs on resume",
            "Harden exploratory RSI autorun: crash-proof dead-ends",
        ],
    )
    def test_human_commits_are_not_matched(self, gen, subject: str) -> None:
        assert not gen._SELF_AUTHORED_RE.match(subject)


class TestIssueTextBounds:
    def test_bounds_are_ordered_and_sane(self, gen) -> None:
        assert 0 < gen._DEFAULT_MIN_ISSUE_CHARS < gen._DEFAULT_MAX_ISSUE_CHARS

    def test_a_terse_but_specific_subject_survives_the_floor(self, gen) -> None:
        """The floor must not become a house-style rule. Real fixes in this repo
        have short, specific subjects and those are good tasks."""
        subject = "fix(rsi): trim resumed transcripts to fit the smallest context window"
        assert len(subject) >= gen._DEFAULT_MIN_ISSUE_CHARS

    def test_the_ceiling_excludes_an_aggregated_changelog(self, gen) -> None:
        """`Develop (#243)` carried 72,263 characters covering dozens of
        unrelated PRs. A genome handed that and asked for one specific fix is
        being tested on extraction, not debugging."""
        assert gen._DEFAULT_MAX_ISSUE_CHARS < 72_263

    def test_the_ceiling_leaves_room_for_a_detailed_report(self, gen) -> None:
        """A thorough bug report with repro steps and a stack trace runs a
        couple of thousand characters and must still be admissible."""
        detailed = "fix(core): sessions leak\n\n" + ("Repro: " + "x" * 60 + "\n") * 25
        assert gen._DEFAULT_MIN_ISSUE_CHARS < len(detailed) < gen._DEFAULT_MAX_ISSUE_CHARS


class TestPatchSizeCeilings:
    def test_ceilings_exclude_a_vendoring_commit(self, gen) -> None:
        """The commit that motivated these: 4,919 lines across 12 files, a real
        fail-to-pass transition and a useless task."""
        assert gen._DEFAULT_MAX_PATCH_LINES < 4919
        assert gen._DEFAULT_MAX_SRC_FILES < 12

    def test_ceilings_admit_a_normal_localized_fix(self, gen) -> None:
        assert gen._DEFAULT_MAX_PATCH_LINES >= 150
        assert gen._DEFAULT_MAX_SRC_FILES >= 3


class TestFileClassification:
    def test_tests_and_sources_are_separated(self, gen) -> None:
        src, tests = gen._classify(
            [
                "packages/maistro-core/src/maistro/router/scorer.py",
                "packages/maistro-core/tests/router/test_scorer.py",
                "packages/hive-conductor/backend/routes/chat.py",
                "packages/maistro-evolve/tests/benchmarks/conftest.py",
                "docs/specs/SPEC-281-harness-lift-measurement.md",
            ]
        )
        assert "packages/maistro-core/src/maistro/router/scorer.py" in src
        assert "packages/hive-conductor/backend/routes/chat.py" in src
        assert "packages/maistro-core/tests/router/test_scorer.py" in tests
        assert "packages/maistro-evolve/tests/benchmarks/conftest.py" in tests
        # Docs are neither: they must not count as a source change on their own.
        assert not any("docs/" in f for f in src + tests)

    def test_a_test_file_is_never_also_a_source_file(self, gen) -> None:
        """Overlap would put the same diff in both patches, so the gold patch
        would contain the tests and every commit would trivially 'pass'."""
        src, tests = gen._classify(["packages/maistro-evolve/tests/test_fitness.py"])
        assert src == []
        assert len(tests) == 1
