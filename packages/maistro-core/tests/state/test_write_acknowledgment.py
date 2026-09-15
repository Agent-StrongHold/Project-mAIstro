"""#1238 regression: the writer thread must report transaction outcomes.

`State._writer_loop` used to catch every exception after a write had already
been accepted — log it, roll back, move on — and `submit` had no way to wait
for an outcome at all. A caller (Hive's ModelStore/JsonStore, the settings/
profile/registration record stores) could therefore acknowledge a mutation
whose commit had failed: the mutation silently disappeared after restart, or
a "deleted" record resurrected. These tests pin the acknowledged-write
contract — `State.submit_sync`, and the PersistedStore put/delete/put_raw
built on it, re-raise the writer's failure — while fire-and-forget `submit`
keeps its non-raising, rollback-on-error contract.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from maistro.state import PersistedStore, State


class Widget(BaseModel):
    name: str


class _CommitFailingConnection:
    """Delegates to a real connection; ``commit()`` always fails.

    Isolates exactly the reported failure mode: ``fn`` succeeds and the COMMIT
    is what breaks — pre-#1238 that outcome was indistinguishable from success
    to every submitter.
    """

    def __init__(self, real: sqlite3.Connection) -> None:
        self._real = real

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        return self._real.execute(sql, *args, **kwargs)

    def rollback(self) -> None:
        self._real.rollback()

    def commit(self) -> None:
        raise sqlite3.OperationalError("simulated commit failure")


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "state.db"


@pytest.fixture()
def state(db_path: Path):
    state = State(db_path=str(db_path))
    state.open_writer()
    yield state
    state.close()


def _row_count(state: State, table: str = "t") -> int:
    reader = state.open_reader()
    try:
        row = reader.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    finally:
        reader.close()
    return int(row[0])


def _swap_commit_failing_writer(state: State) -> tuple[sqlite3.Connection, Callable[[], None]]:
    """Point the writer loop at a connection whose commit always fails.

    Returns the real connection and a restore callable (use in a finally:
    close() would otherwise call commit-again on the proxy and mask the
    failure under test with an AttributeError).
    """
    real = state._writer
    assert real is not None
    state._writer = _CommitFailingConnection(real)
    return real, lambda: setattr(state, "_writer", real)


class TestSubmitSyncAcknowledgment:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    def test_ack_means_committed(self, db_path: Path) -> None:
        """A completed acknowledged write is on disk: no flush() required."""
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()
        store.put("items", "k1", Widget(name="durable"))
        state.close()

        reopened = State(db_path=str(db_path))
        try:
            reopened_store = PersistedStore(reopened)
            reopened_store.initialize()
            assert reopened_store.get("items", "k1", Widget) == Widget(name="durable")
        finally:
            reopened.close()

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    def test_commit_failure_raises_to_submitter(self, state: State) -> None:
        """The reported failure mode: fn succeeds, COMMIT fails, submitter knows."""
        state.run_migration("kv", "CREATE TABLE IF NOT EXISTS t (k TEXT PRIMARY KEY, v TEXT)")
        _real, restore = _swap_commit_failing_writer(state)
        try:
            with pytest.raises(sqlite3.OperationalError, match="simulated commit failure"):
                state.submit_sync(
                    lambda conn: conn.execute("INSERT INTO t VALUES ('k', 'v')"), timeout=5.0
                )
        finally:
            restore()

        # The failed transaction was rolled back...
        assert _row_count(state) == 0
        # ...and the writer loop survived to commit the next acknowledged write.
        state.submit_sync(lambda conn: conn.execute("INSERT INTO t VALUES ('k2', 'v2')"))
        assert _row_count(state) == 1

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    def test_fn_failure_raises_and_rolls_back(self, state: State) -> None:
        state.run_migration("kv", "CREATE TABLE IF NOT EXISTS t (k TEXT PRIMARY KEY, v TEXT)")

        def boom(conn: sqlite3.Connection) -> None:
            conn.execute("INSERT INTO t VALUES ('partial', 'leftover')")
            raise ValueError("transaction failed")

        with pytest.raises(ValueError, match="transaction failed"):
            state.submit_sync(boom, timeout=5.0)

        assert _row_count(state) == 0
        state.submit_sync(lambda conn: conn.execute("INSERT INTO t VALUES ('ok', 'x')"))
        assert _row_count(state) == 1

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    def test_timeout_when_writer_is_stuck(self, state: State) -> None:
        release = threading.Event()
        started = threading.Event()

        def stall(conn: sqlite3.Connection) -> None:
            started.set()
            release.wait(timeout=10.0)

        state.submit(stall)
        assert started.wait(timeout=5.0)

        with pytest.raises(TimeoutError, match="timed out"):
            state.submit_sync(lambda conn: None, timeout=0.05)

        release.set()
        # The queue drains in order, so a later acknowledged write succeeds.
        state.submit_sync(lambda conn: None, timeout=5.0)

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    def test_fire_and_forget_submit_still_does_not_raise(self, state: State) -> None:
        """submit() keeps its contract: never raises for writer failures."""
        state.run_migration("kv", "CREATE TABLE IF NOT EXISTS t (k TEXT PRIMARY KEY, v TEXT)")

        def boom(conn: sqlite3.Connection) -> None:
            conn.execute("INSERT INTO t VALUES ('failed', 'value')")
            raise ValueError("transaction failed")

        state.submit(boom)
        state.flush(timeout=5.0)

        assert _row_count(state) == 0

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    def test_submit_sync_after_close_refuses(self, db_path: Path) -> None:
        state = State(db_path=str(db_path))
        state.open_writer()
        state.close()

        with pytest.raises(RuntimeError, match="open_writer"):
            state.submit_sync(lambda conn: None)


class TestPersistedStoreAcknowledgedWrites:
    def _commit_failing_store(
        self, db_path: Path
    ) -> tuple[State, PersistedStore, Callable[[], None]]:
        """A PersistedStore whose writer accepts statements but never commits."""
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()
        store.put("items", "keep", Widget(name="earlier"))
        _, restore = _swap_commit_failing_writer(state)
        return state, store, restore

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    def test_put_raises_instead_of_losing_the_mutation(self, tmp_path: Path) -> None:
        """Regression for the disappearing-mutation half of #1238."""
        db_path = tmp_path / "state.db"
        state, store, restore = self._commit_failing_store(db_path)
        try:
            with pytest.raises(sqlite3.OperationalError, match="simulated commit failure"):
                store.put("items", "k1", Widget(name="vanishing"))
        finally:
            restore()
        state.close()

        # After restart the write the caller saw fail is absent and the prior
        # record is intact. Pre-#1238 `put` returned normally here while the
        # row never landed: the mutation silently disappeared on restart.
        reopened = State(db_path=str(db_path))
        try:
            reopened_store = PersistedStore(reopened)
            reopened_store.initialize()
            assert reopened_store.get("items", "k1", Widget) is None
            assert reopened_store.get("items", "keep", Widget) == Widget(name="earlier")
        finally:
            reopened.close()

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    def test_delete_raises_instead_of_resurrecting_the_record(self, tmp_path: Path) -> None:
        """Regression for the resurrection half of #1238."""
        db_path = tmp_path / "state.db"
        state, store, restore = self._commit_failing_store(db_path)
        try:
            with pytest.raises(sqlite3.OperationalError, match="simulated commit failure"):
                store.delete("items", "keep")
        finally:
            restore()
        state.close()

        # The delete the caller was told failed did stay failed: the record
        # did not resurrect unacknowledged. Pre-#1238 the same commit failure
        # was swallowed and no caller ever heard about it.
        reopened = State(db_path=str(db_path))
        try:
            reopened_store = PersistedStore(reopened)
            reopened_store.initialize()
            assert reopened_store.get("items", "keep", Widget) == Widget(name="earlier")
        finally:
            reopened.close()

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    def test_put_raw_raises_on_commit_failure(self, db_path: Path) -> None:
        state, store, restore = self._commit_failing_store(db_path)
        try:
            with pytest.raises(sqlite3.OperationalError, match="simulated commit failure"):
                store.put_raw("raws", "r1", '{"x": 1}')
        finally:
            restore()
        state.close()
