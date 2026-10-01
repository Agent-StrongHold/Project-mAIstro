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
import re
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


# --- a heading is not an entry: Unreleased content shape (#385) -----------


def test_a_categorized_linked_unreleased_entry_passes(gate, tmp_path) -> None:
    """The shape the policy asks for: category, entry, link."""
    _write(
        gate,
        tmp_path,
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- **Thing (#9).** Fixed.\n\n"
            "## [1.0.0] - TBD\n\nnotes\n"
        ),
    )

    assert gate.check() == []


def test_a_truly_empty_unreleased_section_passes_an_ordinary_run(gate, tmp_path) -> None:
    """A tree may simply not have accumulated user-visible changes yet.

    Release readiness — where emptiness is a problem — is the `--releasing`
    path's job, not every run's.
    """
    _write(gate, tmp_path)

    assert gate.check() == []


def test_a_placeholder_only_unreleased_section_fails(gate, tmp_path) -> None:
    """TODO defeats a presence check while committing nothing."""
    _write(
        gate,
        tmp_path,
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- TODO\n\n## [1.0.0] - TBD\n\nnotes\n"
        ),
    )

    problems = gate.check()

    assert any("placeholder-only" in p for p in problems)


def test_an_entry_without_a_linked_issue_fails(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- **Something.** Fixed, "
            "traceably to no issue.\n\n## [1.0.0] - TBD\n\nnotes\n"
        ),
    )

    problems = gate.check()

    assert any("links no issue or PR" in p for p in problems)


def test_a_linked_issue_on_a_wrapped_line_counts(gate, tmp_path) -> None:
    """Keep a Changelog entries wrap; the link rides anywhere in the bullet.

    The shipped CHANGELOG's entries are multi-line, so a first-line-only link
    check would reject exactly the entries that already exist.
    """
    _write(
        gate,
        tmp_path,
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n### Security\n\n- **A long title that wraps\n"
            "  onto a second line (#42).** Detail.\n\n## [1.0.0] - TBD\n\nnotes\n"
        ),
    )

    assert gate.check() == []


def test_the_explicit_no_issue_exclusion_is_accepted(gate, tmp_path) -> None:
    """Policy allows entries with no tracked issue, annotated as such."""
    _write(
        gate,
        tmp_path,
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- **Typo (no linked issue: "
            "prose fix).** One word.\n\n## [1.0.0] - TBD\n\nnotes\n"
        ),
    )

    assert gate.check() == []


def test_an_entry_outside_a_category_fails(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n- **Bare bullet (#7).** No category.\n\n"
            "## [1.0.0] - TBD\n\nnotes\n"
        ),
    )

    problems = gate.check()

    assert any("under no category" in p for p in problems)


def test_an_unrecognized_category_fails(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n### Misc\n\n- **Thing (#9).** Unclear "
            "kind of change.\n\n## [1.0.0] - TBD\n\nnotes\n"
        ),
    )

    problems = gate.check()

    assert any("under Misc" in p and "Entries belong under" in p for p in problems)


def test_the_dependencies_category_is_recognized(gate, tmp_path) -> None:
    """The explicit home for operator-visible generated churn."""
    _write(
        gate,
        tmp_path,
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n### Dependencies\n\n- **httpx 0.27 → "
            "0.28 (#60).** No source change required.\n\n## [1.0.0] - TBD\n\nnotes\n"
        ),
    )

    assert gate.check() == []


def test_content_with_no_entries_at_all_fails(gate, tmp_path) -> None:
    """Prose under Unreleased is not a categorized entry."""
    _write(
        gate,
        tmp_path,
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\nSome words about work.\n\n"
            "## [1.0.0] - TBD\n\nnotes\n"
        ),
    )

    problems = gate.check()

    assert any("no entries under a recognized category" in p for p in problems)


def test_a_placeholder_entry_among_real_ones_fails(gate, tmp_path) -> None:
    """One real entry defeats the section-level placeholder check, so the
    per-entry one is the only thing still standing between TODO and the
    release: the section is not placeholder-only, and the TODO bullet is
    still called out by itself."""
    _write(
        gate,
        tmp_path,
        changelog=(
            "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n"
            "- **A real fix (#10).** Real words.\n\n- TODO\n\n## [1.0.0] - TBD\n\nnotes\n"
        ),
    )

    problems = gate.check()

    assert any("is a placeholder, not an entry" in p for p in problems)
    assert not any("placeholder-only" in p for p in problems)


