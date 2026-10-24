"""Tests for coverage-based per-line test selection (#330).

A mutant can only be killed by a test that executes its line. The selector
turns recorded coverage contexts into per-line test sets and groups changed
lines by identical test sets. The dangerous failures are all silent ones —
a context that fails to resolve, a parametrized test that drops its
parameters, a changed line nothing executes — and each is pinned here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mutation_select_tests.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("mutation_select_tests", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


COLLECTED = [
    "tests/test_mod.py::test_add",
    "tests/test_mod.py::TestMath::test_sub",
    "tests/test_mod.py::test_param[3-4]",
    "tests/test_mod.py::test_param[5-6]",
]


@pytest.fixture(scope="module")
def by_key(mod):
    """The context->node-id mapping, built by parse_collected itself."""
    return mod.parse_collected(COLLECTED)


class TestContextResolution:
    def test_a_plain_function_resolves_to_its_node_id(self, mod, by_key):
        assert mod.context_to_node_id("test_mod.test_add", by_key) == [
            "tests/test_mod.py::test_add"
        ]

    def test_a_class_method_resolves_through_the_class(self, mod, by_key):
        assert mod.context_to_node_id("test_mod.TestMath.test_sub", by_key) == [
            "tests/test_mod.py::TestMath::test_sub"
        ]

    def test_a_parametrized_context_resolves_to_one_node(self, mod, by_key):
        assert mod.context_to_node_id("test_mod.test_param[3-4]", by_key) == [
            "tests/test_mod.py::test_param[3-4]"
        ]

    def test_a_param_without_suffix_resolves_to_every_parameter(self, mod, by_key):
        """Under-selection could drop the only killing parameter; over-select."""
        resolved = mod.context_to_node_id("test_mod.test_param", by_key)
        assert resolved == [
            "tests/test_mod.py::test_param[3-4]",
            "tests/test_mod.py::test_param[5-6]",
        ]

    def test_an_unknown_context_resolves_to_nothing(self, mod, by_key):
        assert mod.context_to_node_id("test_mod.ghost", by_key) == []

    def test_a_bare_module_context_resolves_to_nothing(self, mod, by_key):
        assert mod.context_to_node_id("test_mod", by_key) == []


class TestPackageRootedContexts:
    """Coverage roots contexts at the test module's import path.

    For a packaged suite that prefix is the package name, so a real critical
    file's context (`security.test_secret_equal.TestX.test_y`) never equals the
    stem-based collected key (`test_secret_equal.TestX.test_y`). Under-selection
    here silently drops the only killing test, so the suffix match must find it.
    """

    PACKAGE_COLLECTED: ClassVar[list[str]] = [
        "packages/maistro-core/tests/security/test_secret_equal.py::TestSecretEqual::test_equal_strings",
        "packages/maistro-core/tests/security/test_secret_equal.py::TestSecretEqual::test_unequal_strings",
    ]

    def test_a_package_prefixed_context_resolves_through_the_suffix(self, mod):
        by_key = mod.parse_collected(self.PACKAGE_COLLECTED)
        assert mod.context_to_node_id(
            "security.test_secret_equal.TestSecretEqual.test_equal_strings", by_key
        ) == [
            "packages/maistro-core/tests/security/test_secret_equal.py::TestSecretEqual::test_equal_strings"
        ]

    def test_a_package_prefixed_context_never_swallows_a_foreign_stem(self, mod):
        by_key = mod.parse_collected(self.PACKAGE_COLLECTED)
        assert (
            mod.context_to_node_id(
                "security.test_other_module.TestSecretEqual.test_equal_strings", by_key
            )
            == []
        )


class TestCoverageParsing:
    def test_contexts_are_read_per_line_for_the_source(self, mod):
        payload = {"files": {"pkg/mod.py": {"contexts": {"2": ["test_mod.test_add"], "5": [""]}}}}
        by_line = mod.coverage_contexts(payload, "pkg/mod.py")
        assert by_line == {2: ["test_mod.test_add"]}  # empty-context lines drop out

    def test_a_missing_source_entry_is_an_error_not_silence(self, mod):
        with pytest.raises(ValueError, match="no entry"):
            mod.coverage_contexts({"files": {}}, "pkg/mod.py")

    def test_executable_lines_are_executed_plus_missing(self, mod):
        entry = {"executed_lines": [1, 4], "missing_lines": [7]}
        payload = {"files": {"pkg/mod.py": entry}}
        assert mod.coverage_executable_lines(payload, "pkg/mod.py") == ({1, 4}, {7})


class TestExecutableFiltering:
    """Only executable changed lines owe the gate a killing test (review: P2).

    Requiring coverage of a comment or blank line fails the gate on a change
    no mutant could ever exercise; requiring it of an import-time line fails
    the gate on a line that provably ran. Neither is a coverage gap.
    """

    EXECUTED, MISSING = {2, 5}, {9}
    BY_LINE: ClassVar[dict[int, list[str]]] = {2: ["t_a"]}  # 5 ran only at import: no test context

    def test_a_comment_or_blank_line_is_never_a_coverage_gap(self, mod):
        testable, non_exec, import_only = mod.partition_changed(
            [3], self.EXECUTED, self.MISSING, self.BY_LINE
        )
        assert (testable, non_exec, import_only) == ([], [3], [])

    def test_an_import_time_line_is_covered_even_though_no_test_owns_it(self, mod):
        testable, non_exec, import_only = mod.partition_changed(
            [5], self.EXECUTED, self.MISSING, self.BY_LINE
        )
        assert (testable, non_exec, import_only) == ([], [], [5])

    def test_an_executable_unexecuted_line_stays_a_coverage_requirement(self, mod):
        testable, non_exec, import_only = mod.partition_changed(
            [9], self.EXECUTED, self.MISSING, self.BY_LINE
        )
        assert (testable, non_exec, import_only) == ([9], [], [])
        selection = mod.group_lines(testable, {})
        assert selection.no_coverage == [9]  # still fails the gate

    def test_a_covered_executable_line_stays_testable(self, mod):
        testable, non_exec, import_only = mod.partition_changed(
            [2], self.EXECUTED, self.MISSING, self.BY_LINE
        )
        assert (testable, non_exec, import_only) == ([2], [], [])


class TestGrouping:
    def test_lines_with_the_same_tests_collapse_into_one_group(self, mod):
        selection = mod.group_lines([2, 3, 9], {2: ["t_b"], 3: ["t_b"], 9: ["t_a"]})
        assert selection.groups == [
            {"lines": [9], "tests": ["t_a"]},
            {"lines": [2, 3], "tests": ["t_b"]},
        ]
        assert selection.no_coverage == []

    def test_an_uncovered_line_is_named_explicitly(self, mod):
        selection = mod.group_lines([4], {})
        assert selection.groups == []
        assert selection.no_coverage == [4]


class TestCollectedParsing:
    def test_node_ids_map_to_context_keys(self, mod):
        collected = mod.parse_collected(
            [
                "tests/test_mod.py::test_add",
                "tests/test_mod.py::TestMath::test_sub",
                "==================== 2 tests collected ====================",
                "",
            ]
        )
        assert collected == {
            "test_mod.test_add": "tests/test_mod.py::test_add",
            "test_mod.TestMath.test_sub": "tests/test_mod.py::TestMath::test_sub",
        }

    def test_parametrized_node_ids_keep_their_parameters(self, mod):
        collected = mod.parse_collected(["tests/test_mod.py::test_param[3-4]"])
        assert collected == {"test_mod.test_param[3-4]": "tests/test_mod.py::test_param[3-4]"}


class TestEndToEnd:
    """The real machinery: coverage with contexts over a tiny fixture module."""

    def test_selection_on_a_real_coverage_run(self, mod, tmp_path):
        pytest.importorskip("pytest_cov")
        src_dir = tmp_path / "sel_pkg"
        src_dir.mkdir()
        (src_dir / "__init__.py").write_text("", encoding="utf-8")
        (src_dir / "calc.py").write_text(
            "THREE = 3\n\n\ndef add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n"
            "    return a * b\n",
            encoding="utf-8",
        )
        tests_dir = tmp_path / "sel_tests"
        tests_dir.mkdir()
        (tests_dir / "test_calc.py").write_text(
            "from sel_pkg.calc import add, mul\n\n\n"
            "def test_add():\n    assert add(1, 2) == 3\n\n\n"
            "def test_mul():\n    assert mul(2, 3) == 6\n",
            encoding="utf-8",
        )
        selection = mod.select(
            str(src_dir / "calc.py"),
            str(tests_dir),
            [1, 3, 5, 9],  # import-time const, blank line, executable returns
            env_extra={"PYTHONPATH": f"{tmp_path}:{mod._package_pythonpath()}"},
        )
        tests_by_line = {line: set(g["tests"]) for g in selection.groups for line in g["lines"]}
        assert tests_by_line[5], "line 5 (return a + b) has no selected test"
        assert tests_by_line[9], "line 9 (return a * b) has no selected test"
        assert tests_by_line[5] != tests_by_line[9], "each line keeps its own killing test"
        assert selection.no_coverage == [], "executable covered lines never fail the gate"
        assert selection.non_executable == [3], "blank line excluded, not a gap"
        assert selection.import_time_only == [1], "import-time line excluded, not a gap"

    def test_an_unresolvable_context_is_a_named_warning_and_uncovered(self, mod, monkeypatch):
        """A line that ran under a context the collection cannot name must be
        reported as executed-but-unattributed, never silently dropped into a
        group with tests that may not execute it."""
        import types

        coverage_payload = {
            "files": {
                "pkg/mod.py": {
                    "executed_lines": [4],
                    "missing_lines": [],
                    "contexts": {"4": ["some_module.ghost_context"]},
                }
            }
        }

        def fake_run(argv, **kwargs):
            argv = [str(part) for part in argv]
            if "coverage" in argv:
                report = Path(argv[argv.index("-o") + 1])
                report.write_text(json.dumps(coverage_payload), encoding="utf-8")
            done = types.SimpleNamespace(returncode=0, stdout="", stderr="")
            return done

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        selection = mod.select("pkg/mod.py", "tests/test_mod.py", [4])
        assert selection.groups == []
        assert selection.no_coverage == [4]


class TestARedBaselineAbortsSelection:
    def test_selection_refuses_to_rank_lines_on_a_red_baseline(self, mod, monkeypatch):
        import types

        def red_run(argv, **kwargs):
            return types.SimpleNamespace(returncode=1, stdout="1 failed", stderr="")

        monkeypatch.setattr(mod.subprocess, "run", red_run)
        with pytest.raises(SystemExit):
            mod.select("pkg/mod.py", "tests/test_mod.py", [4])


class TestChangedLineInput:
    def test_a_json_array_of_lines_is_accepted(self, mod, tmp_path):
        path = tmp_path / "lines.json"
        path.write_text("[4, 2, 9]", encoding="utf-8")
        assert mod._read_lines(str(path)) == [4, 2, 9]

    def test_a_json_object_of_lines_is_accepted(self, mod, tmp_path):
        path = tmp_path / "lines.json"
        path.write_text('{"9": null, "4": null}', encoding="utf-8")
        assert mod._read_lines(str(path)) == [4, 9]

    def test_an_empty_line_set_is_explicit_never_an_empty_gate(self, mod, tmp_path):
        path = tmp_path / "lines.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(SystemExit, match="empty"):
            mod._read_lines(str(path))


class TestTheSelectionCli:
    """`main` turns a selection into the workflow's selection artifact and
    decides the exit: no-coverage lines fail the PR gate unless the run is a
    measurement (--allow-uncovered), and a selection with no groups refuses."""

    @staticmethod
    def _selection(mod, **overrides):
        return mod.Selection(
            groups=overrides.get("groups", [{"lines": [4], "tests": ["t::x"]}]),
            no_coverage=overrides.get("no_coverage", []),
            non_executable=overrides.get("non_executable", []),
            import_time_only=overrides.get("import_time_only", []),
        )

    def _main(self, mod, tmp_path, extra_args):
        lines = tmp_path / "lines.json"
        lines.write_text("[4]", encoding="utf-8")
        output = tmp_path / "selection.json"
        rc = mod.main(
            [
                "--source",
                "pkg/mod.py",
                "--tests",
                "tests/test_mod.py",
                "--lines",
                str(lines),
                "--output",
                str(output),
                *extra_args,
            ]
        )
        return rc, output

    def test_a_clean_selection_writes_the_workflow_artifact(self, mod, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "select", lambda *a, **k: self._selection(mod))
        rc, output = self._main(mod, tmp_path, [])
        assert rc == 0
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["groups"] == [{"lines": [4], "tests": ["t::x"]}]
        assert payload["changed_lines"] == [4]

    def test_no_coverage_lines_fail_the_pr_gate(self, mod, tmp_path, monkeypatch):
        monkeypatch.setattr(
            mod, "select", lambda *a, **k: self._selection(mod, groups=[], no_coverage=[4])
        )
        rc, _ = self._main(mod, tmp_path, [])
        assert rc == 1

    def test_allow_uncovered_turns_no_coverage_into_report_only(self, mod, tmp_path, monkeypatch):
        # Measurement runs may report unexecuted lines; a PR gate may not.
        monkeypatch.setattr(
            mod,
            "select",
            lambda *a, **k: self._selection(mod, no_coverage=[9]),
        )
        assert self._main(mod, tmp_path, ["--allow-uncovered"])[0] == 0
        assert self._main(mod, tmp_path, [])[0] == 1

    def test_zero_groups_refuse_an_empty_mutation_run(self, mod, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "select", lambda *a, **k: self._selection(mod, groups=[]))
        rc, _ = self._main(mod, tmp_path, ["--allow-uncovered"])
        assert rc == 1
