"""Failed transaction entry and commit must not poison later schedule writes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from maistro.scheduling.model import Schedule
from maistro.scheduling.store import SqliteScheduleStore

pytestmark = [pytest.mark.contract("behavioral")]


@pytest.fixture
async def schedule_db(tmp_path: Path) -> AsyncIterator[tuple[Any, ...]]:
    async with aiosqlite.connect(tmp_path / "write-failure.sqlite3") as conn:
        store = SqliteScheduleStore(conn)
        await store.ensure_schema()
        schedule = await store.put(
            Schedule(
                workspace_id="w1",
                project_id="p1",
                cron="0 * * * *",
                graph_template_id="test",
                name="before",
            )
        )
        yield store, conn, schedule


async def _cancel_after(worker: asyncio.Task[Any], reached: asyncio.Event) -> None:
    try:
        await asyncio.wait_for(reached.wait(), timeout=10)
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
    finally:
        if not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


async def _assert_reusable(store: SqliteScheduleStore, conn: Any, schedule: Schedule) -> None:
    assert conn.in_transaction is False
    retained = await store.get(schedule.schedule_id)
    assert retained is not None and retained.name == "before"
    await store.put(schedule.model_copy(update={"name": "after"}))
    final = await store.get(schedule.schedule_id)
    assert final is not None and final.name == "after"


async def test_failed_commit_rolls_back_before_releasing_writer(
    schedule_db: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, conn, schedule = schedule_db
    original = conn.commit

    async def fail_commit() -> None:
        raise aiosqlite.OperationalError("injected commit failure")

    monkeypatch.setattr(conn, "commit", fail_commit)
    with pytest.raises(aiosqlite.OperationalError, match="injected commit failure"):
        await store.put(schedule.model_copy(update={"name": "uncommitted"}))
    monkeypatch.setattr(conn, "commit", original)
    await _assert_reusable(store, conn, schedule)


async def _cancel_and_hold(worker: asyncio.Task[Any], reached: asyncio.Event) -> None:
    """Cancel the writer mid-commit and prove it waits the commit out.

    aiosqlite has queued the COMMIT on its worker thread by now; cancelling
    the awaiting task cannot retract it. The writer must not classify the
    exit until the commit resolves (Codex, #1199).
    """
    await asyncio.wait_for(reached.wait(), timeout=10)
    worker.cancel()
    for _ in range(5):
        await asyncio.sleep(0)
    assert not worker.done(), "the cancellation is held until the queued COMMIT resolves"


async def test_cancelled_commit_rolls_back_before_releasing_writer(
    schedule_db: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The queued COMMIT resolves as a failure: nothing landed, so the
    rollback is real and the old Schedule is what remains."""
    store, conn, schedule = schedule_db
    reached = asyncio.Event()
    release = asyncio.Event()
    original = conn.commit

    async def commit_that_fails_after_release() -> None:
        reached.set()
        await release.wait()
        raise aiosqlite.OperationalError("queued commit failed")

    monkeypatch.setattr(conn, "commit", commit_that_fails_after_release)
    worker = asyncio.create_task(store.put(schedule.model_copy(update={"name": "uncommitted"})))
    try:
        await _cancel_and_hold(worker, reached)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await worker
    finally:
        if not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
    monkeypatch.setattr(conn, "commit", original)
    await _assert_reusable(store, conn, schedule)


async def test_a_cancelled_commit_that_lands_is_kept(
    schedule_db: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The queued COMMIT resolves as a success: the write is durable, no
    rollback is issued behind it, and the caller still sees the cancellation
    rather than a return value it did not get."""
    store, conn, schedule = schedule_db
    reached = asyncio.Event()
    release = asyncio.Event()
    original = conn.commit
    rollbacks = 0
    original_rollback = conn.rollback

    async def counted_rollback() -> None:
        nonlocal rollbacks
        rollbacks += 1
        await original_rollback()

    async def commit_after_release() -> None:
        reached.set()
        await release.wait()
        await original()

    monkeypatch.setattr(conn, "commit", commit_after_release)
    monkeypatch.setattr(conn, "rollback", counted_rollback)
    worker = asyncio.create_task(store.put(schedule.model_copy(update={"name": "landed"})))
    try:
        await _cancel_and_hold(worker, reached)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await worker
    finally:
        if not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
    monkeypatch.setattr(conn, "commit", original)
    monkeypatch.setattr(conn, "rollback", original_rollback)

    assert rollbacks == 0, "a landed commit is never chased by a rollback"
    assert conn.in_transaction is False
    landed = await store.get(schedule.schedule_id)
    assert landed is not None and landed.name == "landed"


async def test_cancelled_begin_rolls_back_a_transaction_that_already_started(
    schedule_db: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, conn, schedule = schedule_db
    reached = asyncio.Event()
    original = conn.execute

    async def entered_begin(sql: str, parameters: Any = ()) -> Any:
        cursor = await original(sql, parameters)
        if sql == "BEGIN IMMEDIATE":
            # The database has begun even though the awaiting coroutine has
            # not returned. Cancellation here must still release its lock.
            reached.set()
            await asyncio.Event().wait()
        return cursor

    monkeypatch.setattr(conn, "execute", entered_begin)
    worker = asyncio.create_task(store.put(schedule.model_copy(update={"name": "uncommitted"})))
    await _cancel_after(worker, reached)
    monkeypatch.setattr(conn, "execute", original)
    await _assert_reusable(store, conn, schedule)
