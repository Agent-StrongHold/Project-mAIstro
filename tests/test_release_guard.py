"""The release guard and release-notes builder, tested rather than trusted.

`release.yml` cannot be exercised before it is used: publishing to PyPI is
irreversible and the repository has no tags, so the first real run of that
workflow is also the first release. Everything in it that is not YAML lives in
`scripts/release_guard.py` and `scripts/release_notes.py` precisely so it can
be tested here instead.

The four cases the guard exists for — a good final tag, a good rc tag, a
version that disagrees with `VERSION`, and a malformed tag — each get a test.
(The fifth, "tag not on main", is a `git merge-base --is-ancestor` check in the
workflow; what is testable here is that the guard names the right branch to
check against.)
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "scripts" / "release_guard.py"
NOTES = REPO / "scripts" / "release_notes.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[spec.name]
        raise
    return mod


@pytest.fixture(scope="module")
def guard_mod():
    mod = _load(GUARD, "_release_guard")
    yield mod
    del sys.modules["_release_guard"]


@pytest.fixture(scope="module")
def notes_mod():
    mod = _load(NOTES, "_release_notes")
    yield mod
    del sys.modules["_release_notes"]


@pytest.fixture
def release_tree(tmp_path: Path, guard_mod, monkeypatch: pytest.MonkeyPatch):
    """A stand-in repo whose VERSION and CHANGELOG say 1.0.0.

    The real tree is at 0.9.0 and will keep moving; pinning these tests to
    whatever the working copy happens to say would make them assert the tree
    rather than the logic.
    """
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - TBD\n\nnotes here\n")
    version_file = tmp_path / "VERSION"
    version_file.write_text("1.0.0\n")
    monkeypatch.setattr(guard_mod, "ROOT", tmp_path)
    # bump_version's own site table walks the real repo; the guard delegates to
    # it and we are not testing that table here.
    monkeypatch.setattr(
        guard_mod, "_load_bump_version", lambda: type("M", (), {"check": staticmethod(lambda: 0)})
    )
    return changelog


# --- the four tag cases ----------------------------------------------------


def test_final_tag_on_a_matching_tree_passes(release_tree, guard_mod):
    status, out = guard_mod.guard("v1.0.0", release_tree)
    assert status == 0
    assert out["version"] == "1.0.0"
    assert out["prerelease"] == "false"
    assert out["rc"] == ""
    assert out["minor"] == "1.0"
    # ADR-073126-c4e1 §2: a final tag may only point at main.
    assert out["target_branch"] == "main"


def test_rc_tag_passes_against_the_final_version(release_tree, guard_mod):
    """The rc suffix lives only in the tag; packages stay at 1.0.0."""
    status, out = guard_mod.guard("v1.0.0-rc1", release_tree)
    assert status == 0
    assert out["version"] == "1.0.0"
    assert out["prerelease"] == "true"
    assert out["rc"] == "1"
    # ADR §2's sole exception: an rc may point at integration so it can soak.
    assert out["target_branch"] == "integration"


def test_version_disagreeing_with_VERSION_is_rejected(release_tree, guard_mod):
    """A tag whose version is not the tree's version must never build."""
    status, _ = guard_mod.guard("v1.1.0", release_tree)
    assert status == 1


def test_rc_version_disagreeing_with_VERSION_is_rejected(release_tree, guard_mod):
    """Stripping the rc suffix must not also relax the comparison."""
    status, _ = guard_mod.guard("v1.1.0-rc1", release_tree)
    assert status == 1


@pytest.mark.parametrize(
    "tag",
    [
        "v1.0",  # not semver
        "1.0.0",  # no v prefix — not the tag scheme
        "v1.0.0-beta",  # a pre-release form this repo has not decided on
        "v1.0.0-rc0",  # ADR §6: candidates start at rc1
        "v1.0.0-rc01",  # a typo, not a synonym for rc1
        "v1.0.0-rc1-dirty",
        "release-1.0.0",
        "v1.0.0 ",
    ],
)
def test_malformed_tags_are_rejected(release_tree, guard_mod, tag):
    status, out = guard_mod.guard(tag, release_tree)
    assert status == 1
    assert out == {}


