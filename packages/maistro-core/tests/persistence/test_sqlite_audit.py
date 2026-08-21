"""Coverage for maistro.persistence.sqlite_audit.SqliteAuditLog against a real
in-memory sqlite3 DB (via aiosqlite)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
import pytest

from maistro.persistence.sqlite_audit import SqliteAuditLog
from maistro.types.security import AuditEntry


@pytest.fixture
async def log() -> AsyncIterator[SqliteAuditLog]:
    conn = await aiosqlite.connect(":memory:")
    a = SqliteAuditLog(conn)
    await a.ensure_schema()
    yield a
    await conn.close()


@pytest.mark.asyncio
async def test_log_and_get_entries_roundtrip(log: SqliteAuditLog) -> None:
    entry = AuditEntry(
        boundary="tool_call",
        user_id="u1",
        agent_id="a1",
        tool_name="bash",
        verdict="allowed",
        detail="ok",
        trace_id="t1",
        request_id="r1",
    )
    await log.log(entry)
    entries = await log.get_entries(user_id="u1")
    assert len(entries) == 1
    e = entries[0]
    assert e.boundary == "tool_call"
    assert e.user_id == "u1"
    assert e.agent_id == "a1"
    assert e.tool_name == "bash"
    assert e.verdict == "allowed"
    assert e.detail == "ok"
    assert e.trace_id == "t1"
    assert e.request_id == "r1"


@pytest.mark.asyncio
async def test_log_tool_name_none_stored_as_empty(log: SqliteAuditLog) -> None:
    await log.log(AuditEntry(boundary="b", user_id="u", agent_id="a", tool_name=None))
    entries = await log.get_entries(user_id="u")
    assert entries[0].tool_name == ""


@pytest.mark.asyncio
async def test_get_entries_no_filters_returns_all(log: SqliteAuditLog) -> None:
    await log.log(AuditEntry(boundary="b1", user_id="u1", agent_id="a1"))
    await log.log(AuditEntry(boundary="b2", user_id="u2", agent_id="a2"))
    entries = await log.get_entries()
    assert len(entries) == 2


@pytest.mark.asyncio
async def test_get_entries_both_filters_combined_with_and(log: SqliteAuditLog) -> None:
    await log.log(AuditEntry(boundary="b1", user_id="u1", agent_id="a1"))
    await log.log(AuditEntry(boundary="b2", user_id="u1", agent_id="a2"))
    entries = await log.get_entries(user_id="u1", agent_id="a1")
    assert len(entries) == 1
    assert entries[0].boundary == "b1"


@pytest.mark.asyncio
async def test_get_entries_respects_limit(log: SqliteAuditLog) -> None:
    for i in range(5):
        await log.log(AuditEntry(boundary=f"b{i}", user_id="u1", agent_id="a1"))
    entries = await log.get_entries(user_id="u1", limit=2)
    assert len(entries) == 2


@pytest.mark.asyncio
async def test_get_entries_ordered_newest_first(log: SqliteAuditLog) -> None:
    await log.log(AuditEntry(boundary="first", user_id="u1", agent_id="a1"))
    await log.log(AuditEntry(boundary="second", user_id="u1", agent_id="a1"))
    entries = await log.get_entries(user_id="u1")
    assert entries[0].boundary == "second"
    assert entries[1].boundary == "first"


@pytest.mark.asyncio
async def test_get_entries_invalid_filter_column_raises(
    log: SqliteAuditLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    import maistro.persistence.sqlite_audit as sqlite_audit_module

    monkeypatch.setattr(sqlite_audit_module, "_ALLOWED_FILTER_COLUMNS", frozenset({"agent_id"}))
    with pytest.raises(ValueError, match="Invalid filter column: 'user_id'"):
        await log.get_entries(user_id="u1")
