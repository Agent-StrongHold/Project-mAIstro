"""SPEC-010: SQLite Singleton Writer — the invariant that protects state.

These tests define the contract for the state module that all subsystems
must route writes through. All tests should FAIL until the state module
is implemented.
"""

from __future__ import annotations

import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest


def _has_age() -> bool:
    return shutil.which("age") is not None and shutil.which("age-keygen") is not None


age_required = pytest.mark.skipif(not _has_age(), reason="age not installed")


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


class TestSingletonWriter:
    """AC: Exactly one SQLite write-mode connection across conductor lifetime."""

    def test_open_writer_returns_connection(self, db_path: Path) -> None:
        from maistro.state import State

        state = State(db_path=str(db_path))
        conn = state.open_writer()
        assert conn is not None
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        state.close()

    def test_open_writer_raises_on_second_call(self, db_path: Path) -> None:
        from maistro.state import State

        state = State(db_path=str(db_path))
        state.open_writer()
        with pytest.raises(RuntimeError, match=r"open_writer.*once"):
            state.open_writer()
        state.close()

    def test_open_reader_returns_read_only_connection(self, db_path: Path) -> None:
        from maistro.state import State

        state = State(db_path=str(db_path))
        writer = state.open_writer()
        writer.execute("CREATE TABLE test (id INTEGER)")
        writer.commit()

        reader = state.open_reader()
        assert reader.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            reader.execute("INSERT INTO test VALUES (1)")
        state.close()


