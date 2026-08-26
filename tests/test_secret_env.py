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
import os
import stat
import sys
import threading
from contextlib import suppress
from pathlib import Path

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
