"""Tests for bootstrap-credentials staging (SPEC-072726-3439 Phase 1)."""

from __future__ import annotations

import json
import os
import stat
import threading
from contextlib import suppress
from pathlib import Path, PosixPath

import pytest
from pydantic import ValidationError

from maistro_bootstrap.credentials import (
    BOOTSTRAP_CREDENTIALS_FILENAME,
    UnsafeStagedCredentialsError,
    build_bootstrap_credentials,
    staged_credentials_valid,
    validate_bootstrap_credentials,
    write_bootstrap_credentials,
)
from maistro_bootstrap.schema import InstallAnswersV1


def _answers(**overrides: object) -> InstallAnswersV1:
    return InstallAnswersV1.model_validate(
        {"admin_user": "root-admin", "daily_driver_user": "alice", **overrides}
    )


def _creds(admin_password: str = "a", user_password: str = "u") -> dict[str, object]:
    return build_bootstrap_credentials(
        _answers(), admin_password=admin_password, user_password=user_password
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _staged_path(tmp_path: Path) -> Path:
    return tmp_path / BOOTSTRAP_CREDENTIALS_FILENAME


def _write_valid_staged_file(path: Path, creds: dict[str, object] | None = None) -> None:
    """Plant a legitimate-looking prior staging (what the old code produced)."""
    path.write_text(
        json.dumps(creds if creds is not None else _creds(), indent=2) + "\n", encoding="utf-8"
    )
    path.chmod(0o600)


@pytest.fixture
def permissive_umask():
    """umask 0000: any mode we end up seeing must come from an explicit
    fchmod, never from inheriting the caller's."""
    previous = os.umask(0o000)
    yield
    os.umask(previous)


def test_build_payload_carries_names_and_crypto_module() -> None:
    creds = build_bootstrap_credentials(_answers(), admin_password="pw-a", user_password="pw-u")
    assert creds["admin_username"] == "root-admin"
    assert creds["user_username"] == "alice"
    assert creds["optional_modules"] == ["crypto_identity"]
    assert creds["hardware_preset"] == "auto"


def test_no_crypto_profile_omits_identity_module() -> None:
    creds = build_bootstrap_credentials(
        _answers(crypto_profile="no_crypto"), admin_password="a", user_password="u"
    )
    assert creds["optional_modules"] == []


def test_write_is_owner_only_and_round_trips(tmp_path: Path) -> None:
    creds = build_bootstrap_credentials(_answers(), admin_password="a", user_password="u")
    path = write_bootstrap_credentials(tmp_path, creds)
    assert path.name == BOOTSTRAP_CREDENTIALS_FILENAME
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8")) == creds


def test_successful_staging_leaves_no_temp_files_behind(tmp_path: Path) -> None:
    """The temp file is an implementation detail; if one survives, a secret
    copy survives beside the staged file (#809 AC-2/AC-5)."""
    write_bootstrap_credentials(tmp_path, _creds())
    assert [p.name for p in tmp_path.iterdir()] == [BOOTSTRAP_CREDENTIALS_FILENAME]


@pytest.mark.ac
@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes and symlinks")
class TestSymlinkPlantingIsRefused:
    """#809 AC-1 / AC-5: a pre-planted symlink must not redirect the secrets."""

    def test_a_symlink_at_the_final_path_is_refused(self, tmp_path: Path) -> None:
        victim = tmp_path / "outside-the-artifacts-dir"
        victim.write_text("original\n", encoding="utf-8")
        _staged_path(tmp_path).symlink_to(victim)

        with pytest.raises(UnsafeStagedCredentialsError, match="symlink"):
            write_bootstrap_credentials(tmp_path, _creds(admin_password="brand-new-secret"))

    def test_the_symlink_target_is_not_written(self, tmp_path: Path) -> None:
        """The consequence, not just the check: generated passwords must not
        land wherever the link points."""
        victim = tmp_path / "outside-the-artifacts-dir"
        victim.write_text("original\n", encoding="utf-8")
        _staged_path(tmp_path).symlink_to(victim)

        with pytest.raises(UnsafeStagedCredentialsError):
            write_bootstrap_credentials(tmp_path, _creds(admin_password="brand-new-secret"))

        assert victim.read_text(encoding="utf-8") == "original\n"
        assert "brand-new-secret" not in victim.read_text(encoding="utf-8")

    def test_a_dangling_symlink_is_refused_too(self, tmp_path: Path) -> None:
        _staged_path(tmp_path).symlink_to(tmp_path / "nowhere")
        with pytest.raises(UnsafeStagedCredentialsError):
            write_bootstrap_credentials(tmp_path, _creds())


@pytest.mark.ac
@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
class TestAPreexistingPermissiveFileIsNotReused:
    """#809 AC-1 / AC-5: the 0644 leftover from an interrupted old-style run."""

    @pytest.mark.parametrize("stale_content", ["", '{"admin_user'], ids=["empty", "truncated-json"])
    def test_secret_bytes_never_land_in_the_permissive_inode(
        self, tmp_path: Path, stale_content: str
    ) -> None:
        stale = _staged_path(tmp_path)
        stale.write_text(stale_content, encoding="utf-8")
        stale.chmod(0o644)
        stale_ino = stale.stat().st_ino

        path = write_bootstrap_credentials(tmp_path, _creds())

        assert _mode(path) == 0o600
        assert path.stat().st_ino != stale_ino  # a fresh inode, not a re-chmodded one
        assert json.loads(path.read_text(encoding="utf-8")) == _creds()

    def test_even_valid_json_at_0644_is_restaged_private(
        self, tmp_path: Path, permissive_umask
    ) -> None:
        """Permissive-but-parseable is the worst leftover: valid shape, exposed
        bytes. It is replaced, not trusted (#809 AC-3)."""
        stale = _staged_path(tmp_path)
        _write_valid_staged_file(stale, _creds(admin_password="old-secret"))
        stale.chmod(0o644)

        path = write_bootstrap_credentials(tmp_path, _creds(admin_password="new-secret"))

        assert _mode(path) == 0o600
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["admin_password"] == "new-secret"


@pytest.mark.ac
@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
class TestInterruptionNeverLeavesAPartialFile:
    """#809 AC-2 / AC-5: kill the run anywhere and no truncated JSON survives
    at the final path, and no secret-bearing temp file is left behind."""

    def test_crash_before_promotion_keeps_the_previous_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A valid-but-permissive leftover forces the re-stage path; dying
        right before the rename must leave it byte-for-byte intact."""
        staged = _staged_path(tmp_path)
        _write_valid_staged_file(staged, _creds(admin_password="previous-secret"))
        staged.chmod(0o644)  # permissive: not reusable, so staging proceeds

        def boom(src: object, dst: object) -> None:
            raise OSError("simulated crash between fsync and rename")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError, match="simulated crash"):
            write_bootstrap_credentials(tmp_path, _creds(admin_password="next-secret"))

        payload = json.loads(staged.read_text(encoding="utf-8"))
        assert payload["admin_password"] == "previous-secret"
        assert [p.name for p in tmp_path.iterdir()] == [BOOTSTRAP_CREDENTIALS_FILENAME]

    def test_crash_mid_write_leaves_no_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dying with the temp file half-written must leave neither a partial
        final file nor a secret-bearing temp file behind."""
        staged = _staged_path(tmp_path)
        staged.write_text('{"admin_user', encoding="utf-8")  # truncated: re-stage
        staged.chmod(0o600)

        def boom(fd: object) -> None:
            raise OSError("simulated crash while writing the temp file")

        monkeypatch.setattr(os, "fsync", boom)
        with pytest.raises(OSError, match="simulated crash"):
            write_bootstrap_credentials(tmp_path, _creds(admin_password="next-secret"))

        assert staged.read_text(encoding="utf-8") == '{"admin_user'
        assert [p.name for p in tmp_path.iterdir()] == [BOOTSTRAP_CREDENTIALS_FILENAME]


@pytest.mark.ac
@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
class TestExistingFileIsParseValidatedBeforeReuse:
    """#809 AC-3: existence alone is not success."""

    def test_a_valid_private_staging_is_reused_unchanged(self, tmp_path: Path) -> None:
        staged = _staged_path(tmp_path)
        _write_valid_staged_file(staged, _creds(admin_password="already-there"))
        before = staged.stat()

        path = write_bootstrap_credentials(tmp_path, _creds(admin_password="different-prompt"))

        assert path == staged
        assert path.stat().st_ino == before.st_ino  # reused, not rewritten
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["admin_password"] == "already-there"

    def test_a_truncated_private_file_is_restaged_not_trusted(self, tmp_path: Path) -> None:
        """The exact failure the old non-atomic write could leave behind."""
        staged = _staged_path(tmp_path)
        staged.write_text('{"admin_username": "root-admin", "admin_passw', encoding="utf-8")
        staged.chmod(0o600)

        assert staged_credentials_valid(staged) is False
        path = write_bootstrap_credentials(tmp_path, _creds())

        assert json.loads(path.read_text(encoding="utf-8")) == _creds()  # valid, not truncated

    def test_validity_requires_parseable_valid_shape(self, tmp_path: Path) -> None:
        staged = _staged_path(tmp_path)
        # Wrong shape entirely: parses as JSON, is not staged credentials.
        staged.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
        staged.chmod(0o600)
        assert staged_credentials_valid(staged) is False

    def test_an_absent_file_is_not_staged(self, tmp_path: Path) -> None:
        assert staged_credentials_valid(_staged_path(tmp_path)) is False

    def test_a_shared_inode_is_not_reusable(self, tmp_path: Path) -> None:
        """nlink > 1: another name reads whatever lands here regardless of
        mode, so it is replaced with a fresh single-link inode."""
        staged = _staged_path(tmp_path)
        _write_valid_staged_file(staged, _creds(admin_password="old-secret"))
        shadow = tmp_path / "shadow"
        os.link(staged, shadow)

        assert staged_credentials_valid(staged) is False
        path = write_bootstrap_credentials(tmp_path, _creds(admin_password="new-secret"))

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["admin_password"] == "new-secret"
        # The watching name kept the old inode; it never saw the new secret.
        old_payload = json.loads(shadow.read_text(encoding="utf-8"))
        assert old_payload["admin_password"] == "old-secret"


@pytest.mark.ac
@pytest.mark.skipif(os.name == "nt", reason="POSIX file kinds and stat")
class TestNonRegularPathHoldersAreRefused:
    """#809 AC-5: a path held by anything other than a regular file — a
    directory, or an inode swapped in mid-check — is wreckage or a redirect,
    never staged input to trust or write through."""

    def test_a_directory_at_the_final_path_is_refused(self, tmp_path: Path) -> None:
        staged = _staged_path(tmp_path)
        staged.mkdir()

        with pytest.raises(UnsafeStagedCredentialsError, match="not a regular file"):
            staged_credentials_valid(staged)
        with pytest.raises(UnsafeStagedCredentialsError, match="not a regular file"):
            write_bootstrap_credentials(tmp_path, _creds())

    def test_an_inode_swapped_to_non_regular_mid_check_is_not_trusted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`is_file()` and the later `stat()` are two system calls; between
        them the name can be repointed at a FIFO or device node. The stat
        recheck must read that as wreckage, not reuse it."""
        staged = _staged_path(tmp_path)
        _write_valid_staged_file(staged, _creds(admin_password="old-secret"))

        real_stat = Path.stat
        looks = 0

        def racing_stat(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
            nonlocal looks
            # Only the symlink-following looks matter: `is_file()` and the
            # recheck inside `staged_credentials_valid`. The first one must
            # still see a regular file; the recheck sees the swap.
            if self == staged and follow_symlinks:
                looks += 1
                if looks > 1:  # the recheck: the name now resolves to a FIFO
                    was = real_stat(self, follow_symlinks=follow_symlinks)
                    return os.stat_result(
                        (
                            stat.S_IFIFO | stat.S_IMODE(was.st_mode),
                            was.st_ino,
                            was.st_dev,
                            was.st_nlink,
                            was.st_uid,
                            was.st_gid,
                            was.st_size,
                            was.st_atime,
                            was.st_mtime,
                            was.st_ctime,
                        )
                    )
            return real_stat(self, follow_symlinks=follow_symlinks)

        monkeypatch.setattr(Path, "stat", racing_stat)
        assert staged_credentials_valid(staged) is False


@pytest.mark.ac
class TestWindowsSkipsThePOSIXOnlyChecks:
    """The mode/nlink gates and the fchmod are POSIX hardening: on nt they
    are skipped, and both entry points still work there. Pinned from POSIX
    with `os.name` simulated, because the suites run nowhere else."""

    def test_validity_skips_mode_and_nlink_checks_on_windows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        staged = _staged_path(tmp_path)
        _write_valid_staged_file(staged, _creds(admin_password="already-there"))
        staged.chmod(0o644)  # POSIX-only metadata; must not block reuse on nt

        monkeypatch.setattr(os, "name", "nt")

        assert staged_credentials_valid(staged) is True

    def test_staging_skips_fchmod_on_windows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `Path(...)` picks its flavour from `os.name` at construction time,
        # so faking nt also has to pin the module's `Path` to `PosixPath` —
        # otherwise the temp file's name re-renders through `WindowsPath`
        # and the rename misses. The syscalls underneath stay POSIX.
        monkeypatch.setattr("maistro_bootstrap.credentials.Path", PosixPath)
        monkeypatch.setattr(os, "name", "nt")

        path = write_bootstrap_credentials(tmp_path, _creds(admin_password="nt-secret"))

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["admin_password"] == "nt-secret"
        assert [p.name for p in tmp_path.iterdir()] == [BOOTSTRAP_CREDENTIALS_FILENAME]


@pytest.mark.ac
@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
class TestTheModeIsPrivateAtWriteTime:
    """#809 AC-4: observe the mode as the bytes land, not after a trailing
    chmod (there is no trailing chmod to lean on anymore)."""

    def test_the_promoted_inode_is_already_0600(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Intercept the promotion itself: at the instant the secret becomes
        visible under the final name, its inode already carries 0600 — and it
        comes from the same directory, so the replace is one rename."""
        observed: dict[str, object] = {}
        real_replace = os.replace

        def spy(src: str, dst: str) -> None:
            source = Path(src)
            observed["mode"] = _mode(source)
            observed["same_dir"] = source.parent == Path(dst).parent
            real_replace(src, dst)

        monkeypatch.setattr(os, "replace", spy)
        write_bootstrap_credentials(tmp_path, _creds(admin_password="landing-secret"))

        assert observed["mode"] == 0o600
        assert observed["same_dir"] is True

    def test_no_observer_ever_sees_secret_bytes_at_a_wider_mode(
        self, tmp_path: Path, permissive_umask
    ) -> None:
        """The actual claim. A watcher samples the path through a full staging
        cycle over a permissive leftover; every sample whose bytes contain the
        secret must have seen them at 0600. The old write-then-chmod fails
        this: the truncated 0644 inode briefly holds the new secret's prefix.

        Mode and bytes are sampled through one file descriptor, so each pair
        describes a single inode — no torn samples.
        """
        secret = "watched-secret-password"
        stale = _staged_path(tmp_path)
        stale.write_text('{"admin_user', encoding="utf-8")  # truncated old-run leftover
        stale.chmod(0o644)

        observed: list[tuple[int, str]] = []
        stop = threading.Event()

        def sample() -> tuple[int, str] | None:
            try:
                fd = os.open(stale, os.O_RDONLY)
            except OSError:
                return None
            try:
                mode = stat.S_IMODE(os.fstat(fd).st_mode)
                with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as fh:
                    data = fh.read()
                return mode, data
            finally:
                os.close(fd)

        def watch() -> None:
            while not stop.is_set():
                with suppress(OSError, ValueError):
                    pair = sample()
                    if pair is not None:
                        observed.append(pair)

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            for _ in range(5):
                # Reset to the dangerous starting state the same way an
                # interrupted old-style run would have left it: a permissive
                # file holding a truncated *non-secret* leftover. The reset
                # never widens the mode while the real secret is in the file —
                # the only thing allowed to expose bytes at 0600-or-wider is
                # the write under test.
                stale.write_text('{"admin_user', encoding="utf-8")
                stale.chmod(0o644)
                write_bootstrap_credentials(tmp_path, _creds(admin_password=secret))
        finally:
            stop.set()
            watcher.join(timeout=5)

        assert observed, "watcher never got a sample; the proof is vacuous"
        for mode, data in observed:
            if secret in data:
                assert mode == 0o600
        assert _mode(stale) == 0o600


def test_validate_rejects_missing_and_empty_secrets() -> None:
    with pytest.raises(ValueError, match="missing keys"):
        validate_bootstrap_credentials({"admin_username": "a"})
    with pytest.raises(ValueError, match="non-empty"):
        validate_bootstrap_credentials(
            {
                "admin_username": "a",
                "admin_password": "",
                "user_username": "u",
                "user_password": "x",
            }
        )


def test_answers_schema_still_rejects_password_fields() -> None:
    """AC-6: the answers schema must never grow secret fields silently.

    #810 AC-4: rejection is now an explicit error naming the key — distinct
    from a generic unknown-key typo in that the password fields are provably
    *not* schema fields at all (no declaration to typo your way around), and
    the failure is `extra_forbidden`, not a silent drop-to-default.
    """
    assert not {"admin_password", "user_password"} & set(InstallAnswersV1.model_fields)
    with pytest.raises(ValidationError) as excinfo:
        InstallAnswersV1.model_validate({"admin_password": "oops", "user_password": "oops"})
    errs = {(e["type"], ".".join(str(p) for p in e.get("loc", ()))) for e in excinfo.value.errors()}
    assert ("extra_forbidden", "admin_password") in errs
    assert ("extra_forbidden", "user_password") in errs
    # There is no validated answers object to inspect — the payload never
    # existed, which is stronger than "the fields disappeared after parsing".