# --- entry folding: where one bullet ends and the next begins --------------


def test_adjacent_entry_bullets_are_separate_entries(gate) -> None:
    """A second bullet must flush the first, not absorb into it."""
    body = "### Fixed\n\n- **One (#1).** Words.\n- **Two (#2).** Words.\n"

    entries = gate._entries(body)

    assert [entry[2] for entry in entries] == [
        "- **One (#1).** Words.",
        "- **Two (#2).** Words.",
    ]
    assert [entry[1] for entry in entries] == ["Fixed", "Fixed"]


def test_unindented_prose_terminates_the_entry_above_it(gate) -> None:
    """Indented continuation lines fold into the bullet; the same words
    flush-left are section prose and must not ride along as part of the
    entry's claim."""
    body = "### Fixed\n\n- **One (#1).** Words.\nTerminating prose.\n- **Two (#2).** More.\n"

    entries = gate._entries(body)

    assert len(entries) == 2
    assert entries[0][2] == "- **One (#1).** Words."
    assert entries[1][2] == "- **Two (#2).** More."


def test_section_body_is_none_when_the_heading_is_absent(gate) -> None:
    """Callers distinguish 'empty section' from 'no section at all'; the
    heading-missing half of that contract lives here, not in the callers."""
    text = "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - TBD\n\nnotes\n"

    assert gate.section_body(text, re.compile(r"^##\s*\[2\.0\.0\]", re.M)) is None
    assert gate.section_body(text, gate._UNRELEASED_RE) is not None


def test_releasing_against_an_empty_target_section_fails(gate, tmp_path) -> None:
    """Release readiness: publish emptiness is not an option.

    `release_notes.py` publishes exactly the curated section, so a tag cut
    against an empty one publishes empty notes — while passing every other
    consistency check, which is the state #385 exists to reject.
    """
    _write(
        gate,
        tmp_path,
        version="1.0.0",
        changelog="# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - TBD\n",
        readme=f"{gate.README_BEGIN}\n{_status(current='1.0.0')}\n{gate.README_END}",
        tags=["v1.0.0"],
    )

    problems = gate.check(releasing="v1.0.0")

    assert any("is empty" in p and "v1.0.0" in p for p in problems)


def test_releasing_against_a_placeholder_target_section_fails(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        version="1.0.0",
        changelog=("# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - TBD\n\nTBD\n"),
        readme=f"{gate.README_BEGIN}\n{_status(current='1.0.0')}\n{gate.README_END}",
        tags=["v1.0.0"],
    )

    problems = gate.check(releasing="v1.0.0")

    assert any("placeholder-only" in p for p in problems)


def test_releasing_an_rc_checks_the_base_version_section(gate, tmp_path) -> None:
    """A candidate publishes the notes of the release it is a candidate for."""
    _write(
        gate,
        tmp_path,
        version="1.0.0",
        changelog=("# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - TBD\n\n- Real curated notes.\n"),
        readme=f"{gate.README_BEGIN}\n{_status(current='1.0.0')}\n{gate.README_END}",
        tags=["v1.0.0-rc1"],
    )

    problems = gate.check(releasing="v1.0.0-rc1")

    assert problems == []


def test_releasing_against_a_curated_target_section_passes(gate, tmp_path) -> None:
    _write(
        gate,
        tmp_path,
        version="1.0.0",
        changelog=("# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - TBD\n\nCurated notes.\n"),
        readme=f"{gate.README_BEGIN}\n{_status(current='1.0.0')}\n{gate.README_END}",
        tags=["v1.0.0"],
    )

    assert gate.check(releasing="v1.0.0") == []


def test_a_non_release_tag_releasing_argument_defers_to_release_guard(gate, tmp_path) -> None:
    """Tag-shape errors are release_guard's to report; staying quiet here is
    the division of labour, not a hole — two gates saying the same thing is
    how one of them stops being read."""
    _write(gate, tmp_path)

    assert gate.check(releasing="not-a-release-tag") == []


def test_releasing_a_version_with_no_heading_defers_to_release_guard(gate, tmp_path) -> None:
    """The heading's existence is release_guard's check too — a missing
    section is not silently treated as releasable here, and not double-
    reported."""
    _write(gate, tmp_path)

    assert gate.check(releasing="v2.0.0") == []


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
            "# Changelog\n\n## [Unreleased]\n\n## [1.1.0] - TBD\n\n## [1.0.0] - "
            "2026-08-23\n\nCurated release notes.\n"
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
