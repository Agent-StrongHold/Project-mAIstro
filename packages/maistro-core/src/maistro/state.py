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
import random
import shutil
import sqlite3
import subprocess
import threading
import time
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


class _Tx:
    """A queued transaction plus its completion signal.

    The writer thread sets `done` once it has finished with the item —
    committed, failed, or skipped because the connection vanished — and
    records the failure, if any, in `error`. Fire-and-forget submitters
    ignore both; acknowledged submitters (#1238) wait on `done` and re-raise
    `error`, so a caller cannot treat a write the database refused as if it
    had landed.
    """

    __slots__ = ("done", "error", "fn")

    def __init__(self, fn: Callable[[sqlite3.Connection], None]) -> None:
        self.fn = fn
        self.done = threading.Event()
        self.error: BaseException | None = None


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
        self._tx_queue: queue.Queue[_Tx] = queue.Queue(maxsize=max_queue_depth)
        self._writer_thread: threading.Thread | None = None
        self._shutdown = threading.Event()

    @staticmethod
    def _retry_on_locked(fn: Callable[[], object], *, attempts: int = 5) -> None:
        """Retry `fn` a bounded number of times on a transient sqlite3
        "database is locked" error, with a short jittered backoff.

        `busy_timeout` covers ordinary write-lock contention, but SQLite's
        first-time WAL-file creation handshake between two processes opening
        the same brand-new database together is not reliably covered by it.
        Anything other than "locked" is a real failure and is not retried.
        """
        for attempt in range(attempts):
            try:
                fn()
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == attempts - 1:
                    raise
                time.sleep(0.05 * (attempt + 1) + random.uniform(0, 0.05))  # nosec B311

    def open_writer(self) -> sqlite3.Connection:
        with self._lifecycle_lock:
            if self._writer_open:
                raise RuntimeError("open_writer may be called exactly once")
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            # Before anything else: cross-process writers (e.g. two Hive
            # processes starting for the first time against a freshly-upgraded
            # DB, #1528) otherwise get an immediate "database is locked" the
            # instant one of them holds the write lock, instead of a bounded
            # wait for it to be released.
            conn.execute("PRAGMA busy_timeout = 5000")
            # The journal-mode switch itself is the one statement observed to
            # still raise "database is locked" immediately, even with
            # busy_timeout set, when two processes open the same brand-new
            # file for the first time together: SQLite's own WAL-file-creation
            # handshake is not always covered by the ordinary busy handler.
            # Retry it a bounded number of times rather than let a first-boot
            # coincidence fail the whole process (#1528).
            self._retry_on_locked(lambda: conn.execute("PRAGMA journal_mode=WAL"))
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

    def _enqueue(self, tx: _Tx) -> None:
        """Accept a transaction for the writer thread, or refuse.

        Raises rather than accepting work there is no thread to perform. Note
        `fn` runs while the writer lock is held, so it must not call back into
        `run_migration()`, `backup()` or `close()` — the lock is not reentrant
        and doing so deadlocks the writer thread permanently. PersistedStore
        callbacks issue SQL (and the synchronous insert-if-absent commits) on
        the supplied connection without calling back into State.
        """
        with self._lifecycle_lock:
            if not self._writer_open:
                raise RuntimeError(
                    "State writer is not open: call open_writer() first, or this "
                    "State has been closed and can no longer accept writes"
                )
            try:
                self._tx_queue.put_nowait(tx)
            except queue.Full:
                raise RuntimeError(
                    f"backpressure: submit queue full (depth={self._max_queue_depth})"
                ) from None

    def submit(self, fn: Callable[[sqlite3.Connection], None]) -> None:
        """Queue a write for the writer thread without waiting for it.

        Fire-and-forget: a failure inside `fn` or in the commit is logged and
        rolled back by the writer thread, never re-raised here. Callers that
        must know the write reached disk (#1238) use `submit_sync` — or the
        PersistedStore put/delete/put_raw built on it. Same refusal semantics
        as `submit_sync` for a closed writer or a full queue.
        """
        self._enqueue(_Tx(fn))

    def submit_sync(
        self, fn: Callable[[sqlite3.Connection], None], *, timeout: float = 30.0
    ) -> None:
        """Queue a write and block until the writer thread has committed it.

        #1238: a failure inside `fn` or in the commit itself is re-raised
        here, so the caller learns the mutation did not reach disk instead of
        acknowledging it and watching it silently disappear (or a deleted
        record resurrect) after restart. Raises the writer's exception
        directly; TimeoutError if `fn` did not finish within `timeout` (the
        write may still land afterwards); RuntimeError for the same
        closed-writer and backpressure conditions as `submit`.
        """
        tx = _Tx(fn)
        self._enqueue(tx)
        if not tx.done.wait(timeout=timeout):
            raise TimeoutError(
                f"timed out after {timeout:.1f}s waiting for the state writer to commit"
            )
        if tx.error is not None:
            raise tx.error

    def flush(self, timeout: float = 30.0) -> None:
        """Barrier: wait until every write submitted before this call has been
        processed — committed or failed. flush does not surface writer errors
        (#1238); acknowledged writes should use `submit_sync`.
        """
        tx = _Tx(lambda _conn: None)
        self._tx_queue.put(tx)
        tx.done.wait(timeout=timeout)

    def checkpoint(self) -> None:
        if self._writer is None:
            return

        def do_checkpoint(conn: sqlite3.Connection) -> None:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        tx = _Tx(do_checkpoint)
        self._tx_queue.put(tx)
        tx.done.wait(timeout=10.0)

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
        #
        # `_writer_lock` is process-local, though (a plain `threading.Lock`),
        # so it only serializes callers inside this process. Two independent
        # processes can both pass the existence check above before either has
        # committed — each has its own `State`/connection — and then race the
        # same DDL (#1528). Whichever loses fails either on SQLite's own
        # cross-process write lock (if it arrives while the winner still holds
        # it — `busy_timeout` above bounds that wait instead of raising
        # immediately) or on the `schema_migrations.name` PRIMARY KEY once the
        # winner has committed. Every statement in a migration's `up` is
        # required to be idempotent (`IF NOT EXISTS` / `OR IGNORE`) precisely
        # so that losing this race is harmless: after rolling back our own
        # attempt, re-check whether the name is now present. If it is, the
        # winner's identical DDL already applied, so this loss is a no-op —
        # proceed instead of failing this process's startup.
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
                winner = self._writer.execute(
                    "SELECT 1 FROM schema_migrations WHERE name = ?", (name,)
                ).fetchone()
                if winner:
                    logger.info(
                        "migration %r lost a cross-process race but is already "
                        "applied by the winner; proceeding (%s)",
                        name,
                        e,
                    )
                    return
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
            drain = _Tx(lambda _conn: None)
            try:
                self._tx_queue.put(drain, timeout=timeout)
            except queue.Full:
                logger.error("State.close: queue full, cannot drain; writes may be lost")
            else:
                if not drain.done.wait(timeout=timeout):
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
                tx = self._tx_queue.get(timeout=0.1)
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
                    tx.error = RuntimeError("State writer closed before this transaction could run")
                    tx.done.set()
                    return
                try:
                    tx.fn(self._writer)
                    self._writer.commit()
                except Exception as exc:
                    logger.exception("State transaction failed")
                    with contextlib.suppress(Exception):
                        self._writer.rollback()
                    tx.error = exc
                finally:
                    tx.done.set()


