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
import re
import subprocess
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
    # ADR §2 (as amended for ADR-095): an rc may point at develop, the
    # canonical integration branch, so it can soak.
    assert out["target_branch"] == "develop"


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


# --- rc -> final source-tree promotion (#89) -------------------------------


@pytest.fixture
def promotion_tree(release_tree):
    """Real git objects, not mocked tree hashes or a production checkout."""
    root = release_tree.parent

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(root), *args], text=True, stderr=subprocess.STDOUT
        ).strip()

    git("init", "-q")
    git("config", "user.name", "Release test")
    git("config", "user.email", "release@example.invalid")
    (root / "runtime.py").write_text("print('candidate')\n")
    git("add", ".")
    git("commit", "-qm", "candidate")
    return root, git


def test_final_cli_accepts_identical_rc_tree_on_a_different_commit(promotion_tree, guard_mod):
    root, git = promotion_tree
    git("tag", "-a", "v1.0.0-rc1", "-m", "candidate")
    git("commit", "--allow-empty", "-qm", "promotion merge marker")
    git("tag", "-a", "v1.0.0", "-m", "final")
    output = root / "github-output"
    assert (
        guard_mod.main(["--tag", "v1.0.0", "--verify-rc-tree", "--github-output", str(output)]) == 0
    )
    assert "prerelease=false\n" in output.read_text()


def test_final_cli_requires_a_same_version_rc(promotion_tree, guard_mod, capsys):
    root, git = promotion_tree
    git("tag", "-a", "v0.9.0-rc1", "-m", "unrelated candidate")
    git("tag", "-a", "v1.0.0", "-m", "final")
    output = root / "github-output"
    assert (
        guard_mod.main(["--tag", "v1.0.0", "--verify-rc-tree", "--github-output", str(output)]) == 1
    )
    assert "no release candidate" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize("change", ["runtime", "configuration", "executable-bit"])
def test_final_cli_rejects_changes_after_the_rc(promotion_tree, guard_mod, capsys, change):
    root, git = promotion_tree
    git("tag", "-a", "v1.0.0-rc1", "-m", "candidate")
    if change == "runtime":
        (root / "runtime.py").write_text("print('unsoaked')\n")
        git("add", "runtime.py")
    elif change == "configuration":
        (root / "runtime.env").write_text("WORKERS=8\n")
        git("add", "runtime.env")
    else:
        git("update-index", "--chmod=+x", "runtime.py")
    git("commit", "-qm", "unsoaked change")
    git("tag", "-a", "v1.0.0", "-m", "final")
    assert guard_mod.main(["--tag", "v1.0.0", "--verify-rc-tree"]) == 1
    assert "differs from latest candidate v1.0.0-rc1" in capsys.readouterr().err


def test_final_cli_cannot_select_an_older_matching_rc(promotion_tree, guard_mod, capsys):
    root, git = promotion_tree
    git("tag", "-a", "v1.0.0-rc2", "-m", "older candidate")
    git("tag", "-a", "v1.0.0", "-m", "older matching final")
    (root / "runtime.py").write_text("print('latest candidate')\n")
    git("add", "runtime.py")
    git("commit", "-qm", "latest candidate")
    git("tag", "-a", "v1.0.0-rc10", "-m", "latest candidate")
    # Check out the final without moving/deleting any immutable tags.
    git("switch", "--detach", "v1.0.0")
    assert guard_mod.main(["--tag", "v1.0.0", "--verify-rc-tree"]) == 1
    assert "differs from latest candidate v1.0.0-rc10" in capsys.readouterr().err


def test_final_cli_rejects_a_lightweight_candidate(promotion_tree, guard_mod, capsys):
    _, git = promotion_tree
    git("tag", "v1.0.0-rc1")
    git("tag", "-a", "v1.0.0", "-m", "final")
    assert guard_mod.main(["--tag", "v1.0.0", "--verify-rc-tree"]) == 1
    assert "must be annotated" in capsys.readouterr().err


