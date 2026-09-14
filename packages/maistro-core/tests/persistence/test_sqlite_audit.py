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
        org_id="org-a",
        agent_id="a1",
        tool_name="bash",
        verdict="allowed",
        detail="ok",
        trace_id="t1",
        request_id="r1",
    )
    await log.log(entry)
    entries = await log.get_entries(user_id="u1", org_id="org-a")
    assert len(entries) == 1
    e = entries[0]
    assert e.boundary == "tool_call"
    assert e.user_id == "u1"
    assert e.org_id == "org-a"
    assert e.agent_id == "a1"
    assert e.tool_name == "bash"
    assert e.verdict == "allowed"
    assert e.detail == "ok"
    assert e.trace_id == "t1"
    assert e.request_id == "r1"


@pytest.mark.asyncio
async def test_ensure_schema_upgrades_legacy_table_with_scope_index() -> None:
    conn = await aiosqlite.connect(":memory:")
    try:
        await conn.execute(
            """CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                boundary TEXT NOT NULL DEFAULT '',
                user_id TEXT NOT NULL DEFAULT '',
                team_id TEXT NOT NULL DEFAULT '',
                agent_id TEXT NOT NULL DEFAULT '',
                tool_name TEXT,
                verdict TEXT NOT NULL DEFAULT 'allowed',
                detail TEXT NOT NULL DEFAULT '',
                trace_id TEXT NOT NULL DEFAULT '',
                request_id TEXT NOT NULL DEFAULT ''
            )"""
        )
        await conn.commit()

        await SqliteAuditLog(conn).ensure_schema()

        cursor = await conn.execute("PRAGMA table_info(audit_log)")
        assert "org_id" in {row[1] for row in await cursor.fetchall()}
        cursor = await conn.execute("PRAGMA index_list(audit_log)")
        indexes = {row[1] for row in await cursor.fetchall()}
        assert "idx_audit_log_scope" in indexes
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_log_tool_name_none_stored_as_empty(log: SqliteAuditLog) -> None:
    await log.log(AuditEntry(boundary="b", user_id="u", agent_id="a", tool_name=None))
    entries = await log.get_entries(user_id="u")
    assert entries[0].tool_name == ""


@pytest.mark.asyncio
async def test_get_entries_defaults_to_system_scope(log: SqliteAuditLog) -> None:
    await log.log(AuditEntry(boundary="tenant-a", user_id="u1", org_id="org-a"))
    await log.log(AuditEntry(boundary="system-1", user_id="u1"))
    await log.log(AuditEntry(boundary="system-2", user_id="u2"))

    entries = await log.get_entries()

    assert [entry.boundary for entry in entries] == ["system-2", "system-1"]
    assert all(entry.org_id == "" for entry in entries)


@pytest.mark.asyncio
async def test_get_entries_both_filters_combined_with_and(log: SqliteAuditLog) -> None:
    await log.log(AuditEntry(boundary="b1", user_id="u1", agent_id="a1"))
    await log.log(AuditEntry(boundary="b2", user_id="u1", agent_id="a2"))
    entries = await log.get_entries(user_id="u1", agent_id="a1", org_id="")
    assert len(entries) == 1
    assert entries[0].boundary == "b1"


@pytest.mark.asyncio
async def test_get_entries_org_scope_cannot_cross_tenants(log: SqliteAuditLog) -> None:
    await log.log(AuditEntry(boundary="a", user_id="u", org_id="org-a"))
    await log.log(AuditEntry(boundary="b", user_id="u", org_id="org-b"))
    await log.log(AuditEntry(boundary="system", user_id="u"))

    entries = await log.get_entries(user_id="u", org_id="org-a")

    assert [entry.boundary for entry in entries] == ["a"]
    assert all(entry.org_id == "org-a" for entry in entries)


@pytest.mark.asyncio
async def test_get_entries_org_scope_composes_with_user_and_agent(
    log: SqliteAuditLog,
) -> None:
    await log.log(AuditEntry(boundary="match", user_id="u", agent_id="a", org_id="org-a"))
    await log.log(AuditEntry(boundary="other-agent", user_id="u", agent_id="b", org_id="org-a"))
    await log.log(AuditEntry(boundary="other-org", user_id="u", agent_id="a", org_id="org-b"))

    entries = await log.get_entries(user_id="u", agent_id="a", org_id="org-a")

    assert [entry.boundary for entry in entries] == ["match"]


@pytest.mark.asyncio
async def test_get_entries_rejects_none_org_scope(log: SqliteAuditLog) -> None:
    with pytest.raises(ValueError, match="pass '' for an unscoped read"):
        await log.get_entries(org_id=None)  # type: ignore[arg-type]


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


@pytest.mark.asyncio
async def test_get_entries_rejects_unknown_keyword(log: SqliteAuditLog) -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument 'status'"):
        await log.get_entries(status="denied")  # type: ignore[call-arg]