_KV_MIGRATION = (
    "CREATE TABLE IF NOT EXISTS kv_store "
    "(store_name TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
    "updated_at TEXT NOT NULL, PRIMARY KEY (store_name, key))"
)

# A durable uniqueness boundary for model fields. The KV row remains the
# canonical record; this table only makes a uniqueness claim transactional.
_UNIQUE_FIELDS_MIGRATION = (
    "CREATE TABLE IF NOT EXISTS unique_fields "
    "(store_name TEXT NOT NULL, field_name TEXT NOT NULL, "
    "normalized_value TEXT NOT NULL, record_key TEXT NOT NULL, "
    "PRIMARY KEY (store_name, field_name, normalized_value));"
    "CREATE UNIQUE INDEX IF NOT EXISTS unique_fields_record "
    "ON unique_fields (store_name, field_name, record_key);"
    "INSERT OR IGNORE INTO unique_fields "
    "(store_name, field_name, normalized_value, record_key) "
    "SELECT 'users', 'username', lower(json_extract(value, '$.username')), key "
    "FROM kv_store WHERE store_name = 'users' "
    "AND json_extract(value, '$.username') IS NOT NULL"
)

# A genuine SQL-level uniqueness boundary on the row every writer actually
# inserts into, old code path or new (#1528 Codex review finding 4).
# `unique_fields` above only stops a writer that knows to consult it; during
# a rolling upgrade, a still-running pre-#1248 process registers users
# through the generic `PersistedStore.put()` path, which writes straight to
# `kv_store` and has never heard of `unique_fields`. A new-version process
# checking only `unique_fields` for availability cannot see that write and
# can claim + insert a second row for the same username. This index lives on
# `kv_store` itself, so it applies to that write too, regardless of which
# code version made it.
#
# `lower(...)` matches the case-insensitive comparison `unique_fields` and
# `ModelStore` already use. The partial WHERE keeps every other store's rows,
# and `users` rows before a username exists, out of the index entirely.
_KV_USERS_USERNAME_UNIQUE_MIGRATION = (
    "CREATE UNIQUE INDEX IF NOT EXISTS kv_store_users_username_unique "
    "ON kv_store (lower(json_extract(value, '$.username'))) "
    "WHERE store_name = 'users' AND json_extract(value, '$.username') IS NOT NULL"
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
        self._state.run_migration("kv_unique_fields_001", _UNIQUE_FIELDS_MIGRATION)
        self._warn_about_unclaimed_duplicate_usernames()
        self._enforce_username_uniqueness_at_db_boundary()

    def _warn_about_unclaimed_duplicate_usernames(self) -> None:
        """Surface pre-existing duplicate usernames the backfill couldn't claim.

        `kv_unique_fields_001`'s `INSERT OR IGNORE` claims a `unique_fields`
        row for only the first `users` record it sees per normalized
        username; every other pre-existing record sharing that username (only
        possible from before this PR, since `put_model_unique` prevents new
        ones) is left active in `kv_store` with no claim of its own (#1528
        Codex review finding 2). A later update or password rehash of one of
        those records goes through `put_model_unique`, finds the claim owned
        by a different key, and fails — and login may still resolve
        nondeterministically to either duplicate identity until an operator
        picks a winner (rename or remove the loser). This is read-only and
        runs on every `initialize()`, not just when the migration first
        applies, so the warning does not go away on its own — only resolving
        the duplicates does.
        """
        reader = self._state.open_reader()
        try:
            rows = reader.execute(
                "SELECT k.key, json_extract(k.value, '$.username') "
                "FROM kv_store k "
                "WHERE k.store_name = 'users' "
                "AND json_extract(k.value, '$.username') IS NOT NULL "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM unique_fields u "
                "  WHERE u.store_name = 'users' AND u.field_name = 'username' "
                "  AND u.record_key = k.key"
                ")"
            ).fetchall()
        finally:
            reader.close()
        if rows:
            logger.warning(
                "%d 'users' record(s) hold a duplicate username with no durable "
                "uniqueness claim (pre-existing data from before this fix); "
                "username uniqueness is not enforced for these records and login "
                "may resolve to either one. Resolve manually (rename or remove "
                "the duplicate) — affected record keys: %s",
                len(rows),
                [row[0] for row in rows],
            )

    def _enforce_username_uniqueness_at_db_boundary(self) -> None:
        """Best-effort: apply the DB-level index that closes the
        mixed-version-writer gap (#1528 Codex review finding 4).

        SQLite refuses to create a UNIQUE index over data that already
        violates it — exactly the case where legacy duplicate usernames are
        still present (see `_warn_about_unclaimed_duplicate_usernames`
        above). Best-effort rather than fatal: an operator who has not yet
        resolved those duplicates should still be able to start the hive
        with the weaker, application-level-only enforcement it already had,
        not be locked out entirely by a stricter guarantee this PR adds. The
        migration is retried on every `initialize()` and will succeed,
        silently closing the gap, the moment the duplicates are gone.
        """
        try:
            self._state.run_migration(
                "kv_users_username_unique_001", _KV_USERS_USERNAME_UNIQUE_MIGRATION
            )
        except MigrationFailedError as exc:
            logger.warning(
                "could not create the database-level username-uniqueness index "
                "(likely the legacy duplicate usernames reported above); "
                "username uniqueness is enforced only at the application level "
                "until those are resolved and the hive is restarted: %s",
                exc,
            )

    def put(self, store_name: str, key: str, model: BaseModel) -> None:
        """Upsert `model`, blocking until the writer commits it (#1238).

        A failed statement or commit raises to the caller — a Hive mutation is
        acknowledged only once it is durable, never silently dropped while the
        in-memory copy moves on.
        """
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

        self._state.submit_sync(_upsert)

    def put_model_unique(
        self,
        store_name: str,
        key: str,
        model: BaseModel,
        unique_fields: tuple[str, ...],
    ) -> bool:
        """Upsert a model while preserving its durable uniqueness claims.

        Existing records may be updated under the same key, but a claim held
        by another record rejects the whole transaction. This keeps ordinary
        user updates from losing the username claim created at registration.
        """
        data = model.model_dump_json()
        now = datetime.now(UTC).isoformat()
        completed = threading.Event()
        inserted: list[bool] = []
        errors: list[Exception] = []

        def _upsert(conn: sqlite3.Connection) -> None:
            try:
                for field_name in unique_fields:
                    value = str(getattr(model, field_name)).casefold()
                    existing = conn.execute(
                        "SELECT record_key FROM unique_fields "
                        "WHERE store_name = ? AND field_name = ? AND normalized_value = ?",
                        (store_name, field_name, value),
                    ).fetchone()
                    if existing is not None and existing[0] != key:
                        inserted.append(False)
                        return
                conn.execute(
                    "DELETE FROM unique_fields WHERE store_name = ? AND record_key = ?",
                    (store_name, key),
                )
                for field_name in unique_fields:
                    value = str(getattr(model, field_name)).casefold()
                    conn.execute(
                        "INSERT INTO unique_fields "
                        "(store_name, field_name, normalized_value, record_key) "
                        "VALUES (?, ?, ?, ?)",
                        (store_name, field_name, value, key),
                    )
                conn.execute(
                    "INSERT INTO kv_store (store_name, key, value, updated_at) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(store_name, key) DO UPDATE "
                    "SET value = excluded.value, updated_at = excluded.updated_at",
                    (store_name, key, data, now),
                )
                conn.commit()
                inserted.append(True)
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.rollback()
                errors.append(exc)
            finally:
                completed.set()

        self._state.submit(_upsert)
        if not completed.wait(timeout=30.0):
            raise TimeoutError("timed out waiting for unique model write")
        if errors:
            raise RuntimeError("unique model write failed") from errors[0]
        return inserted == [True]

    def put_model_if_unique(
        self,
        store_name: str,
        key: str,
        model: BaseModel,
        field_name: str,
    ) -> bool:
        """Insert a model only if its field claim is still available.

        The claim and model row commit together, so two independent process
        writers cannot both publish UUID-keyed records for one field value.
        """
        data = model.model_dump_json()
        now = datetime.now(UTC).isoformat()
        value = str(getattr(model, field_name)).casefold()
        completed = threading.Event()
        inserted: list[bool] = []
        errors: list[Exception] = []

        def _insert_once(conn: sqlite3.Connection) -> None:
            try:
                cursor = conn.execute(
                    "INSERT INTO unique_fields "
                    "(store_name, field_name, normalized_value, record_key) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                    (store_name, field_name, value, key),
                )
                if cursor.rowcount != 1:
                    inserted.append(False)
                    return
                conn.execute(
                    "INSERT INTO kv_store (store_name, key, value, updated_at) VALUES (?, ?, ?, ?)",
                    (store_name, key, data, now),
                )
                conn.commit()
                inserted.append(True)
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.rollback()
                errors.append(exc)
            finally:
                completed.set()

        self._state.submit(_insert_once)
        if not completed.wait(timeout=30.0):
            raise TimeoutError("timed out waiting for unique model insert")
        if errors:
            raise RuntimeError("unique model insert failed") from errors[0]
        return inserted == [True]

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
        """Remove `key`, blocking until the writer commits it (#1238).

        A failed delete raises to the caller instead of leaving the row on
        disk to resurrect the record after restart.
        """

        def _delete(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM unique_fields WHERE store_name = ? AND record_key = ?",
                (store_name, key),
            )
            conn.execute(
                "DELETE FROM kv_store WHERE store_name = ? AND key = ?",
                (store_name, key),
            )

        self._state.submit_sync(_delete)

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
        """Upsert a raw JSON string, blocking until the writer commits it (#1238)."""
        now = datetime.now(UTC).isoformat()

        def _upsert(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO kv_store (store_name, key, value, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(store_name, key) DO UPDATE "
                "SET value = excluded.value, updated_at = excluded.updated_at",
                (store_name, key, json_str, now),
            )

        self._state.submit_sync(_upsert)

    def put_raw_if_absent(
        self,
        store_name: str,
        key: str,
        json_str: str,
        *,
        timeout: float = 30.0,
    ) -> bool:
        """Atomically insert a raw value without overwriting an existing key."""
        now = datetime.now(UTC).isoformat()
        completed = threading.Event()
        inserted: list[bool] = []
        errors: list[Exception] = []

        def _insert_once(conn: sqlite3.Connection) -> None:
            try:
                # SECURITY-REVIEW: Identity-link callers rely on the primary
                # key conflict being decided by SQLite, not a process-local
                # read followed by an overwriting upsert.
                cursor = conn.execute(
                    "INSERT INTO kv_store (store_name, key, value, updated_at) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(store_name, key) DO NOTHING",
                    (store_name, key, json_str, now),
                )
                conn.commit()
                inserted.append(cursor.rowcount == 1)
            except Exception as exc:
                with contextlib.suppress(Exception):
                    conn.rollback()
                errors.append(exc)
            finally:
                completed.set()

        self._state.submit(_insert_once)
        if not completed.wait(timeout=timeout):
            raise TimeoutError("timed out waiting for conflict-safe state insert")
        if errors:
            raise RuntimeError("conflict-safe state insert failed") from errors[0]
        return inserted == [True]

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