def test_final_cli_fails_closed_on_missing_tag(promotion_tree, guard_mod, capsys):
    _, git = promotion_tree
    git("tag", "-a", "v1.0.0-rc1", "-m", "candidate")
    assert guard_mod.main(["--tag", "v1.0.0", "--verify-rc-tree"]) == 1
    assert "cannot verify RC promotion" in capsys.readouterr().err


def test_final_cli_rejects_a_checkout_other_than_the_final_tree(promotion_tree, guard_mod, capsys):
    root, git = promotion_tree
    git("tag", "-a", "v1.0.0-rc1", "-m", "candidate")
    git("tag", "-a", "v1.0.0", "-m", "final")
    (root / "runtime.py").write_text("print('wrong checkout')\n")
    git("add", "runtime.py")
    git("commit", "-qm", "wrong checkout")
    assert guard_mod.main(["--tag", "v1.0.0", "--verify-rc-tree"]) == 1
    assert "checkout differs from final tag" in capsys.readouterr().err


def test_rc_cli_needs_no_previous_candidate(release_tree, guard_mod):
    # The first RC must build; this fixture is deliberately not a git repo.
    assert guard_mod.main(["--tag", "v1.0.0-rc1", "--verify-rc-tree"]) == 0


def test_shipping_workflow_enforces_rc_tree_in_its_existing_guard():
    import yaml

    workflow = yaml.safe_load((REPO / ".github/workflows/release.yml").read_text())
    job = workflow["jobs"]["guard"]
    guard_step = next(step for step in job["steps"] if step.get("id") == "guard")
    assert "--verify-rc-tree" in guard_step["run"]
    assert not guard_step.get("continue-on-error", False)
    checkout = next(step for step in job["steps"] if "actions/checkout@" in step.get("uses", ""))
    assert checkout["with"]["fetch-depth"] == 0
    assert "guard" in workflow["jobs"]["wheels"]["needs"]
    assert "guard" in workflow["jobs"]["images"]["needs"]


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


def test_notes_verify_artifacts_against_the_canonical_repository(notes_mod, tmp_path: Path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [1.0.0]\n\nbody\n")

    body = notes_mod.build("v1.0.0", "1.0.0", changelog)

    canonical = "https://github.com/Agent-StrongHold/Project-mAIstro"
    assert f"{canonical}/blob/v1.0.0/docs/adr/ADR-073126-c4e1" in body
    assert f"^{canonical}/\\.github/workflows/release\\.yml@refs/tags/v1\\.0\\.0$" in body
    assert "https://github.com/Agent-StrongHold/maistro-engine" not in body


def test_the_shipped_changelog_renders_for_its_own_release(notes_mod):
    """The real 1.0.0 notes must actually build — E4 writes the section, E3
    consumes it, and a mismatch between them is only visible here."""
    body = notes_mod.build("v1.0.0", "1.0.0", REPO / "CHANGELOG.md")
    assert "### API compatibility" in body
    assert body.count("### API compatibility") == 1
    assert "Verifying this release" in body


def test_notes_name_every_package_the_release_publishes(notes_mod):
    """The verification block must describe the artifact set release.yml
    actually attaches. PUBLISH_SET in the workflow is the source of truth;
    the notes hard-code the names beside it, so the two can drift — and a
    consumer told the checksums cover five packages while the release ships
    six has been misinstructed on exactly the step that catches tampering."""
    workflow = (REPO / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    publish_set = re.search(r"^\s*PUBLISH_SET:\s*\"([^\"]+)\"", workflow, re.MULTILINE)
    assert publish_set, "PUBLISH_SET line not found in release.yml"
    packages = publish_set.group(1).split()
    assert len(packages) >= 6, f"unexpectedly small publish set: {packages}"
    block = notes_mod._verification_block("v1.0.0")
    for package in packages:
        assert f"`{package}`" in block, (
            f"release notes omit published package {package!r} from the artifact description"
        )
