"""Re-running get.sh with another channel switches the existing checkout (#411).

Every one-liner install is a single-branch shallow clone (`git clone --depth 1
--branch <ref>`), whose `remote.origin.fetch` maps only that one branch. A
bare `git fetch --depth 1 origin develop` on such a clone lands in FETCH_HEAD
alone — refs/remotes/origin/develop is never created — so the `checkout -B
develop origin/develop` after it died with "'origin/develop' is not a commit"
and every channel change was impossible until the directory was deleted by
hand.

The fix fetches the requested ref by explicit refspec before switching,
refuses the switch while tracked source files carry uncommitted changes (the
tag path used to run `checkout --force` and discard them), and rolls the
checkout back to its previous position when a switch fails.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GET_SH = ROOT / "get.sh"


def _library() -> str:
    """get.sh as a sourceable library: everything but its entrypoint."""
    source = GET_SH.read_text(encoding="utf-8")
    entrypoint = 'main "$@"'
    assert source.rstrip().endswith(entrypoint)
    return source[: source.rfind(entrypoint)]


def _bash(script: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash"],
        input=_library() + "\n" + script,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
        # No controlling terminal, like every non-interactive run of the
        # one-liner (CI, cloud-init, ssh without -t).
        start_new_session=True,
    )


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit_all(origin: Path, message: str) -> None:
    _git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=origin)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", message, cwd=origin)


def _origin(tmp_path: Path) -> Path:
    """main, develop, and a tag: enough release geometry for channel changes.

    The tag sits an older commit than main's tip, so moving to it is a real
    content change — a tag "switch" that changes nothing could not tell the
    refusal path from a no-op.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    _git("init", "-q", "-b", "main", cwd=origin)
    _git(
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "init",
        cwd=origin,
    )
    (origin / "install.sh").write_text("#!/usr/bin/env bash\necho main\n", encoding="utf-8")
    _commit_all(origin, "installer")
    _git("tag", "v1.0.0", cwd=origin)
    (origin / "post-release.txt").write_text("newer than the tag\n", encoding="utf-8")
    _commit_all(origin, "post-release work")
    _git("checkout", "-q", "-b", "develop", cwd=origin)
    (origin / "develop-feature.txt").write_text("from develop\n", encoding="utf-8")
    # develop must genuinely lack a file main has, so an update to develop can
    # prove stale files do not linger.
    (origin / "post-release.txt").unlink()
    _commit_all(origin, "develop work")
    _git("checkout", "-q", "main", cwd=origin)
    return origin


def _install(origin: Path, tmp_path: Path, ref: str = "main") -> Path:
    """A checkout laid down the way get.sh does it: single-branch and shallow."""
    install_dir = tmp_path / "maistro-engine"
    update = (
        f'INSTALL_DIR="{install_dir}"; REPO_URL="file://{origin}"; '
        f'REF_KIND=branch; REF="{ref}"; download_with_git'
    )
    result = _bash(update)
    assert result.returncode == 0, result.stderr
    return install_dir


def _update(
    install_dir: Path, origin: Path, kind: str, ref: str
) -> subprocess.CompletedProcess[str]:
    return _bash(
        f'INSTALL_DIR="{install_dir}"; REPO_URL="file://{origin}"; '
        f'REF_KIND={kind}; REF="{ref}"; download_with_git'
    )


