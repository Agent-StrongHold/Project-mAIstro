"""SPEC-010: SQLite Singleton Writer — the invariant that protects state.

Exactly one write-mode connection across the conductor lifetime. All
subsystem writes route through ``submit()`` which feeds a bounded queue
processed by a dedicated writer thread. Readers open fresh read-only
connections that never contend with the writer.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import shutil
import sqlite3
import subprocess
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from pydantic import BaseModel

T = TypeVar("T", bound="BaseModel")

logger = logging.getLogger(__name__)


class MigrationFailedError(Exception):
    """Raised when a schema migration fails; DB is left unchanged."""


class State:
    """SQLite singleton writer with bounded submit queue."""

    def __init__(
        self,
        db_path: str | Path,
        max_queue_depth: int = 10000,
    ) -> None:
        self._db_path = Path(db_path)
        self._max_queue_depth = max_queue_depth
        self._writer: sqlite3.Connection | None = None
        self._writer_lock = threading.Lock()
        # Serializes the accept/close boundary separately from DB access. A
        # submit that wins this lock is guaranteed to enqueue before close's
        # drain marker; once close wins it, no later submit can be accepted.
        self._lifecycle_lock = threading.Lock()
        self._writer_open = False
        self._tx_queue: queue.Queue[Callable[[sqlite3.Connection], None]] = queue.Queue(
            maxsize=max_queue_depth
        )
        self._writer_thread: threading.Thread | None = None
        self._shutdown = threading.Event()

    def open_writer(self) -> sqlite3.Connection:
        with self._lifecycle_lock:
            if self._writer_open:
                raise RuntimeError("open_writer may be called exactly once")
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT)"
            )
            conn.commit()
            self._writer = conn
            self._writer_open = True

            self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
            self._writer_thread.start()

            return conn

    def open_reader(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True, check_same_thread=False)
        conn.execute("PRAGMA query_only=1")
        return conn

    def submit(self, fn: Callable[[sqlite3.Connection], None]) -> None:
        """Queue a write for the writer thread.

        Raises rather than accepting work there is no thread to perform. Note
        `fn` runs while the writer lock is held, so it must not call back into
        `run_migration()`, `backup()` or `close()` — the lock is not reentrant
        and doing so deadlocks the writer thread permanently. No current caller
        does; `PersistedStore` only issues `conn.execute`.
        """
        with self._lifecycle_lock:
            if not self._writer_open:
                raise RuntimeError(
                    "State writer is not open: call open_writer() first, or this "
                    "State has been closed and can no longer accept writes"
                )
            try:
                self._tx_queue.put_nowait(fn)
            except queue.Full:
                raise RuntimeError(
                    f"backpressure: submit queue full (depth={self._max_queue_depth})"
                ) from None

    def flush(self, timeout: float = 30.0) -> None:
        done = threading.Event()
        self._tx_queue.put(lambda conn: done.set())
        done.wait(timeout=timeout)

    def checkpoint(self) -> None:
        if self._writer is None:
            return
        done = threading.Event()

        def do_checkpoint(conn: sqlite3.Connection) -> None:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            done.set()

        self._tx_queue.put(do_checkpoint)
        done.wait(timeout=10.0)

    def backup(self, backup_dir: str | Path, admin_public_key: str) -> None:
        if self._writer is None:
            raise RuntimeError("open_writer must be called before backup")
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        tmp_plain = backup_dir / f"state-{ts}.db.tmp"

        # Checkpoint and copy under the lock. A background commit landing
        # between the two would put rows into the WAL after it was flushed, so
        # the copied file would be a torn snapshot missing writes that the
        # caller had already been told succeeded.
        with self._writer_lock:
            self._writer.execute("PRAGMA wal_checkpoint(FULL)")
            shutil.copy2(str(self._db_path), str(tmp_plain))

        encrypted_name = f"state-{ts}.db.age"
        encrypted_path = backup_dir / encrypted_name

        try:
            # Invoking the `age` encryption CLI via $PATH is intentional
            # (the binary is the trust root for at-rest encryption). All
            # args are fully controlled by us, not user input: `-r` + admin
            # pubkey, `-o` + dest path, stdin = db bytes.
            subprocess.run(  # nosec — age encryption trust root (B603 + B607)
                ["age", "-r", admin_public_key, "-o", str(encrypted_path)],
                input=tmp_plain.read_bytes(),
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to encrypt backup: {e.stderr.decode(errors='replace')}"
            ) from None
        finally:
            tmp_plain.unlink(missing_ok=True)

    def run_migration(self, name: str, up: str) -> None:
        if self._writer is None:
            self.open_writer()
        assert self._writer is not None

        # The whole savepoint, under the lock. Without it the writer thread can
        # commit a queued transaction on this same connection while we sit
        # between SAVEPOINT and RELEASE — which commits the migration's partial
        # DDL too, so a failed migration leaves a half-applied schema even
        # though MigrationFailedError states the database is unchanged. The
        # existence check is inside the lock as well, so two callers racing the
        # same migration cannot both pass it.
        with self._writer_lock:
            existing = self._writer.execute(
                "SELECT 1 FROM schema_migrations WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                return

            try:
                self._writer.execute("SAVEPOINT migration")
                for stmt in up.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        self._writer.execute(stmt)
                self._writer.execute(
                    "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
                    (name, datetime.now(UTC).isoformat()),
                )
                self._writer.execute("RELEASE migration")
                self._writer.commit()
            except Exception as e:
                self._writer.execute("ROLLBACK TO migration")
                self._writer.execute("RELEASE migration")
                raise MigrationFailedError(f"MIGRATION_FAILED: {name}: {e}") from None

    def close(self, timeout: float = 5.0) -> None:
        """Drain queued writes, then stop the writer thread.

        Close first flips the acceptance gate under `_lifecycle_lock`. Any
        submit accepted before that point is already in the queue, and no
        submit can be accepted after it. The drain marker can therefore safely
        mean "all accepted writes before close are on disk".
        """
        with self._lifecycle_lock:
            self._writer_open = False

        if self._writer_thread is not None:
            drained = threading.Event()
            try:
                self._tx_queue.put(lambda conn: drained.set(), timeout=timeout)
            except queue.Full:
                logger.error("State.close: queue full, cannot drain; writes may be lost")
            else:
                if not drained.wait(timeout=timeout):
                    logger.error(
                        "State.close: drain timed out after %.1fs; %d transaction(s) may be lost",
                        timeout,
                        self._tx_queue.qsize(),
                    )

            self._shutdown.set()
            self._writer_thread.join(timeout=timeout)
            if self._writer_thread.is_alive():
                logger.error("State.close: writer thread did not exit within %.1fs", timeout)
            self._writer_thread = None
        else:
            self._shutdown.set()

        if self._writer is not None:
            # Take the lock: a migration or backup on another thread may still
            # be mid-statement on this same connection. Bounded, unlike the
            # first version: every other wait in this method has a deadline and
            # logs when it expires, and then a bare `with self._writer_lock`
            # could block forever anyway — a shutdown racing a backup (which
            # holds the lock across a full-database copy) would hang the
            # process past all of them.
            if self._writer_lock.acquire(timeout=timeout):
                try:
                    if self._writer is not None:
                        self._writer.close()
                        self._writer = None
                finally:
                    self._writer_lock.release()
            else:
                logger.error(
                    "State.close: could not acquire the writer lock within %.1fs; "
                    "leaving the connection open rather than closing it under another "
                    "thread's statement",
                    timeout,
                )

    def _writer_loop(self) -> None:
        assert self._writer is not None
        while not self._shutdown.is_set():
            try:
                fn = self._tx_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            # `check_same_thread=False` means this thread and any caller of
            # run_migration()/backup() share one connection. Committing here
            # while run_migration is between SAVEPOINT and RELEASE would commit
            # the migration's partial work — leaving a half-applied schema
            # despite MigrationFailedError promising the database is unchanged.
            # `_writer_lock` existed for exactly this and was never acquired
            # anywhere in the file.
            with self._writer_lock:
                if self._writer is None:  # closed underneath us
                    return
                try:
                    fn(self._writer)
                    self._writer.commit()
                except Exception:
                    logger.exception("State transaction failed")
                    with contextlib.suppress(Exception):
                        self._writer.rollback()


_KV_MIGRATION = (
    "CREATE TABLE IF NOT EXISTS kv_store "
    "(store_name TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
    "updated_at TEXT NOT NULL, PRIMARY KEY (store_name, key))"
)


class PersistedStore:
    """Dict-like persistence for Pydantic models over SQLite via State.

    Each logical "store" is a namespace within a single ``kv_store`` table.
    Values are JSON-serialized Pydantic model instances. Writes route through
    ``State.submit()``; reads use ``State.open_reader()``.
    """

    def __init__(self, state: State) -> None:
        self._state = state

    def initialize(self) -> None:
        if not self._state._writer_open:
            self._state.open_writer()
        self._state.run_migration("kv_store_001", _KV_MIGRATION)

    def put(self, store_name: str, key: str, model: BaseModel) -> None:
        data = model.model_dump_json()
        now = datetime.now(UTC).isoformat()

        def _upsert(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO kv_store (store_name, key, value, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(store_name, key) DO UPDATE "
                "SET value = excluded.value, updated_at = excluded.updated_at",
                (store_name, key, data, now),
            )

        self._state.submit(_upsert)

    def get(self, store_name: str, key: str, model_class: type[T]) -> T | None:
        reader = self._state.open_reader()
        try:
            row = reader.execute(
                "SELECT value FROM kv_store WHERE store_name = ? AND key = ?",
                (store_name, key),
            ).fetchone()
        finally:
            reader.close()
        if row is None:
            return None
        return model_class.model_validate_json(row[0])

    def delete(self, store_name: str, key: str) -> None:
        def _delete(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM kv_store WHERE store_name = ? AND key = ?",
                (store_name, key),
            )

        self._state.submit(_delete)

    def contains(self, store_name: str, key: str) -> bool:
        reader = self._state.open_reader()
        try:
            row = reader.execute(
                "SELECT 1 FROM kv_store WHERE store_name = ? AND key = ?",
                (store_name, key),
            ).fetchone()
        finally:
            reader.close()
        return row is not None

    def list_all(self, store_name: str, model_class: type[T]) -> list[T]:
        reader = self._state.open_reader()
        try:
            rows = reader.execute(
                "SELECT value FROM kv_store WHERE store_name = ?",
                (store_name,),
            ).fetchall()
        finally:
            reader.close()
        return [model_class.model_validate_json(row[0]) for row in rows]

    def put_raw(self, store_name: str, key: str, json_str: str) -> None:
        now = datetime.now(UTC).isoformat()

        def _upsert(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO kv_store (store_name, key, value, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(store_name, key) DO UPDATE "
                "SET value = excluded.value, updated_at = excluded.updated_at",
                (store_name, key, json_str, now),
            )

        self._state.submit(_upsert)

    def get_raw(self, store_name: str, key: str) -> str | None:
        reader = self._state.open_reader()
        try:
            row = reader.execute(
                "SELECT value FROM kv_store WHERE store_name = ? AND key = ?",
                (store_name, key),
            ).fetchone()
        finally:
            reader.close()
        return row[0] if row is not None else None

    def list_all_raw(self, store_name: str) -> list[tuple[str, str]]:
        reader = self._state.open_reader()
        try:
            rows = reader.execute(
                "SELECT key, value FROM kv_store WHERE store_name = ?",
                (store_name,),
            ).fetchall()
        finally:
            reader.close()
        return [(row[0], row[1]) for row in rows]
