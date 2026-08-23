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


def _status(released: str = "none", current: str = "0.9.0", target: str = "1.0.0") -> str:
    """A release-status block with the three labelled fields the gate reads."""
    return (
        f"**Released:** {released} - **Version in the tree:** {current} - "
        f"**Next release target:** {target}"
    )


def _write(
    gate,
    tmp_path: Path,
    *,
    version: str = "0.9.0",
    changelog: str | None = None,
    readme: str | None = None,
    tags: list[str] | None = None,
) -> None:
    """Point the gate at a synthetic repo, with a synthetic tag list."""
    if changelog is None:
        changelog = "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - TBD\n\nnotes\n"
    if readme is None:
        readme = f"# Project\n\n{gate.README_BEGIN}\n{_status()}\n{gate.README_END}\n"
    (tmp_path / "VERSION").write_text(version + "\n")
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    (tmp_path / "README.md").write_text(readme)
    gate.VERSION_FILE = tmp_path / "VERSION"
    gate.CHANGELOG = tmp_path / "CHANGELOG.md"
    gate.README = tmp_path / "README.md"
    # Tags are real repository state, so the synthetic cases stub the reader
    # rather than creating tags in the checkout the suite runs from.
    gate.list_release_tags = lambda: list(tags or [])


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
        readme=f"{gate.README_BEGIN}\n{_status(current='1.0.0')}\n{gate.README_END}",
    )

    assert gate.check() == []


# --- what it must catch ---------------------------------------------------


def test_a_version_above_the_pending_release_fails(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        version="1.1.0",
        readme=f"{gate.README_BEGIN}\n{_status(current='1.1.0')}\n{gate.README_END}",
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
        readme=f"{gate.README_BEGIN}\n{_status(target='2.0.0')}\n{gate.README_END}",
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
        readme=f"{gate.README_BEGIN}\n{_status(current='0.8.0')}\n{gate.README_END}",
    )

    problems = gate.check()

    assert any("version in the tree is 0.8.0, but VERSION says 0.9.0" in p for p in problems)


def test_a_readme_block_naming_a_stale_target_fails(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        readme=f"{gate.README_BEGIN}\n{_status(target='0.9.0')}\n{gate.README_END}",
    )

    problems = gate.check()

    assert any("next release target is 0.9.0" in p for p in problems)


def test_an_unterminated_readme_block_is_not_a_block(gate, tmp_path) -> None:
    """A half-written marker must not read as a satisfied one."""
    _write(gate, tmp_path, readme=f"# P\n{gate.README_BEGIN}\n{_status()}\n")

    problems = gate.check()

    assert any("no release-status block" in p for p in problems)


# --- the date field is evidence, so it has to be a date -------------------


@pytest.mark.parametrize("when", ["TBA", "2026-99-99", "soon", "23/08/2026", ""])
def test_a_heading_date_that_is_not_a_date_fails(gate, tmp_path, when: str) -> None:
    """Release state is read from this field and nothing else.

    Accepting arbitrary text meant `## [1.0.0] - TBA` counted as evidence that
    1.0.0 had shipped, purely because it was not the string `TBD`.
    """
    _write(
        gate,
        tmp_path,
        version="1.0.0",
        changelog=(f"# Changelog\n\n## [Unreleased]\n\n## [1.1.0] - TBD\n\n## [1.0.0] - {when}\n"),
        readme=f"{gate.README_BEGIN}\n{_status(current='1.0.0', target='1.1.0')}\n{gate.README_END}",
    )

    problems = gate.check()

    assert any("neither 'TBD' nor an ISO date" in p for p in problems)


def test_a_real_iso_date_is_accepted(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        version="1.0.0",
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n## [1.1.0] - TBD\n\n## [1.0.0] - 2026-08-23\n"
        ),
        readme=f"{gate.README_BEGIN}\n{_status(current='1.0.0', target='1.1.0')}\n{gate.README_END}",
    )

    assert gate.check() == []


# --- a version is pending or released, never both -------------------------


def test_a_version_that_is_both_pending_and_released_fails(gate, tmp_path) -> None:
    """One pending heading and one dated heading equal to VERSION.

    Every other check passes on this: exactly one pending release, VERSION at
    the target, nothing dated above it. `release_notes.py` would publish
    whichever section it reached first.
    """
    _write(
        gate,
        tmp_path,
        version="1.0.0",
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - TBD\n\n## [1.0.0] - 2026-08-23\n"
        ),
        readme=f"{gate.README_BEGIN}\n{_status(current='1.0.0')}\n{gate.README_END}",
    )

    problems = gate.check()

    assert any("more than one heading" in p for p in problems)