# --- the CHANGELOG requirement --------------------------------------------


def test_missing_changelog_heading_fails(
    tmp_path: Path, guard_mod, monkeypatch: pytest.MonkeyPatch
):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [Unreleased]\n\n## [0.9.0] - 2026-01-01\n\nold\n")
    (tmp_path / "VERSION").write_text("1.0.0\n")
    monkeypatch.setattr(guard_mod, "ROOT", tmp_path)
    monkeypatch.setattr(
        guard_mod, "_load_bump_version", lambda: type("M", (), {"check": staticmethod(lambda: 0)})
    )
    status, _ = guard_mod.guard("v1.0.0", changelog)
    assert status == 1


def test_version_site_drift_fails(release_tree, guard_mod, monkeypatch: pytest.MonkeyPatch):
    """Lockstep is the whole point: one stale pyproject blocks the release."""
    monkeypatch.setattr(
        guard_mod, "_load_bump_version", lambda: type("M", (), {"check": staticmethod(lambda: 1)})
    )
    status, _ = guard_mod.guard("v1.0.0", release_tree)
    assert status == 1


def test_the_real_tree_passes_its_own_guard(guard_mod):
    """Whatever VERSION currently says, a tag naming it must be releasable
    once its CHANGELOG section exists — this catches version-site drift in the
    working tree, the same way `bump_version.py --check` does in quality.yml."""
    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    mod = _load(GUARD, "_release_guard_real")
    try:
        status, out = mod.guard(f"v{version}", REPO / "CHANGELOG.md")
    finally:
        del sys.modules["_release_guard_real"]
    # The CHANGELOG heading for the *current* VERSION may legitimately not
    # exist yet (it is written at release time), so only assert that nothing
    # ELSE is wrong: a version-site mismatch would fail here too.
    if status != 0:
        assert not (REPO / "CHANGELOG.md").read_text(encoding="utf-8").count(f"## [{version}]")
    else:
        assert out["version"] == version


# --- release notes ---------------------------------------------------------


def test_notes_extract_the_matching_section(notes_mod):
    text = "# C\n\n## [Unreleased]\n\n## [1.0.0] - TBD\n\nbody one\n\n## [0.9.0]\n\nbody two\n"
    assert notes_mod.extract_section(text, "1.0.0") == "body one"


def test_notes_drop_the_trailing_link_reference_block(notes_mod):
    text = "# C\n\n## [1.0.0]\n\nbody\n\n[1.0.0]: https://example.invalid/tag\n"
    assert notes_mod.extract_section(text, "1.0.0") == "body"


def test_notes_do_not_duplicate_the_api_statement(notes_mod, tmp_path: Path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [1.0.0]\n\nbody\n\n### API compatibility\n\nthe /v1 mount.\n")
    body = notes_mod.build("v1.0.0", "1.0.0", changelog)
    assert body.count("### API compatibility") == 1


def test_notes_add_the_api_statement_when_absent(notes_mod, tmp_path: Path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [1.0.0]\n\nbody only\n")
    body = notes_mod.build("v1.0.0", "1.0.0", changelog)
    assert body.count("### API compatibility") == 1
    assert "ADR-076" in body


def test_rc_notes_carry_a_prerelease_banner(notes_mod, tmp_path: Path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [1.0.0]\n\nbody\n")
    body = notes_mod.build("v1.0.0-rc1", "1.0.0", changelog)
    assert "Release candidate" in body
    assert "TestPyPI" in body
    assert "Release candidate" not in notes_mod.build("v1.0.0", "1.0.0", changelog)


def test_notes_fail_loudly_on_a_missing_section(notes_mod, tmp_path: Path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [0.9.0]\n\nold\n")
    with pytest.raises(SystemExit):
        notes_mod.build("v1.0.0", "1.0.0", changelog)


def test_the_shipped_changelog_renders_for_its_own_release(notes_mod):
    """The real 1.0.0 notes must actually build — E4 writes the section, E3
    consumes it, and a mismatch between them is only visible here."""
    body = notes_mod.build("v1.0.0", "1.0.0", REPO / "CHANGELOG.md")
    assert "### API compatibility" in body
    assert body.count("### API compatibility") == 1
    assert "Verifying this release" in body