class TestSubmitQueue:
    """AC: All subsystem writes route through state.submit(transaction)."""

    def test_submit_executes_transaction(self, db_path: Path) -> None:
        from maistro.state import State

        state = State(db_path=str(db_path))
        w = state.open_writer()
        w.execute("CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT)")
        w.commit()

        state.submit(lambda conn: conn.execute("INSERT INTO kv VALUES (?, ?)", ("hello", "world")))
        state.flush()

        row = w.execute("SELECT v FROM kv WHERE k = 'hello'").fetchone()
        assert row is not None
        assert row[0] == "world"
        state.close()

    def test_submit_is_threadsafe(self, db_path: Path) -> None:
        from maistro.state import State

        state = State(db_path=str(db_path))
        w = state.open_writer()
        w.execute("CREATE TABLE counter (id INTEGER PRIMARY KEY, n INTEGER)")
        w.execute("INSERT INTO counter VALUES (1, 0)")
        w.commit()

        def increment(conn: Any) -> None:
            conn.execute("UPDATE counter SET n = n + 1 WHERE id = 1")

        threads = [threading.Thread(target=lambda: state.submit(increment)) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        state.flush()

        row = w.execute("SELECT n FROM counter WHERE id = 1").fetchone()
        assert row[0] == 50
        state.close()

    def test_submit_queue_is_bounded(self, db_path: Path) -> None:
        from maistro.state import State

        state = State(db_path=str(db_path), max_queue_depth=5)
        state.open_writer()

        barrier = threading.Event()

        def blocking_txn(conn: Any) -> None:
            barrier.wait()

        for _ in range(5):
            state.submit(blocking_txn)

        with pytest.raises(Exception, match=r"backpressure|queue.*full"):
            state.submit(blocking_txn)

        barrier.set()
        state.close()


class TestWALAndCheckpoint:
    """AC: WAL checkpoint runs periodically; DB does not grow unboundedly."""

    def test_wal_mode_enabled(self, db_path: Path) -> None:
        from maistro.state import State

        state = State(db_path=str(db_path))
        state.open_writer()

        row = state.open_reader().execute("PRAGMA journal_mode").fetchone()
        assert row[0].lower() == "wal"
        state.close()

    def test_checkpoint_reduces_wal_size(self, db_path: Path) -> None:
        from maistro.state import State

        state = State(db_path=str(db_path))
        w = state.open_writer()
        w.execute("CREATE TABLE big (id INTEGER PRIMARY KEY, data TEXT)")
        w.commit()

        for i in range(1000):
            state.submit(
                lambda conn, i=i: conn.execute(
                    "INSERT INTO big (data) VALUES (?)", (f"data-{i}" * 10,)
                )
            )
        state.flush()

        wal_path = db_path.with_suffix(".db-wal")
        wal_before = wal_path.stat().st_size if wal_path.exists() else 0

        state.checkpoint()

        wal_after = wal_path.stat().st_size if wal_path.exists() else 0
        assert wal_after <= wal_before
        state.close()


@age_required
class TestEncryptedBackups:
    """AC: State DB backups are encrypted with admin keypair before writing to disk."""

    def test_backup_file_is_age_encrypted(self, db_path: Path, tmp_path: Path) -> None:
        import subprocess

        from maistro.state import State

        if not _has_age():
            pytest.skip("age and age-keygen are required for encrypted backup tests")

        state = State(db_path=str(db_path))
        w = state.open_writer()
        w.execute("CREATE TABLE test (id INTEGER)")
        w.execute("INSERT INTO test VALUES (42)")
        w.commit()

        result = subprocess.run(["age-keygen"], capture_output=True, text=True, check=True)
        secret_key = result.stdout.strip()
        public_key = secret_key.split("# public key: ")[1].split("\n")[0]

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        state.backup(
            backup_dir=str(backup_dir),
            admin_public_key=public_key,
        )

        backups = list(backup_dir.glob("*.db.age"))
        assert len(backups) == 1

        raw = backups[0].read_bytes()
        assert raw.startswith(b"age-encryption.org/v1\n")

        key_file = backup_dir / "test.key"
        key_file.write_text(secret_key)

        decrypted = subprocess.run(
            ["age", "-d", "-i", str(key_file), "-o", str(backup_dir / "decrypted.db")],
            input=backups[0].read_bytes(),
            capture_output=True,
        )
        assert decrypted.returncode == 0
        assert (backup_dir / "decrypted.db").exists()
        state.close()

    def test_no_plaintext_backup_written(self, db_path: Path, tmp_path: Path) -> None:
        import subprocess

        from maistro.state import State

        if not _has_age():
            pytest.skip("age and age-keygen are required for encrypted backup tests")

        state = State(db_path=str(db_path))
        state.open_writer()

        result = subprocess.run(["age-keygen"], capture_output=True, text=True, check=True)
        secret_key = result.stdout.strip()
        public_key = secret_key.split("# public key: ")[1].split("\n")[0]

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        state.backup(
            backup_dir=str(backup_dir),
            admin_public_key=public_key,
        )

        assert not list(backup_dir.glob("*.db"))
        assert not list(backup_dir.glob("*.db.bak"))
        state.close()


class TestMigrations:
    """AC: Schema migrations run atomically at startup; failed migration rolls back completely."""

    def test_migration_applies_cleanly(self, db_path: Path) -> None:
        from maistro.state import State

        state = State(db_path=str(db_path))
        state.open_writer()

        tables = (
            state.open_reader()
            .execute("SELECT name FROM sqlite_master WHERE type='table'")
            .fetchall()
        )
        table_names = [t[0] for t in tables]
        assert "schema_migrations" in table_names
        state.close()

    def test_failed_migration_rolls_back(self, db_path: Path) -> None:
        from maistro.state import MigrationFailedError, State

        state = State(db_path=str(db_path))

        with pytest.raises(MigrationFailedError, match="MIGRATION_FAILED"):
            state.run_migration(
                "broken_001",
                up="CREATE TABLE good (id INTEGER); THIS IS BAD SQL;",
            )

        tables = (
            state.open_reader()
            .execute("SELECT name FROM sqlite_master WHERE type='table'")
            .fetchall()
        )
        table_names = [t[0] for t in tables]
        assert "good" not in table_names
        state.close()


class TestConcurrentReads:
    """AC: Concurrent reads work without contention while writer is active."""

    def test_many_concurrent_readers(self, db_path: Path) -> None:
        from maistro.state import State

        state = State(db_path=str(db_path))
        w = state.open_writer()
        w.execute("CREATE TABLE kv (k TEXT, v TEXT)")
        for i in range(100):
            w.execute("INSERT INTO kv VALUES (?, ?)", (f"k{i}", f"v{i}"))
        w.commit()

        results: list[str] = []
        errors: list[Exception] = []

        def reader_fn(idx: int) -> None:
            try:
                r = state.open_reader()
                row = r.execute("SELECT v FROM kv WHERE k = ?", (f"k{idx}",)).fetchone()
                results.append(row[0])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader_fn, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 100
        assert sorted(results) == sorted(f"v{i}" for i in range(100))
        state.close()
