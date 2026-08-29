"""The containment-surface classifier, on its own (#303).

`quarantine.py`'s suite covers the gate's behaviour and the matching semantics
through the re-export. These cover the two properties that are specifically
about the split: that the module costs nothing to import, and that the
promotion appliers `SENSITIVE_PATH_PATTERNS` used to omit are covered now.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from maistro_rsi.sensitive_paths import (
    SENSITIVE_PATH_PATTERNS,
    matches_sensitive_pattern,
    normalize_touched_path,
)

MODULE = Path(__file__).resolve().parents[1] / "src" / "maistro_rsi" / "sensitive_paths.py"


class TestItCostsNothingToImport:
    """`scripts/check-promotion-surface.py` runs in the lint job, where the
    workspace is not installed. A classifier that needs the security stack to
    answer "is this path protected" is a gate that gets skipped."""

    def test_it_imports_only_the_standard_library(self) -> None:
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                roots.add(node.module.split(".")[0])

        assert roots <= sys.stdlib_module_names, sorted(roots - sys.stdlib_module_names)

    def test_it_loads_by_path_with_nothing_on_the_import_path(self) -> None:
        """The AST check above says what it declares; this says what it does.

        `-I` isolates the interpreter (no `PYTHONPATH`, no user site), so the
        module has to stand on the standard library alone.
        """
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import importlib.util as u, sys;"
                f"s = u.spec_from_file_location('sp', {str(MODULE)!r});"
                "m = u.module_from_spec(s); sys.modules['sp'] = m; s.loader.exec_module(m);"
                "print(m.matches_sensitive_pattern('a/maistro_rsi/local_loop.py'))",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "True"


class TestTheOmissionsThatMotivatedTheSplit:
    @pytest.mark.parametrize(
        "path",
        [
            "packages/maistro-rsi/src/maistro_rsi/local_loop.py",
            "packages/maistro-rsi/src/maistro_rsi/merge.py",
            "packages/maistro-rsi/src/maistro_rsi/code_fixer.py",
            "packages/maistro-rsi/src/maistro_rsi/promotion_review.py",
            "packages/maistro-evolve/src/maistro_evolve/population.py",
            "packages/maistro-bootstrap/src/maistro_bootstrap/builders/sandbox.py",
            "packages/maistro-core/src/maistro/tools/git/github.py",
        ],
    )
    def test_the_promotion_and_execution_modules_escalate(self, path: str) -> None:
        assert matches_sensitive_pattern(path)

    def test_the_directory_patterns_still_cover_what_they_replaced(self) -> None:
        """The per-file entries for these two packages were removed in favour of
        directory patterns. Strictly broader, and this is the assertion that
        says so rather than the commit message."""
        replaced = [
            "packages/maistro-rsi/src/maistro_rsi/quarantine.py",
            "packages/maistro-rsi/src/maistro_rsi/selfbranch.py",
            "packages/maistro-rsi/src/maistro_rsi/runner.py",
            "packages/maistro-rsi/src/maistro_rsi/coordinator.py",
            "packages/maistro-rsi/src/maistro_rsi/autorun.py",
            "packages/maistro-rsi/src/maistro_rsi/apply_agents.py",
            "packages/maistro-rsi/src/maistro_rsi/candidate_fitness.py",
            "packages/maistro-rsi/src/maistro_rsi/harvest.py",
            "packages/maistro-rsi/src/maistro_rsi/sandbox/microvm.py",
            "packages/maistro-evolve/src/maistro_evolve/fitness.py",
            "packages/maistro-evolve/src/maistro_evolve/scorecard.py",
            "packages/maistro-evolve/src/maistro_evolve/harness.py",
            "packages/maistro-evolve/src/maistro_evolve/cycle.py",
            "packages/maistro-evolve/src/maistro_evolve/tournament.py",
            "packages/maistro-evolve/src/maistro_evolve/types.py",
            "packages/maistro-evolve/src/maistro_evolve/benchmarks/ifeval.py",
        ]

        assert [p for p in replaced if not matches_sensitive_pattern(p)] == []

    @pytest.mark.parametrize(
        "path",
        [
            "packages/maistro-rsi/tests/test_quarantine.py",
            "packages/maistro-rsi/tests/test_sensitive_paths.py",
            "packages/maistro-evolve/tests/test_fitness.py",
            "tests/test_check_promotion_surface.py",
            "tests/test_check_enumerations.py",
        ],
    )
    def test_the_evidence_escalates_with_the_code(self, path: str) -> None:
        """A candidate that edits the classifier and the tests pinning it in one
        diff would otherwise authorize itself."""
        assert matches_sensitive_pattern(path)


class TestItStaysASurfaceAndNotAWildcard:
    @pytest.mark.parametrize(
        "path",
        [
            "packages/maistro-core/src/maistro/memory/learnings/store.py",
            "packages/hive-conductor/backend/routes/chat.py",
            "packages/maistro-canvas/src/maistro_canvas/types.py",
            "docs/adr/ADR-036-ontology.md",
            "README.md",
        ],
    )
    def test_ordinary_application_surface_does_not_escalate(self, path: str) -> None:
        assert not matches_sensitive_pattern(path)

    def test_a_lookalike_prefix_does_not_match(self) -> None:
        """Segment-boundary matching: `pattern in path` accepted this once."""
        assert not matches_sensitive_pattern("vendor/notmaistro_rsi/local_loop.py")
        assert not matches_sensitive_pattern("src/maistro_rsi_shim/local_loop.py")

    def test_no_pattern_is_empty(self) -> None:
        """An empty string matches everything a directory check is given."""
        assert [p for p in SENSITIVE_PATH_PATTERNS if not p.strip()] == []

    def test_the_patterns_are_unique(self) -> None:
        assert len(set(SENSITIVE_PATH_PATTERNS)) == len(SENSITIVE_PATH_PATTERNS)


class TestNormalization:
    def test_windows_separators_are_folded(self) -> None:
        assert matches_sensitive_pattern("packages\\maistro-rsi\\src\\maistro_rsi\\merge.py")

    def test_repeated_leading_dot_slash_is_stripped_without_eating_dots(self) -> None:
        assert normalize_touched_path("././.github/workflows/ci.yml") == ".github/workflows/ci.yml"
        assert matches_sensitive_pattern("././.github/workflows/ci.yml")
