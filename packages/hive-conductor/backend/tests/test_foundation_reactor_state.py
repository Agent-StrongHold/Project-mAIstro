"""#1178: the Foundation's Reactor persists through the one configured State.

Real `maistro.state.State` on tmp_path with a custom CONDUCTOR_STATE_DB. The
Reactor must write into that database through the State writer, never create
a second `data_dir/state.db`, never contend with ordinary PersistedStore
writes, and a restarted Foundation must read back the same reactor_log.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel


@pytest.fixture(autouse=True)
def _restore_store_bindings():
    import stores
    from services import profile_store, registration_policy, settings_store

    prev_persisted = stores._persisted
    prev_users = stores.users
    prev_initialize_stores = stores.initialize_stores
    user_snapshot = dict(stores.users._data)
    yield
    stores._persisted = prev_persisted
    for store in (*stores._all_model_stores, *stores._all_json_stores):
        store._persisted = prev_persisted
    stores.users = prev_users
    stores.initialize_stores = prev_initialize_stores
    stores.users._data.clear()
    stores.users._data.update(user_snapshot)
    settings_store.reset()
    profile_store.reset()
    registration_policy.reset()


def _settings(data_dir: Path, state_db: Path) -> Any:
    return SimpleNamespace(
        conductor_data_dir=str(data_dir),
        conductor_vault_path="",
        conductor_identity_path="",
        conductor_state_db=str(state_db),
        conductor_admin_public_key="",
        conductor_user_public_key="",
        session_cookie_secure=True,
        allow_insecure_transport=False,
    )


def _log_to_reactor(reactor: Any) -> None:
    async def handler(event: Any) -> None:
        reactor.state_submit(
            lambda conn: conn.execute(
                "INSERT INTO reactor_log (event_name) VALUES (?)", (event["name"],)
            )
        )

    reactor.register_source("log-event", handler)


async def _start(settings: Any) -> Any:
    from services.foundation import Foundation

    fnd = Foundation()
    await fnd.start(settings)
    assert fnd.state_available is True
    assert fnd.reactor_available is True
    return fnd


def _reactor_rows(db: Path) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT event_name FROM reactor_log ORDER BY rowid").fetchall()
    finally:
        conn.close()


async def test_reactor_writes_land_in_configured_state_db_only(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    state_db = tmp_path / "elsewhere" / "conductor.db"
    state_db.parent.mkdir()
    fnd = await _start(_settings(data_dir, state_db))
    try:
        _log_to_reactor(fnd.reactor)
        await fnd.reactor.emit("log-event", {"name": "configured"})
        await asyncio.sleep(0.2)
        fnd.state.flush()
    finally:
        await fnd.stop()

    assert _reactor_rows(state_db) == [("configured",)]
    assert not (data_dir / "state.db").exists()


async def test_reactor_and_persisted_store_writes_interleave_without_lock_errors(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import stores

    class Marker(BaseModel):
        n: int

    iterations = 200
    state_db = tmp_path / "conductor.db"
    fnd = await _start(_settings(tmp_path / "data", state_db))
    errors: list[Exception] = []

    def put_all() -> None:
        for i in range(iterations):
            try:
                stores._persisted.put("reactor_interleave", str(i), Marker(n=i))
            except Exception as exc:
                errors.append(exc)

    try:
        _log_to_reactor(fnd.reactor)
        writer = asyncio.get_running_loop().run_in_executor(None, put_all)
        for i in range(iterations):
            await fnd.reactor.emit("log-event", {"name": f"e{i}"})
            await asyncio.sleep(0)
        await writer
        await asyncio.sleep(0.3)
        fnd.state.flush()
        persisted = len(stores._persisted.list_all("reactor_interleave", Marker))
    finally:
        await fnd.stop()

    assert errors == []
    assert "database is locked" not in caplog.text
    assert persisted == iterations
    assert len(_reactor_rows(state_db)) == iterations


async def test_restarted_foundation_reads_the_same_reactor_log(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "data", tmp_path / "conductor.db")
    first = await _start(settings)
    try:
        _log_to_reactor(first.reactor)
        await first.reactor.emit("log-event", {"name": "before-restart"})
        await asyncio.sleep(0.2)
    finally:
        await first.stop()

    second = await _start(settings)
    try:
        rows = second.reactor.state_query("SELECT event_name FROM reactor_log")
    finally:
        await second.stop()
    assert rows == [("before-restart",)]
