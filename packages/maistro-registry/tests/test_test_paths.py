"""Cited `tests:` paths must resolve to a real file (#812, AC-1/AC-3).

`schema.FrontMatter` accepts `tests:` as strings; `test_paths.check_test_paths`
is the gate that makes those strings resolve. These tests pin the resolution
contract: node-id suffixes are stripped, existing files and suite directories
resolve, missing paths and paths escaping the repository root do not.
"""

from __future__ import annotations

from pathlib import Path

from maistro_registry.schema import FrontMatter
from maistro_registry.test_paths import check_test_paths, file_portion_of


def _fm(tests: list[str]) -> FrontMatter:
    return FrontMatter.model_validate(
        {
            "id": "SPEC-001",
            "title": "A real record",
            "repo": "maistro-engine",
            "kind": "spec",
            "status": "Proposed",
            "created": "2026-06-10",
            "tests": tests,
            "layer": "Foundation",
            "owners": ["@someone"],
        }
    )


def _make_tree(tmp_path: Path) -> Path:
    (tmp_path / "packages" / "x" / "tests").mkdir(parents=True)
    (tmp_path / "packages" / "x" / "tests" / "test_real.py").write_text(
        "def test_ok():\n    pass\n"
    )
    return tmp_path


def test_file_portion_strips_node_id() -> None:
    assert file_portion_of("packages/x/tests/test_real.py::test_ok") == (
        "packages/x/tests/test_real.py"
    )
    assert file_portion_of("packages/x/tests/test_real.py::TestC::test_ok") == (
        "packages/x/tests/test_real.py"
    )
    assert file_portion_of("packages/x/tests/test_real.py") == "packages/x/tests/test_real.py"


def test_existing_file_and_directory_resolve(tmp_path: Path) -> None:
    root = _make_tree(tmp_path)
    problems = check_test_paths(
        [_fm(["packages/x/tests/test_real.py::test_ok", "packages/x/tests/"])], root
    )
    assert problems == []


def test_dead_file_path_is_a_problem(tmp_path: Path) -> None:
    root = _make_tree(tmp_path)
    problems = check_test_paths([_fm(["packages/x/tests/test_gone.py"])], root)
    assert len(problems) == 1
    (p,) = problems
    assert p.source == "maistro-engine#SPEC-001"
    assert p.entry == "packages/x/tests/test_gone.py"
    assert "does not exist" in p.reason
    assert p.render() == (
        "maistro-engine#SPEC-001.tests -> packages/x/tests/test_gone.py: "
        "does not exist under the repository root"
    )


def test_dead_directory_and_empty_portion_are_problems(tmp_path: Path) -> None:
    root = _make_tree(tmp_path)
    problems = check_test_paths([_fm(["packages/x/tests/gone/", "::test_orphan"])], root)
    # Entries are quoted verbatim: a suite-directory citation and a bare node
    # id are different failure shapes and must stay distinguishable.
    assert [p.entry for p in problems] == ["packages/x/tests/gone/", "::test_orphan"]
    assert "empty file path" in problems[1].reason


def test_node_id_alone_cannot_resolve(tmp_path: Path) -> None:
    # A dead file with a node id must fail on the file portion, not pass
    # because the entry as a whole "looks like" a pytest reference.
    root = _make_tree(tmp_path)
    problems = check_test_paths([_fm(["packages/x/tests/test_gone.py::test_ok"])], root)
    assert len(problems) == 1
    # The failure is about the file portion: what the node id names is never
    # reached, and file_portion_of recovers exactly the part that was checked.
    assert file_portion_of(problems[0].entry) == "packages/x/tests/test_gone.py"


def test_path_escaping_the_repository_root_is_a_problem(tmp_path: Path) -> None:
    root = _make_tree(tmp_path)
    outside = tmp_path.parent / "outside-tests"
    outside.mkdir(exist_ok=True)
    (outside / "test_elsewhere.py").write_text("def test_ok():\n    pass\n")
    problems = check_test_paths([_fm(["../outside-tests/test_elsewhere.py"])], root)
    assert len(problems) == 1
    assert "escapes the repository root" in problems[0].reason