def _head_ref(install_dir: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(install_dir), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _is_shallow(install_dir: Path) -> bool:
    return (install_dir / ".git" / "shallow").is_file()


# --- channel changes on a single-branch clone --------------------------------


def test_a_single_branch_clone_can_switch_to_another_branch(tmp_path: Path) -> None:
    """The defect itself: stable (main fallback) -> dev (develop).

    The old `git fetch --depth 1 origin develop` created no remote-tracking
    ref on a single-branch clone, so the checkout died with "'origin/develop'
    is not a commit". The file develop carries must actually appear, proving
    the working tree moved, not just HEAD.
    """
    origin = _origin(tmp_path)
    install_dir = _install(origin, tmp_path)

    result = _update(install_dir, origin, "branch", "develop")

    assert result.returncode == 0, result.stderr
    assert _head_ref(install_dir) == "develop"
    assert (install_dir / "develop-feature.txt").is_file()


def test_switching_back_and_re_running_is_idempotent(tmp_path: Path) -> None:
    """develop -> main -> main -> main: re-running with a supported channel
    neither wedges nor degrades (#411 definition of done)."""
    origin = _origin(tmp_path)
    install_dir = _install(origin, tmp_path, ref="develop")

    assert _update(install_dir, origin, "branch", "main").returncode == 0
    assert _head_ref(install_dir) == "main"
    assert _update(install_dir, origin, "branch", "main").returncode == 0
    assert _update(install_dir, origin, "branch", "main").returncode == 0
    assert _head_ref(install_dir) == "main"


def test_a_branch_can_switch_to_a_tag_and_back(tmp_path: Path) -> None:
    """Tag installs pin images to the release; switching to one must detach at
    the tag and a later channel change must still find its way out."""
    origin = _origin(tmp_path)
    install_dir = _install(origin, tmp_path)

    to_tag = _update(install_dir, origin, "tag", "v1.0.0")
    assert to_tag.returncode == 0, to_tag.stderr
    assert _head_ref(install_dir) == "HEAD", "a tag install should be detached"
    assert not (install_dir / "post-release.txt").exists(), "the tree did not move to the tag"

    back = _update(install_dir, origin, "branch", "main")
    assert back.returncode == 0, back.stderr
    assert _head_ref(install_dir) == "main"
    assert (install_dir / "post-release.txt").is_file()


def test_a_tag_pinned_clone_can_switch_to_a_branch(tmp_path: Path) -> None:
    """`clone --depth 1 --branch v1.0.0` pins remote.origin.fetch to the tag,
    the tightest single-branch refspec there is — and switching still works."""
    origin = _origin(tmp_path)
    install_dir = _install(origin, tmp_path)

    result = _update(install_dir, origin, "branch", "main")

    assert result.returncode == 0, result.stderr
    assert _head_ref(install_dir) == "main"


def test_a_shallow_clone_stays_shallow_across_a_channel_switch(tmp_path: Path) -> None:
    """file:// clones honor --depth, so this exercises real shallow semantics,
    not the ignore-locally shortcut of path clones."""
    origin = _origin(tmp_path)
    install_dir = _install(origin, tmp_path)
    assert _is_shallow(install_dir)

    assert _update(install_dir, origin, "branch", "develop").returncode == 0

    assert _is_shallow(install_dir), "the switch deepened the clone"


# --- failure modes leave the previous checkout in place -----------------------


def test_a_missing_ref_leaves_the_previous_checkout_in_place(tmp_path: Path) -> None:
    origin = _origin(tmp_path)
    install_dir = _install(origin, tmp_path)

    result = _update(install_dir, origin, "branch", "ghost-branch")

    assert result.returncode != 0
    assert "Could not fetch ghost-branch" in result.stderr
    assert _head_ref(install_dir) == "main"
    branches = subprocess.run(
        ["git", "-C", str(install_dir), "for-each-ref", "refs/heads/"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "ghost-branch" not in branches, "the failed switch left a local branch behind"


def test_an_unreachable_remote_leaves_the_previous_checkout_in_place(tmp_path: Path) -> None:
    """Offline mode: the fetch cannot reach origin, the error says so, and the
    checkout is exactly where the user left it."""
    origin = _origin(tmp_path)
    install_dir = _install(origin, tmp_path)
    hidden = tmp_path / "origin.hidden"
    origin.rename(hidden)

    result = _update(install_dir, origin, "branch", "develop")

    assert result.returncode != 0
    assert "Could not fetch develop" in result.stderr
    assert _head_ref(install_dir) == "main"
    hidden.rename(origin)


def test_a_failed_switch_rolls_back_to_the_previous_checkout(tmp_path: Path) -> None:
    """A switch that dies part-way (here: an untracked file the target branch
    also tracks) must restore the previous position, not wedge the tree.

    The rollback exists for states git only reaches after the fetch has
    succeeded, so it is driven from exactly that state: the fetch lands, the
    checkout refuses, and restore_previous_checkout has to put HEAD back.
    """
    origin = _origin(tmp_path)
    install_dir = _install(origin, tmp_path, ref="develop")
    collision = install_dir / "collision.txt"
    collision.write_text("user-data\n", encoding="utf-8")
    _git("checkout", "-q", "main", cwd=origin)
    (origin / "collision.txt").write_text("from main\n", encoding="utf-8")
    _commit_all(origin, "collide")
    _git("checkout", "-q", "develop", cwd=origin)

    result = _update(install_dir, origin, "branch", "main")

    assert result.returncode != 0
    assert _head_ref(install_dir) == "develop", "the failed switch did not roll back"
    assert collision.read_text() == "user-data\n", "the user's file was clobbered"
    assert (install_dir / "develop-feature.txt").is_file(), "the tree is half-switched"


# --- local changes are preserved, never silently discarded --------------------


def test_a_channel_change_is_refused_while_the_source_is_dirty(tmp_path: Path) -> None:
    origin = _origin(tmp_path)
    install_dir = _install(origin, tmp_path)
    tracked = install_dir / "install.sh"
    tracked.write_text("#!/usr/bin/env bash\necho my local patch\n", encoding="utf-8")

    result = _update(install_dir, origin, "branch", "develop")

    assert result.returncode != 0
    assert "uncommitted changes" in result.stderr
    assert _head_ref(install_dir) == "main"
    assert "my local patch" in tracked.read_text(), "the refusal ate the user's edit"
    # Untracked files are the user's regardless of dirtiness; they survive.
    (install_dir / "notes.txt").write_text("mine\n", encoding="utf-8")
    assert (install_dir / "notes.txt").is_file()


def test_a_dirty_switch_to_a_tag_is_no_longer_silently_discarded(tmp_path: Path) -> None:
    """Regression: the tag path ran `checkout --force` unconditionally, so
    re-running against a different tag threw away uncommitted source edits
    without a word."""
    origin = _origin(tmp_path)
    install_dir = _install(origin, tmp_path)
    tracked = install_dir / "install.sh"
    tracked.write_text("#!/usr/bin/env bash\necho my local patch\n", encoding="utf-8")

    result = _update(install_dir, origin, "tag", "v1.0.0")

    assert result.returncode != 0
    assert "uncommitted changes" in result.stderr
    assert _head_ref(install_dir) == "main"
    assert "my local patch" in tracked.read_text()


def test_a_same_branch_update_still_works_with_local_edits(tmp_path: Path) -> None:
    """Only *channel changes* demand a clean tree. Re-running an update on the
    branch already installed keeps git's own protection: edits git would not
    overwrite stay put and the branch pointer advances."""
    origin = _origin(tmp_path)
    install_dir = _install(origin, tmp_path)
    tracked = install_dir / "install.sh"
    tracked.write_text("#!/usr/bin/env bash\necho my local patch\n", encoding="utf-8")
    (origin / "unrelated.txt").write_text("new upstream file\n", encoding="utf-8")
    _commit_all(origin, "advance main")

    result = _update(install_dir, origin, "branch", "main")

    assert result.returncode == 0, result.stderr
    assert (install_dir / "unrelated.txt").is_file(), "the update did not land"
    assert "my local patch" in tracked.read_text(), "the edit did not survive"


# --- archive installs: channel switches are explicit --------------------------


@pytest.mark.skipif(shutil.which("curl") is None, reason="curl is not installed")
def test_an_archive_install_switches_channels_and_keeps_the_env(tmp_path: Path) -> None:
    """Archive installs have no git to switch with: a channel change re-lays
    the tree from the new ref's tarball. It keeps .env, and it says it is
    switching instead of pretending to be a routine update."""
    origin = _origin(tmp_path)
    main_tarball = tmp_path / "main.tar.gz"
    develop_tarball = tmp_path / "develop.tar.gz"
    subprocess.run(
        ["git", "archive", "--format=tar.gz", "--prefix=maistro/", "-o", str(main_tarball), "main"],
        cwd=origin,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "archive",
            "--format=tar.gz",
            "--prefix=maistro/",
            "-o",
            str(develop_tarball),
            "develop",
        ],
        cwd=origin,
        check=True,
        capture_output=True,
    )
    install_dir = tmp_path / "maistro-engine"

    first = _bash(
        f'INSTALL_DIR="{install_dir}"; ARCHIVE_URL="file://{main_tarball}"; '
        'REF="main"; download_with_archive'
    )
    assert first.returncode == 0, first.stderr
    marker = install_dir / ".maistro-archive-install"
    assert marker.read_text() == "main\n"

    env_file = install_dir / ".env"
    env_file.write_text("LITELLM_MASTER_KEY=keep-me\n", encoding="utf-8")
    second = _bash(
        f'INSTALL_DIR="{install_dir}"; ARCHIVE_URL="file://{develop_tarball}"; '
        'REF="develop"; download_with_archive'
    )
    assert second.returncode == 0, second.stderr
    assert "Switching archive install from main to develop" in second.stdout
    assert (install_dir / "develop-feature.txt").is_file(), "the tree did not move to develop"
    assert not (install_dir / "post-release.txt").exists(), "stale main files linger"
    assert "keep-me" in env_file.read_text(), "the .env did not survive the switch"
    assert marker.read_text() == "develop\n", "the marker did not record the new channel"
