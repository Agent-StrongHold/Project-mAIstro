"""Coverage for maistro.persistence.sqlite_audit.SqliteAuditLog against a real
in-memory sqlite3 DB (via aiosqlite)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest

from maistro.persistence.sqlite_audit import SqliteAuditLog
from maistro.security._types import AuditEntry as SentinelAuditEntry
from maistro.security._types import Violation as SentinelViolation
from maistro.security.sentinel.signing import SIGNING_KEY_ENV, AuditSigner
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
    assert e.proof_type == "Ed25519Signature2020"
    assert log.verify(e)


@pytest.mark.asyncio
async def test_sentinel_entry_is_signed_and_durable(log: SqliteAuditLog) -> None:
    await log.log(SentinelAuditEntry(boundary="pre_call", user_id="u1", tool_name="bash"))

    [entry] = await log.get_entries(user_id="u1")
    assert entry.signature
    assert log.verify(entry)


@pytest.mark.asyncio
async def test_deny_with_violations_verifies_after_durable_roundtrip(
    log: SqliteAuditLog,
) -> None:
    """Deny decisions are the records tamper evidence exists for.

    The durable stores never serialize the violations tuple, so the proof must
    verify against the persisted columns alone — a signature computed over
    in-memory-only fields would leave every deny unverifiable after restart.
    """
    await log.log(
        SentinelAuditEntry(
            boundary="tool_call",
            user_id="u1",
            tool_name="bash",
            verdict="denied",
            violations=(
                SentinelViolation(
                    boundary="tool_call", rule="dangerous-command", severity="high", detail="d"
                ),
            ),
        )
    )

    [entry] = await log.get_entries(user_id="u1")
    assert entry.verdict == "denied"
    assert entry.signature
    assert log.verify(entry)

    forged = replace(entry, detail="forged after retention")
    assert not log.verify(forged)


@pytest.mark.asyncio
async def test_entry_with_unpersisted_metadata_verifies_after_roundtrip(
    log: SqliteAuditLog,
) -> None:
    """Correlation metadata must not break the durable proof.

    The user-model promotion auditor (#1047) logs action/project_id/run_id/
    workspace_id onto the same wired store that Sentinel decisions use, but
    the shipped durable stores serialize none of those columns. Signing them
    attached proofs no stored row could reproduce: legitimate records failed
    verify() after a restart. The proof must cover exactly the persisted
    decision bytes, so the signed row verifies even though the metadata is
    gone, while tampering a persisted column still fails.
    """
    await log.log(
        AuditEntry(
            boundary="user_model",
            user_id="u1",
            org_id="o1",
            action="promote",
            project_id="p1",
            run_id="r-123",
            workspace_id="w1",
            detail="d",
        )
    )

    [entry] = await log.get_entries(user_id="u1", org_id="o1")
    assert entry.signature
    assert entry.action == ""  # not serialized; proof must not depend on it
    assert log.verify(entry)

    forged = replace(entry, verdict="denied")
    assert not log.verify(forged)


@pytest.mark.asyncio
async def test_ephemeral_signing_key_warns_on_a_durable_store(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The ADR-073 restart contract needs a configured key: without one this
    durable store writes proofs no later process can verify, so it must say
    so at wire time instead of failing silently on the first post-restart
    ``verify()``."""
    conn = await aiosqlite.connect(":memory:")
    try:
        with caplog.at_level(logging.WARNING, logger="maistro.persistence.audit"):
            SqliteAuditLog(conn)
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert SIGNING_KEY_ENV in messages
        assert "verify" in messages
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_supplied_signing_key_does_not_warn_on_a_durable_store(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A deployment that configured its key chose durability; no warning."""
    conn = await aiosqlite.connect(":memory:")
    try:
        with caplog.at_level(logging.WARNING, logger="maistro.persistence.audit"):
            SqliteAuditLog(conn, signer=AuditSigner(bytes(32)))
        assert not [r for r in caplog.records if r.name == "maistro.persistence.audit"]
    finally:
        await conn.close()


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
        assert "ix_audit_log_scope" in indexes
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


@pytest.mark.asyncio
async def test_purge_expired_respects_boundary_and_legal_hold(log: SqliteAuditLog) -> None:
    old = datetime.now(UTC) - timedelta(days=2)
    await log._conn.executemany(
        "INSERT INTO audit_log (timestamp, user_id, agent_id) VALUES (?, ?, ?)",
        [(old.isoformat(), "held", "a"), (old.isoformat(), "free", "a")],
    )
    await log._conn.commit()

    removed = await log.purge_expired(
        before=datetime.now(UTC) - timedelta(days=1),
        legal_hold_user_ids=("held",),
    )

    assert removed == 1
    cursor = await log._conn.execute("SELECT user_id FROM audit_log")
    assert [row[0] for row in await cursor.fetchall()] == ["held"]
