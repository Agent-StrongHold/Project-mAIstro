"""Protected test inventory (#306): collection, skip-diff, and the diff that
makes deletions/renames/disables visible. These run REAL pytest collection
against tiny tmp_path trees — collection only, never a test execution — so they
stay fast while proving the parser and the differential skip pass against
pytest's actual output format."""

from __future__ import annotations

import subprocess
from pathlib import Path
from subprocess import TimeoutExpired

import pytest

from maistro_rsi.test_inventory import (
    InventoryResult,
    changed_config_files,
    collect_inventory,
    diff_inventory,
    skipped_ids,
)
from maistro_rsi.test_inventory import test_config_paths as the_config_surface

PYTEST_PROJECT = """\
[tool.pytest.ini_options]
testpaths = ["tests"]
"""


def _make_project(
    root: Path, test_files: dict[str, str], config: str | None = PYTEST_PROJECT
) -> Path:
    """A minimal pytest project: a pyproject.toml with a tests/ root plus the
    given test files (path -> content)."""
    root.mkdir(parents=True, exist_ok=True)
    if config is not None:
        (root / "pyproject.toml").write_text(config, encoding="utf-8")
    for rel, body in test_files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return root


TWO_TESTS = {
    "tests/test_a.py": "def test_one():\n    assert 1\n\n\ndef test_two():\n    assert 2\n",
    "tests/test_b.py": "def test_other():\n    assert 3\n",
}

MARKED = {
    "tests/test_m.py": (
        "import pytest\n\n\n"
        "def test_plain():\n"
        "    assert 1\n\n\n"
        "@pytest.mark.skip(reason='always')\n"
        "def test_skipped():\n"
        "    assert 2\n\n\n"
        "@pytest.mark.skipif(True, reason='cond')\n"
        "def test_skipif():\n"
        "    assert 3\n\n\n"
        "@pytest.mark.xfail\n"
        "def test_xfail():\n"
        "    assert 4\n"
    ),
}


# --- collection -----------------------------------------------------------


def test_collect_inventory_parses_node_ids(tmp_path: Path) -> None:
    inv = collect_inventory(_make_project(tmp_path, TWO_TESTS), [])
    assert inv.collection_ok is True
    assert inv.collected == {
        "tests/test_a.py::test_one",
        "tests/test_a.py::test_two",
        "tests/test_b.py::test_other",
    }
    # No skip markers: everything is servable.
    assert inv.servable == inv.collected
    assert inv.skip_gated == set()


def test_collect_inventory_fails_when_zero_collected_with_suite_present(tmp_path: Path) -> None:
    # A -k filter matching nothing collects zero tests while the suite exists —
    # the exact config-based hiding the gate exists to catch.
    inv = collect_inventory(_make_project(tmp_path, TWO_TESTS), ["-k", "matches_nothing"])
    assert inv.collection_ok is False
    assert "no tests collected" in (inv.collection_error or "")


def test_collect_inventory_fails_on_collection_error(tmp_path: Path) -> None:
    project = _make_project(tmp_path, TWO_TESTS)
    (project / "tests" / "test_broken.py").write_text(
        "import nonexistent_module_xyz\n\n\ndef test_x():\n    pass\n", encoding="utf-8"
    )
    inv = collect_inventory(project, [])
    assert inv.collection_ok is False
    assert "full pass exit" in (inv.collection_error or "")


def test_collect_inventory_ok_when_tree_has_no_tests_at_all(tmp_path: Path) -> None:
    # Nothing to protect: an empty tree is not a collection failure.
    inv = collect_inventory(_make_project(tmp_path, {}, config=None), [])
    assert inv.collection_ok is True
    assert inv.collected == set()


def test_collect_inventory_times_out_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _hang(*args: object, **kwargs: object) -> None:
        raise TimeoutExpired(cmd="pytest", timeout=1)

    monkeypatch.setattr(subprocess, "run", _hang)
    inv = collect_inventory(_make_project(tmp_path, TWO_TESTS), [], timeout=1)
    assert inv.collection_ok is False
    assert "timed out" in (inv.collection_error or "")


# --- skip detection (differential collection) ------------------------------


def test_skipped_ids_via_differential_collection(tmp_path: Path) -> None:
    root = _make_project(tmp_path, MARKED)
    gated = skipped_ids(root, [])
    assert gated == {"tests/test_m.py::test_skipped", "tests/test_m.py::test_skipif"}
    # xfail is NOT skip-gated — it still runs (and reports), so it stays protected.
    inv = collect_inventory(root, [])
    assert inv.collected == inv.servable | gated
    assert "tests/test_m.py::test_xfail" in inv.servable


