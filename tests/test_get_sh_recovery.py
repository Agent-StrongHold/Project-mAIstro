"""The one-liner recovers from its own failures instead of wedging on them.

Two defects, both found by running `get.sh` on a Mac rather than reading it.

**An unfinished install was unrecoverable.** An earlier get.sh migrated the
user's `.env` into `$INSTALL_DIR` *before* cloning. When the clone then failed,
the directory existed but was not a checkout, so every later run stopped at
"exists but is not a git checkout" -- permanently, until someone found the
directory and moved it aside by hand. The ordering bug was fixed; the wreckage
it left on users' machines was not. One such directory was sitting on the
machine these tests were written on.

**The one-liner died without a terminal.** get.sh handed install.sh the user's
terminal behind `[[ -r /dev/tty ]]`. That node exists and is world-readable on
every macOS and Linux host, so the test was true even with no controlling
terminal -- and the redirect then failed with "Device not configured", under
`exec`, taking the install down. That is every non-interactive run: cloud-init,
`ssh host 'curl ... | bash'` without -t, CI, launchd. Gate C never saw it
because it runs install.sh directly, skipping get.sh's hand-off entirely.
"""

from __future__ import annotations

import os
import stat
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
        # A new session has no controlling terminal: the state cloud-init,
        # non-interactive ssh and CI all run the one-liner in.
        start_new_session=True,
    )


def _origin(tmp_path: Path) -> Path:
    """A local repository to clone from, so no test touches the network."""
    origin = tmp_path / "origin"
    origin.mkdir()
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
    ):
        subprocess.run(cmd, cwd=origin, check=True, capture_output=True)
    (origin / "install.sh").write_text("#!/usr/bin/env bash\necho installed\n", encoding="utf-8")
    subprocess.run(["git", "add", "install.sh"], cwd=origin, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "installer"],
        cwd=origin,
        check=True,
    )
    return origin


def _unfinished(tmp_path: Path, *extra: str) -> Path:
    install_dir = tmp_path / "maistro-engine"
    install_dir.mkdir()
    env_file = install_dir / ".env"
    env_file.write_text("LITELLM_MASTER_KEY=keep-me\nLITELLM_URL=https://gw.example\n")
    env_file.chmod(0o600)
    for name in extra:
        (install_dir / name).write_text("")
    return install_dir


# --- which directories count as an unfinished install -----------------------


@pytest.mark.parametrize(
    "extra, expected",
    [
        ((), True),
        ((".DS_Store",), True),
        (("notes.txt",), False),
        ((".env", "data.db"), False),
    ],
)
def test_only_installer_leftovers_count_as_unfinished(
    tmp_path: Path, extra: tuple[str, ...], expected: bool
) -> None:
    """Anything beyond a .env and Finder litter might be the user's, so it is
    never adopted -- the guard's refusal stays exactly as it was for those."""
    install_dir = _unfinished(tmp_path, *[e for e in extra if e != ".env"])
    result = _bash(f'is_unfinished_install "{install_dir}" && echo yes || echo no')

    assert result.stdout.strip() == ("yes" if expected else "no"), result.stderr


def test_a_directory_without_a_dotenv_is_not_adopted(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    result = _bash(f'is_unfinished_install "{tmp_path / "empty"}" && echo yes || echo no')

    assert result.stdout.strip() == "no"


def test_a_real_checkout_is_not_mistaken_for_an_unfinished_install(tmp_path: Path) -> None:
    install_dir = _unfinished(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=install_dir, check=True)
    result = _bash(f'is_unfinished_install "{install_dir}" && echo yes || echo no')

    assert result.stdout.strip() == "no"


# --- adopting one -----------------------------------------------------------


def test_an_unfinished_install_is_recovered_with_its_env_intact(tmp_path: Path) -> None:
    origin = _origin(tmp_path)
    install_dir = _unfinished(tmp_path, ".DS_Store")

    result = _bash(f'INSTALL_DIR="{install_dir}"; REPO_URL="{origin}"; REF=main; download_with_git')

    assert result.returncode == 0, result.stderr
    assert (install_dir / ".git").is_dir(), "no checkout was laid down"
    assert (install_dir / "install.sh").is_file()
    env_file = install_dir / ".env"
    assert "LITELLM_MASTER_KEY=keep-me" in env_file.read_text()
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600, "the .env lost its 0600 mode"
    assert not (install_dir / ".DS_Store").exists()
    assert not list(tmp_path.glob("maistro-engine.clone.*")), "staging directory left behind"


def test_a_failed_clone_leaves_the_unfinished_install_untouched(tmp_path: Path) -> None:
    """Nothing is removed until the clone has succeeded."""
    install_dir = _unfinished(tmp_path)

    result = _bash(
        f'INSTALL_DIR="{install_dir}"; REPO_URL="{tmp_path / "no-such-repo"}"; REF=main; download_with_git'
    )

    assert result.returncode != 0
    assert "untouched" in result.stderr
    assert sorted(p.name for p in install_dir.iterdir()) == [".env"]
    assert "keep-me" in (install_dir / ".env").read_text()
    assert not list(tmp_path.glob("maistro-engine.clone.*"))


def test_a_directory_with_user_content_is_still_refused(tmp_path: Path) -> None:
    origin = _origin(tmp_path)
    install_dir = _unfinished(tmp_path, "my-notes.md")

    result = _bash(f'INSTALL_DIR="{install_dir}"; REPO_URL="{origin}"; REF=main; download_with_git')

    assert result.returncode != 0
    assert "exists but is not a git checkout" in result.stderr
    assert (install_dir / "my-notes.md").exists()


# --- handing off to install.sh without a terminal ---------------------------


def test_the_hand_off_to_install_sh_survives_having_no_terminal(tmp_path: Path) -> None:
    """The cloud-init / non-interactive-ssh case.

    Runs in a new session, so there is no controlling terminal, with stdin
    from /dev/null: what `curl ... | bash` looks like to a script launched by
    cloud-init. The old `[[ -r /dev/tty ]]` probe passed here and the redirect
    then failed with "Device not configured".
    """
    install_dir = tmp_path / "checkout"
    install_dir.mkdir()
    (install_dir / "install.sh").write_text('#!/usr/bin/env bash\necho "install.sh ran: $*"\n')

    result = subprocess.run(
        ["bash"],
        input=_library()
        + f'\nINSTALL_DIR="{install_dir}"; IMAGE_TAG=latest\n'
        + "verify_installer_checksum() { :; }\n"
        + "run_installer --no-start\n",
        capture_output=True,
        text=True,
        check=False,
        start_new_session=True,
    )

    assert "Device not configured" not in result.stderr
    assert "No such device" not in result.stderr
    assert "install.sh ran: --no-start" in result.stdout, result.stderr
