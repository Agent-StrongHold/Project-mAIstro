"""Tests for the per-file diff-coverage gate (#163).

The gate replaced a `diff-cover` wrapper after review showed that tool could not
express two of the four rules: it pools every changed line before applying its
threshold, and it scores line hits without reading branch arcs. Both properties
are asserted here directly, because "it is not pooled" and "arcs count" are
exactly the claims that were wrong before.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-diff-coverage.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_diff_coverage", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _report(tmp_path: Path, lines: dict[str, list[tuple[int, int, str | None]]]) -> Path:
    """A minimal Cobertura report: {filename: [(line, hits, condition|None)]}."""
    body = []
    for filename, entries in lines.items():
        rows = []
        for number, hits, condition in entries:
            attrs = f'number="{number}" hits="{hits}"'
            if condition:
                attrs += f' branch="true" condition-coverage="{condition}"'
            rows.append(f"<line {attrs}/>")
        body.append(f'<class filename="{filename}"><lines>{"".join(rows)}</lines></class>')
    path = tmp_path / "coverage.xml"
    path.write_text(
        f"<coverage><packages><package><classes>{''.join(body)}"
        "</classes></package></packages></coverage>"
    )
    return path


class TestDiffParsing:
    def test_hunk_header_without_a_count_is_one_line(self, gate):
        assert gate.HUNK_RE.match("@@ -1 +7 @@").groups() == ("7", None)

    def test_hunk_header_with_a_count(self, gate):
        assert gate.HUNK_RE.match("@@ -1,2 +7,3 @@").groups() == ("7", "3")

    def test_the_merge_base_form_is_used(self, gate):
        """`...` and not `..`: a PR is judged on what it changed, not on what
        the base branch merged since it forked."""
        import inspect

        assert "...HEAD" in inspect.getsource(gate.changed_lines)


class TestPerFileNotPooled:
    """The finding that motivated replacing `diff-cover`."""

    def test_an_uncovered_file_fails_however_well_covered_the_rest_is(
        self, gate, tmp_path, monkeypatch
    ):
        report = _report(
            tmp_path,
            {
                "new.py": [(1, 0, None), (2, 0, None), (3, 0, None), (4, 0, None), (5, 0, None)],
                "old.py": [(n, 1, None) for n in range(1, 96)],
            },
        )
        monkeypatch.setattr(
            gate,
            "changed_lines",
            lambda base: {"new.py": set(range(1, 6)), "old.py": set(range(1, 96))},
        )
        failures = gate.audit("base", report, 90.0, 80.0)
        assert len(failures) == 1
        assert "new.py" in failures[0]
        # 5 uncovered of 100 changed lines pools to 95% — which is why pooling
        # was the defect and not merely a rounding difference.

    def test_a_covered_file_alongside_it_is_not_reported(self, gate, tmp_path, monkeypatch):
        report = _report(tmp_path, {"a.py": [(1, 0, None)], "b.py": [(1, 1, None)]})
        monkeypatch.setattr(gate, "changed_lines", lambda base: {"a.py": {1}, "b.py": {1}})
        failures = gate.audit("base", report, 90.0, 80.0)
        assert len(failures) == 1 and "a.py" in failures[0]


class TestBranchArcs:
    def test_a_half_taken_conditional_fails_even_though_the_line_ran(
        self, gate, tmp_path, monkeypatch
    ):
        """The second thing `diff-cover` could not see: the line records a hit,
        and only one arc out of it was taken."""
        report = _report(tmp_path, {"a.py": [(1, 5, "50% (1/2)")]})
        monkeypatch.setattr(gate, "changed_lines", lambda base: {"a.py": {1}})
        failures = gate.audit("base", report, 90.0, 80.0)
        assert len(failures) == 1
        assert "branch arcs" in failures[0]

    def test_a_fully_taken_conditional_passes(self, gate, tmp_path, monkeypatch):
        report = _report(tmp_path, {"a.py": [(1, 5, "100% (2/2)")]})
        monkeypatch.setattr(gate, "changed_lines", lambda base: {"a.py": {1}})
        assert gate.audit("base", report, 90.0, 80.0) == []

    def test_a_file_with_no_conditionals_is_not_penalised(self, gate, tmp_path, monkeypatch):
        report = _report(tmp_path, {"a.py": [(1, 1, None)]})
        monkeypatch.setattr(gate, "changed_lines", lambda base: {"a.py": {1}})
        assert gate.audit("base", report, 90.0, 80.0) == []


class TestScope:
    def test_a_file_outside_the_coverage_report_is_skipped(self, gate, tmp_path, monkeypatch):
        """The measured scope is the `--source` list in quality.yml, and that
        list is the exemption list — migrations, workflows and docs fall out by
        construction rather than by a list somebody maintains."""
        report = _report(tmp_path, {"a.py": [(1, 1, None)]})
        monkeypatch.setattr(gate, "changed_lines", lambda base: {"alembic/versions/010.py": {1}})
        assert gate.audit("base", report, 90.0, 80.0) == []

    def test_changed_lines_outside_the_measured_ones_are_skipped(self, gate, tmp_path, monkeypatch):
        """A docstring or blank line inside a measured file has no coverage
        record; only executable lines are scored."""
        report = _report(tmp_path, {"a.py": [(10, 1, None)]})
        monkeypatch.setattr(gate, "changed_lines", lambda base: {"a.py": {1, 2}})
        assert gate.audit("base", report, 90.0, 80.0) == []
