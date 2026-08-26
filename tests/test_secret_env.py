"""Credentials are never reachable through the file's mode (#357).

The installer wrote every secret into `.env` with `cat >` — creating it under
the caller's umask, 0644 on a typical system — and narrowed it with `chmod 600`
afterwards. Measured on this machine under `umask 0022`:

    cat > old.env <<EOF        ->  644, with the token already in it
    chmod 600 old.env          ->  600

Between those two lines the credentials are world-readable. A crash there leaves
them that way permanently, and `TestTheModeIsNeverWide` is the half of this file
that pins the fix: not "it ends up 0600", which the old code also managed, but
that **no observer ever sees anything wider**.
"""

from __future__ import annotations

import importlib.util
import io
import os
import stat
import subprocess
import sys
import threading
from contextlib import suppress
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "secret_env.py"

TOKEN = "MAISTRO_ACCESS_TOKEN=s3cr3t-do-not-leak\n"


@pytest.fixture(scope="module")
def secret_env():
    spec = importlib.util.spec_from_file_location("_secret_env", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def env_path(tmp_path: Path) -> Path:
    return tmp_path / ".env"


@pytest.fixture
def permissive_umask():
    """The worst realistic case. A 0600 result under umask 0000 can only come
    from an explicit mode, never from inheriting the caller's."""
    previous = os.umask(0o000)
    yield
    os.umask(previous)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


class TestTheModeIsNeverWide:
    def test_a_new_file_is_created_at_0600(self, secret_env, env_path) -> None:
        secret_env.create_exclusive(env_path, TOKEN)
        assert _mode(env_path) == 0o600

    def test_even_under_a_fully_permissive_umask(
        self, secret_env, env_path, permissive_umask
    ) -> None:
        """`umask 0000` is what makes this a real assertion: the old `cat >`
        would produce 0666 here."""
        secret_env.create_exclusive(env_path, TOKEN)
        assert _mode(env_path) == 0o600

    def test_an_update_lands_at_0600_too(self, secret_env, env_path, permissive_umask) -> None:
        """`os.replace` swaps in the temp file's inode, so the temp file's mode
        is the one that survives — not the target's."""
        secret_env.create_exclusive(env_path, "A=1\n")
        secret_env.atomic_write(env_path, TOKEN)
        assert _mode(env_path) == 0o600

    def test_no_observer_ever_sees_a_wider_mode(
        self, secret_env, env_path, permissive_umask
    ) -> None:
        """The actual claim. A watcher samples the path throughout a series of
        writes; every mode it manages to observe must already be 0600.

        The old code fails this even though its *final* mode is right, which is
        why "ends up 0600" was never the property worth asserting.
        """
        observed: list[int] = []
        stop = threading.Event()

        def watch() -> None:
            while not stop.is_set():
                with suppress(FileNotFoundError):
                    observed.append(_mode(env_path))

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            secret_env.create_exclusive(env_path, TOKEN)
            for index in range(40):
                secret_env.set_key(env_path, f"K{index}", "v")
        finally:
            stop.set()
            watcher.join(timeout=5)

        assert observed, "the watcher never sampled the file; the test proves nothing"
        wide = {mode for mode in observed if mode & (stat.S_IRWXG | stat.S_IRWXO)}
        assert not wide, f"observed group/other-readable modes: {[oct(m) for m in sorted(wide)]}"

    def test_the_temp_file_is_never_wide_either(
        self, secret_env, env_path, permissive_umask
    ) -> None:
        """The temp file holds the same secrets for as long as it exists. A
        `mkstemp` default of 0600 is what this depends on, so it is asserted
        rather than assumed."""
        secret_env.create_exclusive(env_path, TOKEN)
        seen: list[int] = []
        stop = threading.Event()

        def watch() -> None:
            while not stop.is_set():
                for candidate in env_path.parent.glob(".env.*.tmp"):
                    with suppress(FileNotFoundError):
                        seen.append(_mode(candidate))

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            for index in range(60):
                secret_env.set_key(env_path, f"K{index}", "v")
        finally:
            stop.set()
            watcher.join(timeout=5)

        assert not [mode for mode in seen if mode & (stat.S_IRWXG | stat.S_IRWXO)]


class TestInterruption:
    """ "Crash or concurrent reader in that window" is the issue's own wording.
    These interrupt at each of the three points and assert what survives.
    """

    def test_an_interrupt_before_the_write_leaves_no_file(
        self, secret_env, env_path, monkeypatch
    ) -> None:
        """Interrupted at the open() itself: nothing is created, so there is no
        empty-but-present `.env` for a later run to mistake for a real one."""

        def die(*_args, **_kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(secret_env.os, "open", die)
        with pytest.raises(KeyboardInterrupt):
            secret_env.create_exclusive(env_path, TOKEN)
        assert not env_path.exists()

    def test_an_interrupt_during_an_update_keeps_the_old_file_whole(
        self, secret_env, env_path, monkeypatch
    ) -> None:
        """The reason updates go through a temp file at all. Truncating in
        place would leave a half-written `.env` missing whichever keys came
        after the interrupt — and the stack would then start with a partial
        configuration rather than fail."""
        secret_env.create_exclusive(env_path, "KEEP=me\nALSO=me\n")
        original = env_path.read_text(encoding="utf-8")

        def die(*_args, **_kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(secret_env.os, "replace", die)
        with pytest.raises(KeyboardInterrupt):
            secret_env.atomic_write(env_path, TOKEN)

        assert env_path.read_text(encoding="utf-8") == original
        assert _mode(env_path) == 0o600

    def test_an_interrupted_update_leaves_no_temp_file_behind(
        self, secret_env, env_path, monkeypatch
    ) -> None:
        """A leftover temp file is a second copy of every secret, sitting in a
        directory the user believes holds one."""
        secret_env.create_exclusive(env_path, "KEEP=me\n")

        def die(*_args, **_kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(secret_env.os, "replace", die)
        with pytest.raises(KeyboardInterrupt):
            secret_env.atomic_write(env_path, TOKEN)

        assert list(env_path.parent.glob(".env.*.tmp")) == []

    def test_an_interrupt_after_the_write_leaves_a_complete_file(
        self, secret_env, env_path
    ) -> None:
        secret_env.create_exclusive(env_path, TOKEN)
        assert env_path.read_text(encoding="utf-8") == TOKEN
        assert _mode(env_path) == 0o600


class TestItRefusesRatherThanRepairs:
    """Each of these means something else holds the path. `chmod` would narrow
    the mode without taking that handle away, so narrowing would be a repair
    that hides the cause.
    """

    def test_a_symlink_is_refused(self, secret_env, tmp_path) -> None:
        target = tmp_path / "elsewhere"
        target.write_text("", encoding="utf-8")
        link = tmp_path / ".env"
        link.symlink_to(target)
        with pytest.raises(secret_env.UnsafeEnvFile, match="symlink"):
            secret_env.validate_target(link)

    def test_the_symlink_target_is_not_written(self, secret_env, tmp_path) -> None:
        """The consequence, not just the check: credentials must not land
        wherever the link points."""
        target = tmp_path / "elsewhere"
        target.write_text("original\n", encoding="utf-8")
        link = tmp_path / ".env"
        link.symlink_to(target)
        with pytest.raises(secret_env.UnsafeEnvFile):
            secret_env.write(link, TOKEN)
        assert target.read_text(encoding="utf-8") == "original\n"

    def test_an_extra_hard_link_is_refused(self, secret_env, tmp_path) -> None:
        """The case chmod cannot fix: the other name refers to the same inode,
        so its holder reads whatever is written here regardless of mode."""
        env = tmp_path / ".env"
        env.write_text("", encoding="utf-8")
        env.chmod(0o600)
        os.link(env, tmp_path / "shadow")
        with pytest.raises(secret_env.UnsafeEnvFile, match="hard link"):
            secret_env.validate_target(env)

    @pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o666, 0o660])
    def test_an_already_readable_file_is_refused(self, secret_env, env_path, mode) -> None:
        env_path.write_text("", encoding="utf-8")
        env_path.chmod(mode)
        with pytest.raises(secret_env.UnsafeEnvFile, match="readable beyond its owner"):
            secret_env.validate_target(env_path)

    def test_a_safe_existing_file_is_accepted(self, secret_env, env_path) -> None:
        """The ordinary re-run. Refusing here would break every second install."""
        env_path.write_text("A=1\n", encoding="utf-8")
        env_path.chmod(0o600)
        assert secret_env.validate_target(env_path) is True

    def test_an_absent_file_is_not_an_error(self, secret_env, env_path) -> None:
        assert secret_env.validate_target(env_path) is False

    def test_create_refuses_to_clobber(self, secret_env, env_path) -> None:
        """O_EXCL. If something appeared at this path since the caller checked,
        it is not ours to overwrite with credentials."""
        env_path.write_text("someone else's\n", encoding="utf-8")
        with pytest.raises(FileExistsError):
            secret_env.create_exclusive(env_path, TOKEN)
        assert env_path.read_text(encoding="utf-8") == "someone else's\n"


class TestNoSecretIsPrinted:
    def test_a_refusal_names_the_path_not_the_value(self, secret_env, env_path, capsys) -> None:
        """ "Do not print secret values" — a diagnostic that echoes the file is
        the leak it was added to prevent."""
        env_path.write_text(TOKEN, encoding="utf-8")
        env_path.chmod(0o644)
        code = secret_env.main(["check", str(env_path)])
        captured = capsys.readouterr()
        assert code == 2
        assert "s3cr3t-do-not-leak" not in captured.out + captured.err
        assert str(env_path) in captured.err


class TestTheKeyOperations:
    def test_append_once_leaves_an_existing_value_alone(self, secret_env, env_path) -> None:
        secret_env.create_exclusive(env_path, "TOKEN=original\n")
        secret_env.append_once(env_path, "TOKEN", "replacement")
        assert "TOKEN=original" in env_path.read_text(encoding="utf-8")

    def test_set_key_replaces_in_place(self, secret_env, env_path) -> None:
        secret_env.create_exclusive(env_path, "A=1\nB=2\nC=3\n")
        secret_env.set_key(env_path, "B", "changed")
        assert env_path.read_text(encoding="utf-8") == "A=1\nB=changed\nC=3\n"

    def test_only_if_blank_keeps_a_set_value(self, secret_env, env_path) -> None:
        secret_env.create_exclusive(env_path, "SECRET=already-set\n")
        secret_env.set_key(env_path, "SECRET", "new", only_if_blank=True)
        assert "already-set" in env_path.read_text(encoding="utf-8")

    def test_only_if_blank_fills_an_empty_value(self, secret_env, env_path) -> None:
        secret_env.create_exclusive(env_path, "SECRET=\n")
        secret_env.set_key(env_path, "SECRET", "generated", only_if_blank=True)
        assert "SECRET=generated" in env_path.read_text(encoding="utf-8")

    def test_ensure_api_keys_adds_without_dropping_others(self, secret_env, env_path) -> None:
        secret_env.create_exclusive(env_path, 'API_KEYS=["first"]\n')
        secret_env.ensure_api_keys(env_path, "second")
        assert '"first"' in env_path.read_text(encoding="utf-8")
        assert '"second"' in env_path.read_text(encoding="utf-8")

    def test_ensure_api_keys_is_idempotent(self, secret_env, env_path) -> None:
        """Installers re-run. Appending the same token each time would grow the
        array without bound."""
        secret_env.create_exclusive(env_path, 'API_KEYS=["tok"]\n')
        secret_env.ensure_api_keys(env_path, "tok")
        secret_env.ensure_api_keys(env_path, "tok")
        assert env_path.read_text(encoding="utf-8").count("tok") == 1

    def test_a_corrupt_api_keys_line_is_replaced_not_crashed_on(self, secret_env, env_path) -> None:
        """A hand-edited `.env` should not stop the installer; the token still
        has to end up present."""
        secret_env.create_exclusive(env_path, "API_KEYS=not json\n")
        secret_env.ensure_api_keys(env_path, "tok")
        assert '["tok"]' in env_path.read_text(encoding="utf-8")


class TestTheInstallersUseIt:
    """A helper nothing calls fixes nothing — the same shape as the guards in
    #419, which needed tests at their call sites rather than on the module."""

    def test_no_installer_still_chmods_a_secret_file_after_writing_it(self) -> None:
        for name in ("install.sh", "get.sh"):
            body = (ROOT / name).read_text(encoding="utf-8")
            offenders = [
                line
                for line in body.splitlines()
                if "chmod 600" in line and not line.lstrip().startswith("#")
            ]
            assert not offenders, f"{name} still chmods after writing: {offenders}"

    def test_install_sh_creates_the_env_file_through_the_helper(self) -> None:
        body = (ROOT / "install.sh").read_text(encoding="utf-8")
        assert "secret_env_run create" in body
        assert 'cat > "$ENV_FILE"' not in body

    def test_install_sh_appends_through_the_helper(self) -> None:
        """`printf >> "$ENV_FILE"` creates the file under the umask when it is
        absent, which is the same defect one line smaller."""
        body = (ROOT / "install.sh").read_text(encoding="utf-8")
        assert '>> "$ENV_FILE"' not in body

    def test_get_sh_migrates_the_legacy_env_through_the_helper(self) -> None:
        body = (ROOT / "get.sh").read_text(encoding="utf-8")
        assert "secret_env.py" in body
        assert 'cp "$LEGACY_DIR/.env"' not in body


class TestTheCommandLine:
    """`install.sh` and `get.sh` reach this module only through its CLI, so the
    dispatch is production code, not a convenience wrapper."""

    def test_create_writes_stdin_at_0600(self, secret_env, env_path, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(TOKEN))
        assert secret_env.main(["create", str(env_path)]) == 0
        assert env_path.read_text(encoding="utf-8") == TOKEN
        assert _mode(env_path) == 0o600

    def test_create_on_an_existing_file_exits_3(self, secret_env, env_path, monkeypatch) -> None:
        """A distinct exit code, so `get.sh` can tell "already there" from
        "unsafe" and say something accurate."""
        env_path.write_text("mine\n", encoding="utf-8")
        monkeypatch.setattr("sys.stdin", io.StringIO(TOKEN))
        assert secret_env.main(["create", str(env_path)]) == 3
        assert env_path.read_text(encoding="utf-8") == "mine\n"

    def test_write_creates_when_absent(self, secret_env, env_path, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(TOKEN))
        assert secret_env.main(["write", str(env_path)]) == 0
        assert _mode(env_path) == 0o600

    def test_write_replaces_when_present(self, secret_env, env_path, monkeypatch) -> None:
        secret_env.create_exclusive(env_path, "OLD=1\n")
        monkeypatch.setattr("sys.stdin", io.StringIO(TOKEN))
        assert secret_env.main(["write", str(env_path)]) == 0
        assert env_path.read_text(encoding="utf-8") == TOKEN

    def test_set_key(self, secret_env, env_path) -> None:
        secret_env.create_exclusive(env_path, "A=1\n")
        assert secret_env.main(["set-key", str(env_path), "A", "2"]) == 0
        assert env_path.read_text(encoding="utf-8") == "A=2\n"

    def test_set_key_only_if_blank(self, secret_env, env_path) -> None:
        secret_env.create_exclusive(env_path, "A=keep\n")
        assert secret_env.main(["set-key", str(env_path), "A", "no", "--only-if-blank"]) == 0
        assert env_path.read_text(encoding="utf-8") == "A=keep\n"

    def test_append_once(self, secret_env, env_path) -> None:
        secret_env.create_exclusive(env_path, "A=1\n")
        assert secret_env.main(["append-once", str(env_path), "B", "2"]) == 0
        assert "B=2" in env_path.read_text(encoding="utf-8")

    def test_ensure_api_keys(self, secret_env, env_path) -> None:
        secret_env.create_exclusive(env_path, "A=1\n")
        assert secret_env.main(["ensure-api-keys", str(env_path), "tok"]) == 0
        assert 'API_KEYS=["tok"]' in env_path.read_text(encoding="utf-8")

    def test_check_passes_on_a_safe_file(self, secret_env, env_path) -> None:
        secret_env.create_exclusive(env_path, TOKEN)
        assert secret_env.main(["check", str(env_path)]) == 0

    def test_it_runs_as_a_subprocess_the_way_the_installer_calls_it(self, tmp_path: Path) -> None:
        """The installer shells out; nothing above proves the file is
        executable as a script with a working `__main__` guard."""
        target = tmp_path / ".env"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "create", str(target)],
            input=TOKEN,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert target.read_text(encoding="utf-8") == TOKEN
        assert _mode(target) == 0o600


class TestTheRemainingRefusals:
    def test_a_directory_at_the_path_is_refused(self, secret_env, tmp_path) -> None:
        """`mkdir .env` is a plausible accident, and O_WRONLY on a directory
        raises something far less clear than this."""
        directory = tmp_path / ".env"
        directory.mkdir()
        with pytest.raises(secret_env.UnsafeEnvFile, match="not a regular file"):
            secret_env.validate_target(directory)

    def test_a_file_owned_by_someone_else_is_refused(
        self, secret_env, env_path, monkeypatch
    ) -> None:
        """Simulated by moving the caller rather than the file: the test suite
        does not run as root and cannot chown."""
        env_path.write_text("", encoding="utf-8")
        env_path.chmod(0o600)
        # Read the real uid first: `secret_env.os` is the same module object as
        # `os`, so a lambda calling os.getuid() after the patch calls itself.
        someone_else = os.getuid() + 1
        monkeypatch.setattr(secret_env.os, "getuid", lambda: someone_else)
        with pytest.raises(secret_env.UnsafeEnvFile, match="owned by uid"):
            secret_env.validate_target(env_path)

    def test_a_directory_that_cannot_be_fsynced_is_not_fatal(
        self, secret_env, env_path, monkeypatch
    ) -> None:
        """Some filesystems refuse fsync on a directory handle. The replace is
        still atomic; only durability across a power loss is weaker, and that
        is not worth failing an install over."""
        real_fsync = secret_env.os.fsync

        def picky(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("fsync not supported here")
            return real_fsync(fd)

        monkeypatch.setattr(secret_env.os, "fsync", picky)
        secret_env.create_exclusive(env_path, TOKEN)
        assert env_path.read_text(encoding="utf-8") == TOKEN


class TestTheRemainingKeyOperations:
    def test_append_once_adds_an_absent_key(self, secret_env, env_path) -> None:
        secret_env.create_exclusive(env_path, "A=1\n")
        secret_env.append_once(env_path, "B", "2")
        assert env_path.read_text(encoding="utf-8") == "A=1\nB=2\n"

    def test_ensure_api_keys_creates_the_line_when_absent(self, secret_env, env_path) -> None:
        secret_env.create_exclusive(env_path, "OTHER=1\n")
        secret_env.ensure_api_keys(env_path, "tok")
        assert 'API_KEYS=["tok"]' in env_path.read_text(encoding="utf-8")

    def test_a_non_list_api_keys_value_is_replaced(self, secret_env, env_path) -> None:
        """Valid JSON, wrong shape — `{}` parses but cannot be appended to."""
        secret_env.create_exclusive(env_path, "API_KEYS={}\n")
        secret_env.ensure_api_keys(env_path, "tok")
        assert 'API_KEYS=["tok"]' in env_path.read_text(encoding="utf-8")

    def test_writing_to_an_absent_path_creates_it(self, secret_env, env_path) -> None:
        secret_env.write(env_path, TOKEN)
        assert _mode(env_path) == 0o600

    def test_set_key_on_an_absent_file_creates_it(self, secret_env, env_path) -> None:
        secret_env.set_key(env_path, "A", "1")
        assert env_path.read_text(encoding="utf-8") == "A=1\n"
        assert _mode(env_path) == 0o600


class TestTheRealShellPath:
    """`release-installer.yml` runs `./install.sh`, but it triggers only on tags
    and `workflow_dispatch` — so no PR check executes a line of the installer.

    Every other test here drives the Python helper directly, which proves the
    helper and not the shell that calls it. These source the real functions out
    of `install.sh` and run them, so a rewiring mistake in the shell fails a PR
    check rather than a release.
    """

    #: The env-writing functions, lifted verbatim from install.sh.
    _FUNCTIONS = (
        "ensure_python",
        "secret_env_run",
        "env_has",
        "append_env_once",
        "fill_env_value",
        "set_env_value",
        "ensure_api_keys_contains",
        "verify_env_file",
    )

    def _harness(self) -> str:
        extract = ";".join(f"/^{name}()/,/^}}/p" for name in self._FUNCTIONS)
        return f"""
set -euo pipefail
SCRIPT_DIR={str(ROOT)!r}
ENV_FILE=".env"
PYTHON_CMD=()
warn() {{ echo "WARN: $*" >&2; }}
ok() {{ :; }}
info() {{ :; }}
source <(sed -n {extract!r} "$SCRIPT_DIR/install.sh")
"""

    def _run(self, workdir: Path, script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", self._harness() + script],
            cwd=workdir,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_every_shell_write_path_lands_at_0600(self, tmp_path: Path) -> None:
        """`umask 0000` is what makes this an assertion rather than a
        coincidence: the pre-#357 shell produced 666 here."""
        result = self._run(
            tmp_path,
            """
umask 0000
printf 'MAISTRO_ACCESS_TOKEN=tok\\nAPI_KEYS=["tok"]\\n' | secret_env_run create
stat -c '%a create' .env
append_env_once NEWKEY hello;   stat -c '%a append_env_once' .env
set_env_value NEWKEY replaced;  stat -c '%a set_env_value' .env
fill_env_value BLANKY filled;   stat -c '%a fill_env_value' .env
ensure_api_keys_contains tok2;  stat -c '%a ensure_api_keys' .env
verify_env_file
""",
        )
        assert result.returncode == 0, result.stderr
        modes = [line.split()[0] for line in result.stdout.strip().splitlines()]
        assert modes, f"the harness produced no output: {result.stderr}"
        assert set(modes) == {"600"}, f"a shell write path widened the mode: {result.stdout}"

    def test_the_shell_writes_the_values_it_was_given(self, tmp_path: Path) -> None:
        """Mode is not the only thing that has to survive the rewiring: the
        three functions that used to be Python heredocs have to keep their
        replace / append / fill-if-blank semantics."""
        result = self._run(
            tmp_path,
            """
printf 'A=1\\nSECRET=\\n' | secret_env_run create
append_env_once A 999
append_env_once B 2
fill_env_value SECRET generated
set_env_value A replaced
ensure_api_keys_contains tok
cat .env
""",
        )
        assert result.returncode == 0, result.stderr
        body = result.stdout
        assert "A=replaced" in body, "set_env_value did not replace in place"
        assert "B=2" in body, "append_env_once did not add the absent key"
        assert "999" not in body, "append_env_once overwrote an existing value"
        assert "SECRET=generated" in body, "fill_env_value did not fill the blank"
        assert '["tok"]' in body

    def test_the_shell_refuses_an_unsafe_existing_file(self, tmp_path: Path) -> None:
        """`verify_env_file` warns rather than silently chmod-ing, so a file
        that may already have leaked is reported instead of quietly narrowed."""
        env = tmp_path / ".env"
        env.write_text(TOKEN, encoding="utf-8")
        env.chmod(0o644)
        result = self._run(tmp_path, "verify_env_file")
        assert "did not pass the credential-file safety check" in result.stderr
        assert "s3cr3t-do-not-leak" not in result.stdout + result.stderr


class TestReservingAPathForAnotherProgram:
    """`create_exclusive` covers a secret this process produces. The recovery
    phrase is produced by the *server* and lands via `curl -o`, which supplies
    a mode only when it creates the file — under the caller's umask (#360)."""

    def test_the_reserved_file_is_owner_only(self, secret_env, tmp_path: Path) -> None:
        target = tmp_path / ".setup-response.json"
        secret_env.reserve(target)

        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_it_is_owner_only_even_under_a_permissive_umask(
        self, secret_env, tmp_path: Path
    ) -> None:
        """0644 is what the installer was actually producing, so the umask is
        the condition under test rather than a detail of the environment."""
        target = tmp_path / ".setup-response.json"
        previous = os.umask(0o000)
        try:
            secret_env.reserve(target)
        finally:
            os.umask(previous)

        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_the_reserved_file_is_empty(self, secret_env, tmp_path: Path) -> None:
        """A writer that appends rather than truncates must not inherit
        anything, and a reader must not see a stale body as this run's."""
        target = tmp_path / ".setup-response.json"
        secret_env.reserve(target)

        assert target.read_bytes() == b""

    def test_a_writer_that_truncates_keeps_the_narrow_mode(
        self, secret_env, tmp_path: Path
    ) -> None:
        """The property the whole approach rests on: `O_WRONLY|O_CREAT|O_TRUNC`
        — what curl does — does not widen an existing file's mode."""
        target = tmp_path / ".setup-response.json"
        secret_env.reserve(target)

        previous = os.umask(0o000)
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
            os.write(fd, b'{"mnemonic": ["word"]}')
            os.close(fd)
        finally:
            os.umask(previous)

        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_a_leftover_from_an_interrupted_run_is_purged_not_refused(
        self, secret_env, tmp_path: Path
    ) -> None:
        """`create_exclusive` would raise here. That is the wrong answer: the
        leftover is itself secret-bearing, so failing preserves exactly the
        file we want gone, and it fails on every retry from then on."""
        target = tmp_path / ".setup-response.json"
        target.write_text('{"mnemonic": ["stale", "words"]}', encoding="utf-8")

        secret_env.reserve(target)

        assert target.read_bytes() == b""
        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_a_leftover_at_a_wide_mode_is_narrowed(self, secret_env, tmp_path: Path) -> None:
        """The exact state the old installer left behind after an interrupt."""
        target = tmp_path / ".setup-response.json"
        target.write_text('{"mnemonic": ["stale"]}', encoding="utf-8")
        target.chmod(0o644)

        secret_env.reserve(target)

        assert stat.S_IMODE(target.stat().st_mode) == 0o600


class TestPurgeIsHonestAboutWhatItDoes:
    """It is not secure erasure and nothing may say it is. What it must do is
    be no worse than `rm`, which the shell it replaces was not."""

    def test_the_file_is_gone(self, secret_env, tmp_path: Path) -> None:
        target = tmp_path / "creds.json"
        target.write_text("hunter2", encoding="utf-8")

        assert secret_env.purge(target) is True
        assert not target.exists()

    def test_purging_nothing_is_not_an_error(self, secret_env, tmp_path: Path) -> None:
        """Called from an EXIT trap on paths that already purged."""
        assert secret_env.purge(tmp_path / "never-existed") is False

    def test_purging_twice_is_not_an_error(self, secret_env, tmp_path: Path) -> None:
        target = tmp_path / "creds.json"
        target.write_text("hunter2", encoding="utf-8")

        assert secret_env.purge(target) is True
        assert secret_env.purge(target) is False

    def test_an_empty_file_is_removed_without_a_zero_write(
        self, secret_env, tmp_path: Path
    ) -> None:
        target = tmp_path / "empty"
        target.touch()

        assert secret_env.purge(target) is True
        assert not target.exists()

    def test_it_does_not_truncate_before_overwriting(self, secret_env, tmp_path: Path) -> None:
        """The defect in the shell it replaces. `head -c $size /dev/zero > $f`
        truncates at redirection setup, *before* a byte is written — so the
        original blocks return to the allocator first and the zeros land
        wherever the filesystem next chooses. Asserted on the descriptor flags
        rather than on an outcome, because the outcome is exactly what a
        filesystem is free to vary."""
        target = tmp_path / "creds.json"
        target.write_text("x" * 64, encoding="utf-8")

        opened: list[int] = []
        real_open = os.open

        def recording_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
            if str(path) == str(target):
                opened.append(flags)
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(secret_env.os, "open", recording_open):
            secret_env.purge(target)

        assert opened, "purge never opened the target"
        assert all(not flags & os.O_TRUNC for flags in opened)

    def test_the_bytes_written_cover_the_whole_file(self, secret_env, tmp_path: Path) -> None:
        """Not a claim that the blocks are gone — a claim that the zeros are at
        least as long as the secret, so nothing is left half-overwritten."""
        target = tmp_path / "creds.json"
        target.write_text("word " * 24, encoding="utf-8")
        size = target.stat().st_size

        written: list[bytes] = []
        real_write = os.write

        def recording_write(fd: int, data: bytes) -> int:
            written.append(data)
            return real_write(fd, data)

        with mock.patch.object(secret_env.os, "write", recording_write):
            secret_env.purge(target)

        assert sum(len(chunk) for chunk in written) >= size
        assert all(set(chunk) <= {0} for chunk in written)

    def test_a_symlink_is_unlinked_rather_than_followed(self, secret_env, tmp_path: Path) -> None:
        """Following it would zero whatever it points at, which is the classic
        way a cleanup step becomes a weapon."""
        victim = tmp_path / "someone-elses-file"
        victim.write_text("important", encoding="utf-8")
        link = tmp_path / ".setup-response.json"
        link.symlink_to(victim)

        assert secret_env.purge(link) is True
        assert not link.exists()
        assert victim.read_text(encoding="utf-8") == "important"

    def test_a_hard_linked_file_is_not_zeroed_through(self, secret_env, tmp_path: Path) -> None:
        """The same attack without a symlink. Zeroing the inode would destroy
        the other name's contents too."""
        other = tmp_path / "other-name"
        other.write_text("important", encoding="utf-8")
        target = tmp_path / ".setup-response.json"
        os.link(other, target)

        secret_env.purge(target)

        assert other.read_text(encoding="utf-8") == "important"

    def test_a_directory_is_refused_rather_than_removed(self, secret_env, tmp_path: Path) -> None:
        target = tmp_path / "a-directory"
        target.mkdir()

        with pytest.raises(OSError):
            secret_env.purge(target)

        assert target.is_dir()

    def test_an_already_world_readable_file_is_still_purged(
        self, secret_env, tmp_path: Path
    ) -> None:
        """`validate_target` refuses a wide mode, correctly, because writing
        more secrets into it would compound the exposure. Purging is the
        opposite case: an exposed file is the one most worth removing, so
        refusing it here would leave it exactly where it is."""
        target = tmp_path / ".setup-response.json"
        target.write_text('{"mnemonic": ["word"]}', encoding="utf-8")
        target.chmod(0o644)

        assert secret_env.purge(target) is True
        assert not target.exists()


class TestPurgeWhenTheOverwriteCannotHappen:
    """The overwrite is the part that carries no guarantee anyway. When it
    cannot run at all, removing the name is still strictly better than leaving
    the secret in place — so none of these may abort before the unlink."""

    def test_a_write_failure_still_removes_the_file(
        self, secret_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A full disk or a read-only remount. Keeping the file because the
        zeroing failed would preserve exactly what the caller asked to
        destroy."""
        target = tmp_path / ".setup-response.json"
        target.write_text('{"mnemonic": ["word"]}', encoding="utf-8")

        def failing_write(fd: int, data: bytes) -> int:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(secret_env.os, "write", failing_write)

        assert secret_env.purge(target) is True
        assert not target.exists()

    def test_a_file_owned_by_someone_else_is_unlinked_not_written_through(
        self, secret_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Zeroing another user's file is the same mistake as following a
        symlink. Dropping the name we were handed removes this reference
        without touching what it refers to.

        `secret_env.os` *is* `os`, so the replacement has to close over the
        value rather than call `os.getuid()` again — otherwise it calls
        itself."""
        target = tmp_path / ".setup-response.json"
        target.write_text("not mine", encoding="utf-8")
        someone_else = os.getuid() + 1
        monkeypatch.setattr(secret_env.os, "getuid", lambda: someone_else)

        assert secret_env.purge(target) is True
        assert not target.exists()

    def test_the_refusal_path_reports_it_removed_something(
        self, secret_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """True and False mean "was there" and "was not", not "overwrote" and
        "did not" — a caller that treated the refusal path as "nothing here"
        would skip its own cleanup."""
        target = tmp_path / ".setup-response.json"
        target.write_text("not mine", encoding="utf-8")
        someone_else = os.getuid() + 1
        monkeypatch.setattr(secret_env.os, "getuid", lambda: someone_else)

        assert secret_env.purge(target) is True
        assert secret_env.purge(target) is False


class TestThePurgeAndReserveCommandLine:
    """The installer reaches this module only through the CLI, so an
    unreachable subcommand is an unreachable feature."""

    def test_reserve_creates_the_file(self, secret_env, tmp_path: Path) -> None:
        target = tmp_path / ".setup-response.json"

        assert secret_env.main(["reserve", str(target)]) == 0
        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_purge_removes_the_file(self, secret_env, tmp_path: Path) -> None:
        target = tmp_path / "creds.json"
        target.write_text("hunter2", encoding="utf-8")

        assert secret_env.main(["purge", str(target)]) == 0
        assert not target.exists()

    def test_purging_an_absent_path_succeeds(self, secret_env, tmp_path: Path) -> None:
        """It runs from an EXIT trap that fires on paths where the file was
        already removed; a non-zero exit there would make the installer look
        like it failed."""
        assert secret_env.main(["purge", str(tmp_path / "gone")]) == 0

    def test_neither_command_prints_the_secret(self, secret_env, tmp_path: Path, capsys) -> None:
        target = tmp_path / "creds.json"
        target.write_text("hunter2-the-actual-password", encoding="utf-8")

        secret_env.main(["purge", str(target)])
        secret_env.main(["reserve", str(target)])

        captured = capsys.readouterr()
        assert "hunter2" not in captured.out
        assert "hunter2" not in captured.err
