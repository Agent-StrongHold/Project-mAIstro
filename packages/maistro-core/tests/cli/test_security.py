"""Tests for `maistro security` (maistro.cli._security)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from cryptography.fernet import Fernet

from maistro.cli._security import purge_sessions, rotate_credential_key
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
