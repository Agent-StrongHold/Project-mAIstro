"""Tests for the release-consistency gate (#83).

The gate's only job is to fail when `VERSION`, `CHANGELOG.md` and `README.md`
stop telling one story. A gate that passes on a drifted set would launder
"0.9.0 developing toward 1.0.0" and "we released 1.0.0 and forgot to bump" as
the same state — which is exactly the ambiguity it exists to remove.

The checks run against synthetic files so the tests stay hermetic; one test
runs the shipped documents, because a gate nobody has pointed at the real repo
proves nothing about it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-release-consistency.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_release_consistency", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(
    gate,
    tmp_path: Path,
    *,
    version: str = "0.9.0",
    changelog: str | None = None,
    readme: str | None = None,
) -> None:
    """Point the gate at a synthetic repo."""
    if changelog is None:
        changelog = "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - TBD\n\nnotes\n"
    if readme is None:
        readme = (
            f"# Project\n\n{gate.README_BEGIN}\nversion 0.9.0, target 1.0.0\n{gate.README_END}\n"
        )
    (tmp_path / "VERSION").write_text(version + "\n")
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    (tmp_path / "README.md").write_text(readme)
    gate.VERSION_FILE = tmp_path / "VERSION"
    gate.CHANGELOG = tmp_path / "CHANGELOG.md"
    gate.README = tmp_path / "README.md"


# --- the state the repo is actually in ------------------------------------


def test_developing_toward_a_later_target_is_consistent(gate, tmp_path) -> None:
    """0.9.0 with a pending 1.0.0 is coherent, and must not be flagged."""
    _write(gate, tmp_path)

    assert gate.check() == []


def test_version_equal_to_the_target_is_consistent(gate, tmp_path) -> None:
    """The taggable state: bump lands, then the tag can be cut."""
    _write(
        gate,
        tmp_path,
        version="1.0.0",
        readme=f"{gate.README_BEGIN}\nversion 1.0.0, target 1.0.0\n{gate.README_END}",
    )

    assert gate.check() == []


# --- what it must catch ---------------------------------------------------


def test_a_version_above_the_pending_release_fails(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        version="1.1.0",
        readme=f"{gate.README_BEGIN}\nversion 1.1.0, target 1.0.0\n{gate.README_END}",
    )

    problems = gate.check()

    assert any("above the pending CHANGELOG release" in p for p in problems)


def test_a_dated_release_above_version_fails(gate, tmp_path) -> None:
    """You cannot have released a version the packages do not carry."""
    _write(
        gate,
        tmp_path,
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n## [2.0.0] - TBD\n\n## [1.5.0] - 2026-01-01\n"
        ),
        readme=f"{gate.README_BEGIN}\nversion 0.9.0, target 2.0.0\n{gate.README_END}",
    )

    problems = gate.check()

    assert any("records [1.5.0] as released" in p for p in problems)


def test_two_pending_releases_fail(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        changelog="# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - TBD\n\n## [1.1.0] - TBD\n",
    )

    problems = gate.check()

    assert any("exactly one pending release" in p for p in problems)


def test_no_pending_release_fails(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        changelog="# Changelog\n\n## [Unreleased]\n\n## [0.9.0] - 2026-01-01\n",
    )

    problems = gate.check()

    assert any("exactly one pending release" in p for p in problems)


def test_a_missing_unreleased_section_fails(gate, tmp_path) -> None:
    _write(gate, tmp_path, changelog="# Changelog\n\n## [1.0.0] - TBD\n")

    problems = gate.check()

    assert any("no '## [Unreleased]' section" in p for p in problems)


def test_an_rc_suffix_in_version_fails(gate, tmp_path) -> None:
    """Candidate-ness lives in the tag alone (ADR-073126-c4e1 §2)."""
    _write(gate, tmp_path, version="1.0.0-rc1")

    problems = gate.check()

    assert any("not a plain X.Y.Z" in p for p in problems)


def test_a_missing_readme_block_fails(gate, tmp_path) -> None:
    _write(gate, tmp_path, readme="# Project\n\nno block here\n")

    problems = gate.check()

    assert any("no release-status block" in p for p in problems)


def test_a_readme_block_naming_a_stale_version_fails(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        readme=f"{gate.README_BEGIN}\nversion 0.8.0, target 1.0.0\n{gate.README_END}",
    )

    problems = gate.check()

    assert any("does not name VERSION (0.9.0)" in p for p in problems)


def test_a_readme_block_naming_a_stale_target_fails(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        readme=f"{gate.README_BEGIN}\nversion 0.9.0, target 0.9.0\n{gate.README_END}",
    )

    problems = gate.check()

    assert any("does not name the release target (1.0.0)" in p for p in problems)


def test_an_unterminated_readme_block_is_not_a_block(gate, tmp_path) -> None:
    """A half-written marker must not read as a satisfied one."""
    _write(gate, tmp_path, readme=f"# P\n{gate.README_BEGIN}\nversion 0.9.0, target 1.0.0\n")

    problems = gate.check()

    assert any("no release-status block" in p for p in problems)


# --- the shipped documents ------------------------------------------------


def test_the_shipped_repo_tells_one_story() -> None:
    """The gate pointed at the real files, which is the claim that matters."""
    import subprocess

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "working toward" in result.stdout or "taggable" in result.stdout