# --- the README's fields are labelled, so one cannot stand in for another --


def test_a_stale_current_version_is_not_covered_by_the_target(gate, tmp_path) -> None:
    """The unsoundness that made containment the wrong test.

    Promoting the target makes VERSION and the target the same number. A README
    left claiming the old current version used to pass, because the target's
    occurrence satisfied the VERSION check and the same occurrence satisfied the
    target check.
    """
    _write(
        gate,
        tmp_path,
        version="1.0.0",
        changelog="# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - TBD\n",
        readme=f"{gate.README_BEGIN}\n{_status(current='0.9.0')}\n{gate.README_END}",
    )

    problems = gate.check()

    assert any("version in the tree is 0.9.0, but VERSION says 1.0.0" in p for p in problems)


@pytest.mark.parametrize("field", ["Released", "Version in the tree", "Next release target"])
def test_a_block_missing_any_labelled_field_fails(gate, tmp_path, field: str) -> None:
    block = _status().replace(f"**{field}:**", "")
    _write(gate, tmp_path, readme=f"{gate.README_BEGIN}\n{block}\n{gate.README_END}")

    problems = gate.check()

    assert any("has no" in p and "field" in p for p in problems)


# --- tags are the only record of what was actually published ---------------


def test_a_readme_claiming_nothing_released_fails_once_a_tag_exists(gate, tmp_path) -> None:
    """The claim this gate used to make and never check.

    Before tags were read, `Released: none` stayed true-looking forever: the
    first `v*` tag made it false and every subsequent CI run still passed.
    """
    _write(
        gate,
        tmp_path,
        version="1.0.0",
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n## [1.1.0] - TBD\n\n## [1.0.0] - 2026-08-23\n"
        ),
        readme=f"{gate.README_BEGIN}\n{_status(current='1.0.0', target='1.1.0')}\n{gate.README_END}",
        tags=["v1.0.0"],
    )

    problems = gate.check()

    assert any(
        "released version is none, but the repository's tags say 1.0.0" in p for p in problems
    )


def test_a_readme_naming_the_released_tag_passes(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        version="1.0.0",
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n## [1.1.0] - TBD\n\n## [1.0.0] - 2026-08-23\n"
        ),
        readme=(
            f"{gate.README_BEGIN}\n"
            f"{_status(released='1.0.0', current='1.0.0', target='1.1.0')}\n"
            f"{gate.README_END}"
        ),
        tags=["v1.0.0"],
    )

    assert gate.check() == []


def test_a_release_candidate_tag_is_not_a_release(gate, tmp_path) -> None:
    """`vX.Y.Z-rcN` is a candidate; `release_guard.py` treats it as one too."""
    _write(gate, tmp_path, tags=["v1.0.0-rc1", "v1.0.0-rc2"])

    assert gate.check() == []


def test_the_tag_being_released_is_excluded(gate, tmp_path) -> None:
    """At tag time the tag exists, but the commit it points at predates it.

    Without the exclusion, the release workflow's own consistency step would
    demand a README that could not have been written yet.
    """
    _write(
        gate,
        tmp_path,
        version="1.0.0",
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n## [1.1.0] - TBD\n\n## [1.0.0] - 2026-08-23\n"
        ),
        readme=f"{gate.README_BEGIN}\n{_status(current='1.0.0', target='1.1.0')}\n{gate.README_END}",
        tags=["v1.0.0"],
    )

    assert gate.check(releasing="v1.0.0") == []
    assert gate.check() != []


def test_a_tag_above_version_fails(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        version="0.9.0",
        readme=f"{gate.README_BEGIN}\n{_status(released='1.0.0')}\n{gate.README_END}",
        tags=["v1.0.0"],
    )

    problems = gate.check()

    assert any("cannot be above the version the packages carry" in p for p in problems)


def test_a_tag_without_dated_notes_fails(gate, tmp_path) -> None:
    """A published release has to have notes, and they have to be dated."""
    _write(
        gate,
        tmp_path,
        version="1.0.0",
        changelog="# Changelog\n\n## [Unreleased]\n\n## [1.1.0] - TBD\n",
        readme=(
            f"{gate.README_BEGIN}\n"
            f"{_status(released='1.0.0', current='1.0.0', target='1.1.0')}\n"
            f"{gate.README_END}"
        ),
        tags=["v1.0.0"],
    )

    problems = gate.check()

    assert any("has no dated '## [1.0.0]' heading" in p for p in problems)


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
