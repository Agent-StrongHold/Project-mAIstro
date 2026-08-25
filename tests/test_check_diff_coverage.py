"""Tests for the per-file diff-coverage gate (#163).

The gate replaced a `diff-cover` wrapper after review showed that tool could not
express two of the four rules: it pools every changed line before applying its
threshold, and it scores line hits without reading branch arcs. Both properties
are asserted here directly, because "it is not pooled" and "arcs count" are
exactly the claims that were wrong before.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-diff-coverage.py"

#: A path inside a measured root. Bare names like `a.py` used to work because
#: `audit` scored whatever appeared in the report; it now scores only what
#: `MEASURED_ROOTS` claims, so a fixture file has to live somewhere the gate
#: says it measures — which is the property under test in `TestMeasuredScope`.
SRC = "packages/maistro-core/src/maistro"


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
                f"{SRC}/new.py": [
                    (1, 0, None),
                    (2, 0, None),
                    (3, 0, None),
                    (4, 0, None),
                    (5, 0, None),
                ],
                f"{SRC}/old.py": [(n, 1, None) for n in range(1, 96)],
            },
        )
        monkeypatch.setattr(
            gate,
            "changed_lines",
            lambda base: {f"{SRC}/new.py": set(range(1, 6)), f"{SRC}/old.py": set(range(1, 96))},
        )
        failures = gate.audit("base", report, 90.0, 80.0)
        assert len(failures) == 1
        assert f"{SRC}/new.py" in failures[0]
        # 5 uncovered of 100 changed lines pools to 95% — which is why pooling
        # was the defect and not merely a rounding difference.

    def test_a_covered_file_alongside_it_is_not_reported(self, gate, tmp_path, monkeypatch):
        report = _report(tmp_path, {f"{SRC}/a.py": [(1, 0, None)], f"{SRC}/b.py": [(1, 1, None)]})
        monkeypatch.setattr(
            gate, "changed_lines", lambda base: {f"{SRC}/a.py": {1}, f"{SRC}/b.py": {1}}
        )
        failures = gate.audit("base", report, 90.0, 80.0)
        assert len(failures) == 1 and f"{SRC}/a.py" in failures[0]


class TestBranchArcs:
    def test_a_half_taken_conditional_fails_even_though_the_line_ran(
        self, gate, tmp_path, monkeypatch
    ):
        """The second thing `diff-cover` could not see: the line records a hit,
        and only one arc out of it was taken."""
        report = _report(tmp_path, {f"{SRC}/a.py": [(1, 5, "50% (1/2)")]})
        monkeypatch.setattr(gate, "changed_lines", lambda base: {f"{SRC}/a.py": {1}})
        failures = gate.audit("base", report, 90.0, 80.0)
        assert len(failures) == 1
        assert "branch arcs" in failures[0]

    def test_a_fully_taken_conditional_passes(self, gate, tmp_path, monkeypatch):
        report = _report(tmp_path, {f"{SRC}/a.py": [(1, 5, "100% (2/2)")]})
        monkeypatch.setattr(gate, "changed_lines", lambda base: {f"{SRC}/a.py": {1}})
        assert gate.audit("base", report, 90.0, 80.0) == []

    def test_a_file_with_no_conditionals_is_not_penalised(self, gate, tmp_path, monkeypatch):
        report = _report(tmp_path, {f"{SRC}/a.py": [(1, 1, None)]})
        monkeypatch.setattr(gate, "changed_lines", lambda base: {f"{SRC}/a.py": {1}})
        assert gate.audit("base", report, 90.0, 80.0) == []


class TestScope:
    def test_a_declared_exemption_is_not_scored(self, gate, tmp_path, monkeypatch):
        """Migrations are exempt by declaration and with a reason, not by
        happening to fall outside a `--source` flag."""
        report = _report(tmp_path, {f"{SRC}/a.py": [(1, 1, None)]})
        monkeypatch.setattr(gate, "changed_lines", lambda base: {"alembic/versions/010.py": {1}})
        assert gate.audit("base", report, 90.0, 80.0) == []

    def test_changed_lines_outside_the_measured_ones_are_skipped(self, gate, tmp_path, monkeypatch):
        """A docstring or blank line inside a measured file has no coverage
        record; only executable lines are scored."""
        report = _report(tmp_path, {f"{SRC}/a.py": [(10, 1, None)]})
        monkeypatch.setattr(gate, "changed_lines", lambda base: {f"{SRC}/a.py": {1, 2}})
        assert gate.audit("base", report, 90.0, 80.0) == []


class TestMeasuredScope:
    """#163 item 6 and item 5, which are the same mechanism seen twice.

    Item 6 is "cover the non-publish packages too". Item 5 is "say what is
    exempt, in one place". Both fail the same way if the gate treats "absent
    from coverage.xml" as "nothing to check": a package nobody measures and a
    package whose measurement broke produce the identical green tick.
    """

    def _audit(self, gate, tmp_path, monkeypatch, changed, report=None):
        path = _report(tmp_path, report or {f"{SRC}/a.py": [(1, 1, None)]})
        monkeypatch.setattr(gate, "changed_lines", lambda base: changed)
        return gate.audit("base", path, 90.0, 80.0)

    @pytest.mark.ac("ADR-082526-cb51/AC-1")
    def test_every_package_the_issue_names_is_measured(self, gate):
        """The four packages #163 item 6 names, each with the root that
        measures it. Named individually rather than counted: a length
        assertion passes while the wrong four are listed."""
        for package in (
            "packages/maistro-server/src/maistro_server",
            "packages/maistro-turing/src/maistro_turing",
            "packages/maistro-turing/backend",
            "packages/maistro-design/src/maistro_design",
            "packages/hive-conductor/backend",
        ):
            assert package in gate.MEASURED_ROOTS

    @pytest.mark.ac("ADR-082526-cb51/AC-2")
    def test_an_in_scope_file_absent_from_the_report_fails(self, gate, tmp_path, monkeypatch):
        """The hole this closes. A mistyped `--source`, a producer whose
        artefact uploaded empty, or a namespace directory coverage declined to
        walk all produce a file that is in scope and has no record — and a skip
        there is indistinguishable from a pass."""
        found = self._audit(gate, tmp_path, monkeypatch, {f"{SRC}/never_measured.py": {1, 2}})
        assert len(found) == 1
        assert "absent from the coverage report" in found[0]

    @pytest.mark.ac("ADR-082526-cb51/AC-2")
    def test_a_measured_file_with_no_executable_lines_passes(self, gate, tmp_path, monkeypatch):
        """Membership, not truthiness. Coverage emits a `<class>` with zero
        `<line>` children for a file with no statements — verified against a
        real report: an empty `__init__.py` and a docstring-only module both
        arrive with `line-elements=0`. Reading that empty record as "absent"
        failed exactly the files that are trivially correct."""
        report = _report(tmp_path, {f"{SRC}/__init__.py": []})
        monkeypatch.setattr(gate, "changed_lines", lambda base: {f"{SRC}/__init__.py": {1}})
        assert gate.audit("base", report, 90.0, 80.0) == []

    @pytest.mark.ac("ADR-082526-cb51/AC-3")
    def test_a_file_no_producer_reaches_is_not_a_failure(self, gate, tmp_path, monkeypatch):
        """Out-of-scope is not the same as broken. It is reported as unmeasured
        rather than failed, because no one decided that file should be covered
        and failing every PR that touches one would get the gate turned off."""
        # maistro-registry, which has its own workflow but no coverage
        # producer. `scripts/` used to be the example here and is measured as
        # of #257 — the test caught that change rather than being updated to
        # suit it.
        outside = "packages/maistro-registry/src/maistro_registry/cli.py"
        assert self._audit(gate, tmp_path, monkeypatch, {outside: {1}}) == []
        assert gate.classify(outside)[0] == "unmeasured"

    def test_a_non_python_file_is_ignored(self, gate):
        assert gate.classify("docs/adr/ADR-1.md")[0] == "ignored"

    def test_test_code_is_exempt_with_a_reason(self, gate):
        """`--source=packages/hive-conductor/backend` sweeps in 91 test files.
        Scoring a test file's own coverage measures nothing."""
        verdict, reason = gate.classify("packages/hive-conductor/backend/tests/test_x.py")
        assert verdict == "exempt" and reason

    @pytest.mark.ac("ADR-082526-cb51/AC-4")
    def test_every_exemption_states_a_reason(self, gate):
        """An exemption that does not have to justify itself is only a way to
        make the gate quieter."""
        assert gate.EXEMPT
        for marker, reason in gate.EXEMPT:
            assert marker and len(reason) > 20, marker

    @pytest.mark.ac("ADR-082526-cb51/AC-5")
    def test_the_declaration_matches_what_the_workflow_measures(self, gate):
        """A declaration nobody verifies drifts the first time a producer is
        added, and drift here is silent by construction: declaring a root with
        no producer fails every PR that touches it, and adding a producer
        without declaring the root leaves the package unscored."""
        workflow = (ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
        # Comment lines are skipped: the header explaining the pattern writes
        # `--source=<src>`, and a placeholder is not a producer.
        in_workflow = {
            match
            for line in workflow.splitlines()
            if not line.lstrip().startswith("#")
            for match in re.findall(r"--source=(\S+)", line)
        }
        assert in_workflow == set(gate.MEASURED_ROOTS)