def test_newly_added_skip_marker_reads_as_a_deletion(tmp_path: Path) -> None:
    # The candidate's whole trick: the test still collects (the ID is there),
    # but it is deselected at run time. The servable-set diff must catch it.
    root = _make_project(tmp_path, TWO_TESTS)
    base = collect_inventory(root, [])
    (root / "tests" / "test_a.py").write_text(
        "import pytest\n\n\n"
        "@pytest.mark.skip(reason='gone')\n"
        "def test_one():\n"
        "    assert 1\n\n\n"
        "def test_two():\n"
        "    assert 2\n",
        encoding="utf-8",
    )
    cand = collect_inventory(root, [])
    assert "tests/test_a.py::test_one" in cand.collected  # still collected...
    diff = diff_inventory(base, cand)
    assert diff.deleted == ["tests/test_a.py::test_one"]  # ...but no longer protected
    assert diff.unchanged_count == 2  # test_two + test_other


# --- diff semantics --------------------------------------------------------


def _inv(ids: set[str]) -> InventoryResult:
    return InventoryResult(collected=set(ids), servable=set(ids))


def test_diff_reports_deletion_and_addition() -> None:
    diff = diff_inventory(_inv({"a::x", "a::y"}), _inv({"a::y", "b::z"}))
    assert diff.deleted == ["a::x"]
    assert diff.added == ["b::z"]
    assert diff.unchanged_count == 1
    assert diff.shrinks is True


def test_diff_treats_rename_as_deletion() -> None:
    diff = diff_inventory(_inv({"tests/test_x.py::test_old"}), _inv({"tests/test_x.py::test_new"}))
    assert diff.deleted == ["tests/test_x.py::test_old"]
    assert diff.added == ["tests/test_x.py::test_new"]
    assert diff.shrinks is True


def test_diff_clean_candidate_shrinks_false() -> None:
    diff = diff_inventory(_inv({"a::x"}), _inv({"a::x", "b::z"}))
    assert diff.deleted == []
    assert diff.shrinks is False
    assert diff.unchanged_count == 1


def test_diff_ignores_tests_skip_gated_on_both_sides() -> None:
    # A test that was already skip-gated in the base and stays gated is not a
    # new loss; un-gating it counts as an addition (a genuine improvement).
    base = InventoryResult(
        collected={"a::x", "a::gated"},
        servable={"a::x"},
    )
    cand = InventoryResult(collected={"a::x", "a::gated"}, servable={"a::x", "a::gated"})
    diff = diff_inventory(base, cand)
    assert diff.deleted == []
    assert diff.added == ["a::gated"]


# --- test-config surface ---------------------------------------------------


def test_test_config_paths_names_the_pytest_config_surface() -> None:
    assert the_config_surface() == frozenset(
        {"pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini", "conftest.py"}
    )


def test_changed_config_files_flags_config_edits_at_any_depth() -> None:
    changed = [
        "pyproject.toml",
        "packages/rsi/tests/conftest.py",
        "pkg/setup.cfg",
        "tox.ini",
        "deep/nested/pytest.ini",
        "src/mod.py",
        "tests/test_a.py",
    ]
    assert changed_config_files(changed) == [
        "pyproject.toml",
        "packages/rsi/tests/conftest.py",
        "pkg/setup.cfg",
        "tox.ini",
        "deep/nested/pytest.ini",
    ]
    assert changed_config_files([]) == []


def test_config_based_deselection_shrinks_the_collected_set(tmp_path: Path) -> None:
    # addopts with -k inside pyproject.toml: the config edit, not a file
    # deletion, hides the test — the collected set must still shrink.
    root = _make_project(tmp_path, TWO_TESTS)
    base = collect_inventory(root, [])
    (root / "pyproject.toml").write_text(
        PYTEST_PROJECT + 'addopts = "-k test_one"\n', encoding="utf-8"
    )
    cand = collect_inventory(root, [])
    diff = diff_inventory(base, cand)
    assert diff.deleted == ["tests/test_a.py::test_two", "tests/test_b.py::test_other"]


@pytest.mark.parametrize("marker", ["skip", "skipif"])
def test_marker_variants_both_leave_servable(tmp_path: Path, marker: str) -> None:
    body = (
        "import pytest\n\n\n"
        f"@pytest.mark.{marker}"
        + ("(True, reason='cond')\n" if marker == "skipif" else "(reason='always')\n")
        + "def test_m():\n"
        "    assert 1\n"
    )
    inv = collect_inventory(_make_project(tmp_path, {"tests/test_m.py": body}), [])
    assert inv.collected == {"tests/test_m.py::test_m"}
    assert inv.servable == set()
    assert inv.skip_gated == {"tests/test_m.py::test_m"}
