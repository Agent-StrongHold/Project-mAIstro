"""Tests for coverage-based per-line test selection (#330).

A mutant can only be killed by a test that executes its line. The selector
turns recorded coverage contexts into per-line test sets and groups changed
lines by identical test sets. The dangerous failures are all silent ones —
a context that fails to resolve, a parametrized test that drops its
parameters, a changed line nothing executes — and each is pinned here.
"""

from __future__ import annotations

import importlib.util
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
            "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n",
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
            [2, 6],
            env_extra={"PYTHONPATH": f"{tmp_path}:{mod._package_pythonpath()}"},
        )
        tests_by_line = {line: set(g["tests"]) for g in selection.groups for line in g["lines"]}
        assert tests_by_line[2], "line 2 (return a + b) has no selected test"
        assert tests_by_line[6], "line 6 (return a * b) has no selected test"
        assert tests_by_line[2] != tests_by_line[6], "each line keeps its own killing test"
