"""Tests for `maistro security` (maistro.cli._security)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
import typer
from cryptography.fernet import Fernet

from maistro.cli._security import backup, purge_sessions, restore, rotate_credential_key
from maistro.credentials.store import (
    MASTER_KEY_FILENAME,
    STORE_FILENAME,
    UserCredentialStore,
    generate_master_key,
)


def _seed_credentials(data_dir: Path) -> bytes:
    store = UserCredentialStore.open(data_dir)
    store.set_secret("alice", "jira", "alice-token")
    store.set_secret("bob", "github", "bob-token")
    return (data_dir / MASTER_KEY_FILENAME).read_bytes()


class TestRotateCredentialKey:
    def test_dry_run_changes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        old_key = _seed_credentials(tmp_path)
        ciphertext = (tmp_path / STORE_FILENAME).read_bytes()

        rotate_credential_key(data_dir=str(tmp_path), new_key="", show_key=False, yes=False)

        out = capsys.readouterr().out
        assert "Planned: credential master-key rotation" in out
        assert "2 secret(s) across 2 user(s)" in out
        assert "DRY RUN" in out
        assert (tmp_path / MASTER_KEY_FILENAME).read_bytes() == old_key
        assert (tmp_path / STORE_FILENAME).read_bytes() == ciphertext

    def test_yes_rotates_and_reports(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        old_key = _seed_credentials(tmp_path)

        rotate_credential_key(data_dir=str(tmp_path), new_key="", show_key=False, yes=True)

        out = capsys.readouterr().out
        assert "Rotated." in out
        assert "2 secret(s) across 2 user(s)" in out
        new_key = (tmp_path / MASTER_KEY_FILENAME).read_bytes()
        assert new_key != old_key
        reopened = UserCredentialStore.open(tmp_path)
        assert reopened.use_secret("alice", "jira", lambda v: v) == "alice-token"

    def test_explicit_new_key_is_used(self, tmp_path: Path) -> None:
        _seed_credentials(tmp_path)
        chosen = generate_master_key()

        rotate_credential_key(
            data_dir=str(tmp_path), new_key=chosen.decode(), show_key=False, yes=True
        )

        assert (tmp_path / MASTER_KEY_FILENAME).read_bytes() == chosen
        payload = Fernet(chosen).decrypt((tmp_path / STORE_FILENAME).read_bytes())
        assert json.loads(payload.decode())["alice"]["jira"] == "alice-token"

    def test_show_key_prints_the_new_key(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_credentials(tmp_path)
        chosen = generate_master_key()

        rotate_credential_key(
            data_dir=str(tmp_path), new_key=chosen.decode(), show_key=True, yes=True
        )

        assert chosen.decode() in capsys.readouterr().out.replace("\n", "")

    def test_env_var_override_is_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_credentials(tmp_path)
        monkeypatch.setenv("HIVE_CREDENTIALS_MASTER_KEY", generate_master_key().decode())

        rotate_credential_key(data_dir=str(tmp_path), new_key="", show_key=False, yes=False)

        assert "HIVE_CREDENTIALS_MASTER_KEY is set in this environment" in capsys.readouterr().out

    def test_missing_data_dir_exits(self, tmp_path: Path) -> None:
        with pytest.raises(typer.Exit) as exc:
            rotate_credential_key(
                data_dir=str(tmp_path / "nope"), new_key="", show_key=False, yes=True
            )
        assert exc.value.exit_code == 2

    def test_invalid_new_key_exits_without_changing_anything(self, tmp_path: Path) -> None:
        old_key = _seed_credentials(tmp_path)
        ciphertext = (tmp_path / STORE_FILENAME).read_bytes()

        with pytest.raises(typer.Exit) as exc:
            rotate_credential_key(
                data_dir=str(tmp_path), new_key="obviously-not-fernet", show_key=False, yes=True
            )

        assert exc.value.exit_code == 1
        assert (tmp_path / MASTER_KEY_FILENAME).read_bytes() == old_key
        assert (tmp_path / STORE_FILENAME).read_bytes() == ciphertext

    def test_undecryptable_store_exits(self, tmp_path: Path) -> None:
        _seed_credentials(tmp_path)
        (tmp_path / STORE_FILENAME).write_bytes(b"corrupt")

        with pytest.raises(typer.Exit) as exc:
            rotate_credential_key(data_dir=str(tmp_path), new_key="", show_key=False, yes=True)

        assert exc.value.exit_code == 1


def _state_db_with_sessions(db_path: Path, session_ids: list[str]) -> None:
    from maistro.state import PersistedStore, State

    state = State(db_path=db_path)
    state.open_writer()
    persisted = PersistedStore(state)
    persisted.initialize()
    for sid in session_ids:
        persisted.put_raw("sessions", sid, json.dumps({"user_id": "u-" + sid}))
    state.flush()
    state.close()


def _remaining_sessions(db_path: Path) -> list[str]:
    from maistro.state import PersistedStore, State

    state = State(db_path=db_path)
    state.open_writer()
    persisted = PersistedStore(state)
    persisted.initialize()
    keys = [key for key, _ in persisted.list_all_raw("sessions")]
    state.close()
    return keys


class TestPurgeSessions:
    def test_dry_run_leaves_sessions_in_place(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = tmp_path / "state.db"
        _state_db_with_sessions(db, ["s1", "s2", "s3"])

        purge_sessions(data_dir=str(tmp_path), state_db="", yes=False)

        out = capsys.readouterr().out
        assert "to revoke: 3 session(s)" in out
        assert "DRY RUN" in out
        assert sorted(_remaining_sessions(db)) == ["s1", "s2", "s3"]

    def test_yes_revokes_every_session(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = tmp_path / "state.db"
        _state_db_with_sessions(db, ["s1", "s2", "s3"])

        purge_sessions(data_dir=str(tmp_path), state_db="", yes=True)

        assert "Revoked 3 session(s)." in capsys.readouterr().out
        assert _remaining_sessions(db) == []

    def test_explicit_state_db_path(self, tmp_path: Path) -> None:
        db = tmp_path / "elsewhere.db"
        _state_db_with_sessions(db, ["s1"])

        purge_sessions(data_dir=str(tmp_path), state_db=str(db), yes=True)

        assert _remaining_sessions(db) == []

    def test_missing_state_db_is_reported_not_fatal(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        purge_sessions(data_dir=str(tmp_path), state_db="", yes=True)
        assert "No state DB at" in capsys.readouterr().out.replace("\n", "")

    def test_missing_data_dir_exits(self, tmp_path: Path) -> None:
        with pytest.raises(typer.Exit) as exc:
            purge_sessions(data_dir=str(tmp_path / "nope"), state_db="", yes=True)
        assert exc.value.exit_code == 2


# --- backup / restore (#331) ---------------------------------------------


def _provisioned_data_dir(data_dir: Path) -> None:
    """A data directory holding every coupled durable file."""
    store = UserCredentialStore.open(data_dir)
    store.set_secret("alice", "github", "alice-token")
    (data_dir / "state.db").write_bytes(b"sqlite-bytes")
    (data_dir / "secrets.age").write_bytes(b"age-ciphertext")
    (data_dir / "admin.key").write_bytes(b"age-identity")


class TestBackup:
    def test_backup_captures_the_whole_directory_atomically(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _provisioned_data_dir(data_dir)
        archive = tmp_path / "backup.tar.gz"

        backup(data_dir=str(data_dir), out=str(archive))

        assert archive.is_file()
        # Staged as .tmp and renamed only when complete: no partial file ever
        # carried the final name, and nothing is left behind.
        assert not list(tmp_path.glob("*.tmp"))
        import tarfile

        with tarfile.open(archive, "r:gz") as tar:
            names = set(tar.getnames())
        assert {
            "state.db",
            "secrets.age",
            "admin.key",
            MASTER_KEY_FILENAME,
            STORE_FILENAME,
        } <= names
        out = capsys.readouterr().out
        for known in ("state.db", "secrets.age", "admin.key"):
            assert known in out

    def test_default_output_lands_next_to_the_data_dir(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _provisioned_data_dir(data_dir)

        backup(data_dir=str(data_dir), out="")

        produced = list(tmp_path.glob("conductor-data-*.tar.gz"))
        assert len(produced) == 1
        assert produced[0].stat().st_size > 0

    def test_empty_data_dir_is_refused(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "empty"
        data_dir.mkdir()
        with pytest.raises(typer.Exit) as exc:
            backup(data_dir=str(data_dir), out=str(tmp_path / "a.tar.gz"))
        assert exc.value.exit_code == 2

    def test_missing_data_dir_exits(self, tmp_path: Path) -> None:
        with pytest.raises(typer.Exit) as exc:
            backup(data_dir=str(tmp_path / "nope"), out=str(tmp_path / "a.tar.gz"))
        assert exc.value.exit_code == 2

    def test_existing_archive_is_never_overwritten(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _provisioned_data_dir(data_dir)
        archive = tmp_path / "backup.tar.gz"
        archive.write_bytes(b"previous backup")

        with pytest.raises(typer.Exit) as exc:
            backup(data_dir=str(data_dir), out=str(archive))

        assert exc.value.exit_code == 2
        assert archive.read_bytes() == b"previous backup"


class TestRestore:
    def _roundtrip(self, tmp_path: Path) -> tuple[Path, Path]:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _provisioned_data_dir(data_dir)
        archive = tmp_path / "backup.tar.gz"
        backup(data_dir=str(data_dir), out=str(archive))
        return data_dir, archive

    def test_dry_run_replaces_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data_dir, archive = self._roundtrip(tmp_path)
        before = sorted(p.name for p in data_dir.iterdir())

        restore(data_dir=str(data_dir), from_archive=str(archive), yes=False)

        assert "DRY RUN" in capsys.readouterr().out
        assert sorted(p.name for p in data_dir.iterdir()) == before

    def test_yes_restores_every_coupled_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data_dir, archive = self._roundtrip(tmp_path)
        # A later accident destroys state and the encrypted store.
        (data_dir / "state.db").write_bytes(b"truncated")
        (data_dir / STORE_FILENAME).unlink()

        restore(data_dir=str(data_dir), from_archive=str(archive), yes=True)

        assert (data_dir / "state.db").read_bytes() == b"sqlite-bytes"
        # The restored master key still decrypts the restored store.
        reopened = UserCredentialStore.open(data_dir)
        assert reopened.use_secret("alice", "github", lambda v: v) == "alice-token"
        assert "Restored 5 file(s)" in capsys.readouterr().out

    def test_restored_directory_is_owner_only(self, tmp_path: Path) -> None:
        data_dir, archive = self._roundtrip(tmp_path)
        os.chmod(data_dir, 0o755)

        restore(data_dir=str(data_dir), from_archive=str(archive), yes=True)

        assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700

    def test_crash_before_the_swap_leaves_the_original_in_place(self, tmp_path: Path) -> None:
        data_dir, archive = self._roundtrip(tmp_path)
        before = {p.name: p.read_bytes() for p in data_dir.iterdir()}
        staging = data_dir.parent / f".{data_dir.name}.restore-staging"
        staging.mkdir()
        (staging / "junk").write_bytes(b"leftover from a killed run")

        with pytest.raises(typer.Exit) as exc:
            restore(data_dir=str(data_dir), from_archive=str(archive), yes=True)

        assert exc.value.exit_code == 1
        assert {p.name: p.read_bytes() for p in data_dir.iterdir()} == before

    def test_corrupt_archive_is_refused_before_touching_the_target(self, tmp_path: Path) -> None:
        data_dir, archive = self._roundtrip(tmp_path)
        before = {p.name: p.read_bytes() for p in data_dir.iterdir()}
        archive.write_bytes(b"not a tarball at all")

        with pytest.raises(typer.Exit) as exc:
            restore(data_dir=str(data_dir), from_archive=str(archive), yes=True)

        assert exc.value.exit_code == 1
        assert {p.name: p.read_bytes() for p in data_dir.iterdir()} == before

    def test_truncated_archive_is_refused(self, tmp_path: Path) -> None:
        data_dir, archive = self._roundtrip(tmp_path)
        before = {p.name: p.read_bytes() for p in data_dir.iterdir()}
        raw = archive.read_bytes()
        archive.write_bytes(raw[: len(raw) // 2])

        with pytest.raises(typer.Exit) as exc:
            restore(data_dir=str(data_dir), from_archive=str(archive), yes=True)

        assert exc.value.exit_code == 1
        assert {p.name: p.read_bytes() for p in data_dir.iterdir()} == before

    def test_missing_archive_exits(self, tmp_path: Path) -> None:
        with pytest.raises(typer.Exit) as exc:
            restore(data_dir=str(tmp_path / "data"), from_archive=str(tmp_path / "nope.tar.gz"))
        assert exc.value.exit_code == 2

    def test_unsafe_archive_paths_are_refused(self, tmp_path: Path) -> None:
        import tarfile

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _provisioned_data_dir(data_dir)
        archive = tmp_path / "evil.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            member = tarfile.TarInfo("../../escape")
            payload = b"payload"
            import io

            tar.addfile(member, io.BytesIO(payload))

        with pytest.raises(typer.Exit) as exc:
            restore(data_dir=str(data_dir), from_archive=str(archive), yes=True)

        assert exc.value.exit_code == 2
        assert not (tmp_path / "escape").exists()
        assert (data_dir / "state.db").read_bytes() == b"sqlite-bytes"
