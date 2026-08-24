"""Tests for `scripts/check-merge-markers.py` (#154).

The gate is trivial to write and easy to get subtly wrong in the direction that
matters: too eager and it fails on a Markdown setext underline or a diff quoted
in a document, too lax and it misses the thing that actually reached `develop`.
Both directions are pinned here.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-merge-markers.py"

OURS = "<<<<<<< HEAD"
SEP = "======="
THEIRS = ">>>>>>> origin/develop"


@pytest.fixture(scope="module")
def gate():
    """The script, imported as a module so its helpers can be called directly."""
    spec = importlib.util.spec_from_file_location("check_merge_markers", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_merge_markers"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo, because the gate's scope is `git ls-files`."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(repo)],
        capture_output=True,
        text=True,
    )


def _track(repo: Path, name: str, body: str) -> Path:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", name], cwd=repo, check=True)
    return path


# --------------------------------------------------------------------------
# What must fail
# --------------------------------------------------------------------------


def test_a_full_conflict_block_fails(gate, repo: Path) -> None:
    """The exact shape that reached `develop`: a markdown table with a block in
    it, where every other gate still saw a well-formed table."""
    path = _track(
        repo,
        "docs/testing/SUITE-INVENTORY.md",
        f"| Suite | Node IDs |\n|---|---:|\n{OURS}\n| `tests/` | 927 |\n{SEP}\n{THEIRS}\n",
    )

    found = gate._markers_in(path)

    assert [line for _n, line in found] == [OURS, SEP, THEIRS]


def test_an_unresolved_block_in_source_fails(gate, repo: Path) -> None:
    path = _track(repo, "a.py", f"{OURS}\nx = 1\n{SEP}\nx = 2\n{THEIRS}\n")

    assert [n for n, _line in gate._markers_in(path)] == [1, 3, 5]


def test_the_process_exits_nonzero_and_names_the_file(repo: Path) -> None:
    """End-to-end, since CI reads the exit status and a human reads stderr."""
    _track(repo, "a.md", f"{OURS}\nx\n{SEP}\ny\n{THEIRS}\n")

    result = _run(repo)

    assert result.returncode == 1
    assert "a.md:1" in result.stderr
    assert "a.md:5" in result.stderr


# --------------------------------------------------------------------------
# What must not fail
# --------------------------------------------------------------------------


def test_a_setext_underline_alone_is_not_a_finding(gate, repo: Path) -> None:
    """`=======` under a line of text is a Markdown heading. Reporting it would
    make the gate unusable in exactly the documents it is here to protect."""
    path = _track(repo, "a.md", f"Title\n{SEP}\n\nBody.\n")

    assert gate._markers_in(path) == []


def test_a_separator_is_reported_only_beside_a_labelled_marker(gate, repo: Path) -> None:
    """The separator is ambiguous on its own and unambiguous next to a label."""
    clean = _track(repo, "clean.md", f"Heading\n{SEP}\n")
    dirty = _track(repo, "dirty.md", f"{OURS}\na\n{SEP}\nb\n{THEIRS}\n")

    assert gate._markers_in(clean) == []
    assert SEP in [line for _n, line in gate._markers_in(dirty)]


def test_an_untracked_file_is_out_of_scope(repo: Path) -> None:
    """A scratch file or a vendored virtualenv must not fail someone's build."""
    (repo / "scratch.md").write_text(f"{OURS}\nx\n{SEP}\ny\n{THEIRS}\n", encoding="utf-8")

    assert _run(repo).returncode == 0


def test_a_binary_file_is_skipped_rather_than_guessed_at(gate, repo: Path) -> None:
    path = repo / "blob.bin"
    path.write_bytes(b"\x00\xff\xfe" + OURS.encode() + b"\x00")
    subprocess.run(["git", "add", "blob.bin"], cwd=repo, check=True)

    assert gate._markers_in(path) == []


def test_an_unmerged_path_is_reported_once(gate) -> None:
    """`git ls-files` prints an unmerged path once per stage, so the file this
    gate exists to catch is the file most likely to be listed three times."""
    files = gate._tracked_files()

    assert len(files) == len(set(files))


# --------------------------------------------------------------------------
# This repository
# --------------------------------------------------------------------------


def test_this_repository_is_clean() -> None:
    """The gate's own subject. Kept as a test as well as a CI step so a marker
    fails the suite a developer runs locally, not only the pipeline."""
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
