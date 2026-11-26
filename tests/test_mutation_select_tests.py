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
import types
from pathlib import Path
from typing import ClassVar

import pytest
from coverage import CoverageData

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mutation_select_tests.py"


def write_coverage_data(
    basename: Path, filename: str, contexts: dict[str, list[int]]
) -> CoverageData:
    """A real coverage data file with per-context line rows, written and re-opened.

    The selector reads per-test attribution from the data file the traced run
    wrote; these fixtures exercise that exact seam, not a mock of it.
    """
    data = CoverageData(basename=str(basename), suffix="")
    for context, lines in contexts.items():
        data.set_context(context)
        data.add_lines({filename: lines})
    data.write()
    fresh = CoverageData(basename=str(basename))
    fresh.read()
    return fresh


def rc_data_file(rc_path: Path) -> str:
    """The `data_file` value a coverage rc file declares."""
    for line in rc_path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("data_file"):
            return line.split("=", 1)[1].strip()
    raise AssertionError(f"fixture rc has no data_file: {rc_path}")


def fake_traced_run(
    coverage_payload: dict,
    *,
    data_contexts: dict[str, list[int]],
    source: str = "pkg/mod.py",
    collect_stdout: str = "tests/test_mod.py::test_add",
):
    """A subprocess.run stand-in modeling select()'s traced run.

    The pytest run "writes" a real coverage data file at the rc's declared
    data_file (per-test attribution lives there); the coverage report step
    writes the JSON payload (executed/missing lines only — the report no
    longer carries contexts). Returns (captured argvs, fake run callable).
    """
    captured: list[list[str]] = []

    def fake_run(argv, **kwargs):
        argv = [str(part) for part in argv]
        captured.append(argv)
        if "coverage" in argv:
            report = Path(argv[argv.index("-o") + 1])
            report.write_text(json.dumps(coverage_payload), encoding="utf-8")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        cov_config = next((a for a in argv if a.startswith("--cov-config=")), None)
        if cov_config is not None:
            rc = Path(cov_config.split("=", 1)[1])
            write_coverage_data(rc_data_file(rc), source, data_contexts)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if "--collect-only" in argv:
            return types.SimpleNamespace(returncode=0, stdout=collect_stdout, stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    return captured, fake_run


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
    def test_contexts_are_read_per_line_from_the_data_file(self, mod, tmp_path):
        filename = str(tmp_path / "mod.py")
        Path(filename).write_text("x = 1\ny = 2\n", encoding="utf-8")
        data = write_coverage_data(
            tmp_path / ".covdata",
            filename,
            {"": [5], "test_mod.test_add": [2]},  # 5 ran only at import time
        )
        by_line = mod.coverage_contexts(data, filename)
        assert by_line == {2: ["test_mod.test_add"]}  # empty-context lines drop out

    def test_a_missing_source_entry_is_an_error_not_silence(self, mod, tmp_path):
        filename = str(tmp_path / "mod.py")
        Path(filename).write_text("x = 1\n", encoding="utf-8")
        data = write_coverage_data(tmp_path / ".covdata", filename, {"": [1]})
        with pytest.raises(ValueError, match="no entry"):
            mod.coverage_contexts(data, str(tmp_path / "other.py"))

    def test_a_repo_relative_source_resolves_through_the_recorded_absolute_path(
        self, mod, tmp_path
    ):
        """The traced run records absolute paths; a repo-relative source must
        still find its rows through the unique-suffix fallback, and an
        ambiguous one must fail loudly rather than select nothing."""
        filename = str(tmp_path / "mod.py")
        Path(filename).write_text("x = 1\ny = 2\n", encoding="utf-8")
        data = write_coverage_data(tmp_path / ".covdata", filename, {"test_mod.test_add": [2]})
        relative_like = "/".join(Path(filename).parts[-2:])  # a suffix of the recorded path
        assert mod.coverage_contexts(data, relative_like) == {2: ["test_mod.test_add"]}
        with pytest.raises(ValueError, match="no entry"):
            mod.coverage_contexts(data, "somewhere/other.py")

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

        coverage_payload = {
            "files": {
                "pkg/mod.py": {
                    "executed_lines": [4],
                    "missing_lines": [],
                }
            }
        }
        _captured, fake_run = fake_traced_run(
            coverage_payload,
            data_contexts={"some_module.ghost_context": [4]},
        )

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        selection = mod.select("pkg/mod.py", "tests/test_mod.py", [4])
        assert selection.groups == []
        assert selection.no_coverage == [4]


class TestTheMeasuredScopeIsTheDeclaredSource:
    """The selector's own argv is part of its contract.

    pytest-cov's bare `--cov` means "record everything": it overrides the
    `--cov=<dir>` scope that the same argv passes. The gate CI red on (#330
    follow-up, PR #1994 head 2f21a0ab16) shows the shape: a test in the scope
    imports a module from a scratch directory that is deleted before the run
    ends (the extension lifecycle proof does exactly this), coverage traces the
    ephemeral file, and `coverage json --show-contexts` then dies with "No
    source for code" on the vanished path — the mutation gate cannot select
    tests at all. Measuring only the declared source directory keeps ephemeral
    code out of the data file, and the report step ignores reads of files that
    vanished mid-run without ever skipping the critical source itself (a
    missing critical-file entry still fails `_coverage_file_entry`).
    """

    def test_the_pytest_run_is_scoped_and_never_records_everything(
        self, mod, monkeypatch, tmp_path
    ):
        captured, fake_run = fake_traced_run(
            {"files": {"pkg/mod.py": {"executed_lines": [4], "missing_lines": []}}},
            data_contexts={"": [4], "test_mod.test_add": [4]},
        )

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        selection = mod.select("pkg/mod.py", "tests/test_mod.py", [4])
        pytest_argv = next(a for a in captured if "pytest" in a)
        bare = [a for a in pytest_argv if a == "--cov"]
        scoped = [a for a in pytest_argv if a.startswith("--cov=")]
        assert bare == [], "bare --cov means record-everything and overrides the scope"
        assert scoped == ["--cov=pkg"], "measure exactly the declared source directory"
        json_argv = next(a for a in captured if "coverage" in a)
        assert "--ignore-errors" in json_argv, (
            "a source file deleted mid-run must not end selection"
        )
        assert selection.groups == [{"lines": [4], "tests": ["tests/test_mod.py::test_add"]}]

    def test_the_report_step_never_serializes_contexts(self, mod, monkeypatch):
        """The gate killer this selection survived last: `coverage json
        --show-contexts` over a suite-wide run serializes every measured line
        of every file once per test that ran it — multi-GB for maistro-core's
        ~19k-test suite — and the parse outgrew the 16GB CI runner (run
        44700198260 died ~22.5m into that report with the data file already
        written). Per-test attribution lives in the data file; the report step
        must never be asked for contexts again."""
        captured, fake_run = fake_traced_run(
            {"files": {"pkg/mod.py": {"executed_lines": [4], "missing_lines": []}}},
            data_contexts={"": [4], "test_mod.test_add": [4]},
        )

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        selection = mod.select("pkg/mod.py", "tests/test_mod.py", [4])
        assert selection.groups == [{"lines": [4], "tests": ["tests/test_mod.py::test_add"]}]
        assert not any("--show-contexts" in argv for argv in captured), (
            "a contexts report is multi-GB at suite scale and its parse kills the gate; "
            "contexts are read from the data file"
        )

    def test_contexts_come_from_the_data_file_not_the_report(self, mod, monkeypatch):
        """The report carries no contexts at all here, yet both changed lines
        keep their own killing test — proving attribution is read from the
        data file the traced run wrote."""
        captured, fake_run = fake_traced_run(
            {"files": {"pkg/mod.py": {"executed_lines": [4], "missing_lines": []}}},
            data_contexts={"test_mod.test_add": [4]},
            collect_stdout="tests/test_mod.py::test_add\ntests/test_mod.py::TestX::test_y",
        )

        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        selection = mod.select("pkg/mod.py", "tests/test_mod.py", [4])
        assert selection.groups == [{"lines": [4], "tests": ["tests/test_mod.py::test_add"]}]
        report_argv = next(a for a in captured if "coverage" in a)
        assert "--show-contexts" not in report_argv

    def test_an_ephemeral_module_deleted_by_the_suite_does_not_break_selection(self, mod, tmp_path):
        """The real failure, small: the scope imports scratch code that deletes
        itself before the coverage report is written. Under the old argv this
        exact sequence reded `coverage json` with "No source for code"."""
        pytest.importorskip("pytest_cov")
        src_dir = tmp_path / "sel_pkg"
        src_dir.mkdir()
        (src_dir / "__init__.py").write_text("", encoding="utf-8")
        (src_dir / "calc.py").write_text(
            "THREE = 3\n\n\ndef add(a, b):\n    return a + b\n",
            encoding="utf-8",
        )
        ephemeral = tmp_path / "ephemeral-scratch"
        ephemeral.mkdir()
        (ephemeral / "greeter.py").write_text("VALUE = 41\n", encoding="utf-8")
        tests_dir = tmp_path / "sel_tests"
        tests_dir.mkdir()
        (tests_dir / "test_calc.py").write_text(
            "import importlib.util\nimport shutil\nfrom pathlib import Path\n\n"
            "from sel_pkg.calc import add\n\n\n"
            "def test_add():\n    assert add(1, 2) == 3\n\n\n"
            "def test_imports_ephemeral_code_then_it_vanishes():\n"
            f"    path = Path({str(ephemeral / 'greeter.py')!r})\n"
            "    spec = importlib.util.spec_from_file_location('greeter', path)\n"
            "    module = importlib.util.module_from_spec(spec)\n"
            "    spec.loader.exec_module(module)\n"
            "    assert module.VALUE == 41\n"
            "    shutil.rmtree(path.parent)\n",
            encoding="utf-8",
        )
        selection = mod.select(
            str(src_dir / "calc.py"),
            str(tests_dir),
            [5],  # `return a + b`
            env_extra={"PYTHONPATH": f"{tmp_path}:{mod._package_pythonpath()}"},
        )
        assert selection.groups, "the scoped run still selects the killing test"
        # Collected node ids are printed root-relative for an out-of-tree
        # absolute tests path, so the stem carries no `sel_tests/` prefix.
        assert {t for g in selection.groups for t in g["tests"]} == {"test_calc.py::test_add"}


class TestARedBaselineAbortsSelection:
    def test_selection_refuses_to_rank_lines_on_a_red_baseline(self, mod, monkeypatch):

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
