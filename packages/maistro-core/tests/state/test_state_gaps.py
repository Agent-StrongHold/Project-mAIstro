"""Gap-filling coverage for State/PersistedStore not exercised by
test_state.py: submit/checkpoint/backup no-writer guards, run_migration's
already-applied skip and auto-open-writer branches, close()'s no-thread/
no-writer guards, and the entire PersistedStore class (initialize, put,
get, delete, contains, list_all, put_raw, get_raw, list_all_raw)."""

from __future__ import annotations

import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from pydantic import BaseModel

from maistro.state import MigrationFailedError, PersistedStore, State


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


class Widget(BaseModel):
    name: str
    count: int


class TestSubmitGuard:
    def test_submit_before_open_writer_raises(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        # Message widened when close() started refusing writes too — it now has
        # to name both reasons the writer can be unavailable.
        with pytest.raises(RuntimeError, match="call open_writer"):
            state.submit(lambda conn: None)


class TestCheckpointGuard:
    def test_checkpoint_without_writer_is_noop(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        state.checkpoint()

        assert state._writer is None
        assert not db_path.exists()


class TestBackupGuard:
    def test_backup_without_writer_raises(self, db_path: Path, tmp_path: Path) -> None:
        state = State(db_path=str(db_path))
        with pytest.raises(RuntimeError, match="open_writer must be called before backup"):
            state.backup(backup_dir=str(tmp_path / "backups"), admin_public_key="age1xxx")

    def test_backup_encryption_failure_raises_runtime_error(
        self, db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = State(db_path=str(db_path))
        state.open_writer()

        def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            raise subprocess.CalledProcessError(1, ["age"], stderr=b"boom")

        monkeypatch.setattr(subprocess, "run", fake_run)

        backup_dir = tmp_path / "backups"
        with pytest.raises(RuntimeError, match="Failed to encrypt backup"):
            state.backup(backup_dir=str(backup_dir), admin_public_key="age1xxx")

        assert not list(backup_dir.glob("*.db.tmp"))
        state.close()


class TestWriterLoop:
    def test_idle_loop_hits_queue_empty_continue(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        state.open_writer()
        time.sleep(0.3)  # let the writer thread idle-poll past its 0.1s timeout
        assert state._writer_thread is not None
        assert state._writer_thread.is_alive()
        state.close()

    def test_transaction_exception_is_caught_and_rolled_back(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        w = state.open_writer()
        w.execute("CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT)")
        w.commit()

        def boom(conn: sqlite3.Connection) -> None:
            conn.execute("INSERT INTO kv (k, v) VALUES ('failed', 'value')")
            raise ValueError("transaction failed")

        state.submit(boom)
        state.flush(timeout=2.0)
        assert w.execute("SELECT * FROM kv WHERE k = 'failed'").fetchone() is None
        state.close()


class TestRunMigrationBranches:
    def test_skips_when_already_applied(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        state.run_migration("m1", up="CREATE TABLE foo (id INTEGER)")
        # second call with a deliberately broken statement must be skipped,
        # not executed, since the migration name is already recorded
        state.run_migration("m1", up="THIS IS BAD SQL")
        assert state._writer is not None
        assert state._writer.execute("SELECT name FROM schema_migrations").fetchall() == [("m1",)]
        assert state._writer.execute("SELECT name FROM sqlite_master WHERE name = 'foo'").fetchone()
        state.close()

    def test_auto_opens_writer_when_not_open(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        assert state._writer is None
        state.run_migration("m2", up="CREATE TABLE bar (id INTEGER)")
        assert state._writer is not None
        state.close()

    def test_migration_failure_raises_migration_failed_error(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        with pytest.raises(MigrationFailedError, match="MIGRATION_FAILED: bad_one"):
            state.run_migration("bad_one", up="NOT VALID SQL AT ALL")
        state.close()


class TestClose:
    def test_close_without_open_writer_is_noop(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        state.close()

        assert state._writer is None
        assert state._writer_open is False
        assert state._shutdown.is_set()

    def test_close_after_open_writer_closes_connection(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        state.open_writer()
        state.close()
        assert state._writer is None


class TestPersistedStore:
    def test_initialize_opens_writer_when_not_open(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        assert not state._writer_open
        store.initialize()
        assert state._writer_open
        state.close()

    def test_initialize_skips_open_writer_when_already_open(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        state.open_writer()
        store = PersistedStore(state)
        store.initialize()

        assert state._writer is not None
        assert state._writer.execute("SELECT name FROM schema_migrations").fetchall() == [
            ("kv_store_001",)
        ]
        state.close()

    def test_put_and_get_roundtrip(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()

        store.put("widgets", "w1", Widget(name="gadget", count=3))
        state.flush()

        result = store.get("widgets", "w1", Widget)
        assert result == Widget(name="gadget", count=3)
        state.close()

    def test_get_missing_key_returns_none(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()

        assert store.get("widgets", "nope", Widget) is None
        state.close()

    def test_put_overwrites_existing_key(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()

        store.put("widgets", "w1", Widget(name="gadget", count=3))
        store.put("widgets", "w1", Widget(name="gadget", count=9))
        state.flush()

        assert store.get("widgets", "w1", Widget) == Widget(name="gadget", count=9)
        state.close()

    def test_delete_removes_key(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()

        store.put("widgets", "w1", Widget(name="gadget", count=3))
        state.flush()
        store.delete("widgets", "w1")
        state.flush()

        assert store.get("widgets", "w1", Widget) is None
        state.close()

    def test_contains_true_and_false(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()

        store.put("widgets", "w1", Widget(name="gadget", count=3))
        state.flush()

        assert store.contains("widgets", "w1") is True
        assert store.contains("widgets", "nope") is False
        state.close()

    def test_list_all_returns_all_models_in_store(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()

        store.put("widgets", "w1", Widget(name="a", count=1))
        store.put("widgets", "w2", Widget(name="b", count=2))
        store.put("others", "o1", Widget(name="c", count=3))
        state.flush()

        result = store.list_all("widgets", Widget)
        assert sorted(result, key=lambda w: w.name) == [
            Widget(name="a", count=1),
            Widget(name="b", count=2),
        ]
        state.close()

    def test_put_raw_and_get_raw_roundtrip(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()

        store.put_raw("raws", "r1", '{"x": 1}')
        state.flush()

        assert store.get_raw("raws", "r1") == '{"x": 1}'
        state.close()

    def test_get_raw_missing_key_returns_none(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()

        assert store.get_raw("raws", "nope") is None
        state.close()

    def test_list_all_raw_returns_key_value_pairs(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()

        store.put_raw("raws", "r1", '{"x": 1}')
        store.put_raw("raws", "r2", '{"x": 2}')
        state.flush()

        result = store.list_all_raw("raws")
        assert sorted(result) == [("r1", '{"x": 1}'), ("r2", '{"x": 2}')]
        state.close()
