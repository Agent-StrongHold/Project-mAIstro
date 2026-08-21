"""Tests for maistro.security.sentinel.audit — InMemoryAuditLog."""

from __future__ import annotations

import pytest

from maistro.security._types import AuditEntry
from maistro.security.sentinel.audit import InMemoryAuditLog


class TestInMemoryAuditLog:
    @pytest.mark.asyncio
    async def test_log_appends_entry(self) -> None:
        log = InMemoryAuditLog()
        entry = AuditEntry(boundary="tool_call", user_id="u1")
        await log.log(entry)
        entries = await log.get_entries()
        assert entries == [entry]

    @pytest.mark.asyncio
    async def test_get_entries_returns_reverse_chronological(self) -> None:
        log = InMemoryAuditLog()
        first = AuditEntry(boundary="b1", user_id="u1")
        second = AuditEntry(boundary="b2", user_id="u1")
        await log.log(first)
        await log.log(second)
        entries = await log.get_entries()
        assert entries == [second, first]

    @pytest.mark.asyncio
    async def test_filters_by_user_id(self) -> None:
        log = InMemoryAuditLog()
        e1 = AuditEntry(boundary="b", user_id="u1")
        e2 = AuditEntry(boundary="b", user_id="u2")
        await log.log(e1)
        await log.log(e2)
        entries = await log.get_entries(user_id="u1")
        assert entries == [e1]

    @pytest.mark.asyncio
    async def test_filters_by_agent_id(self) -> None:
        log = InMemoryAuditLog()
        e1 = AuditEntry(boundary="b", user_id="u1", agent_id="a1")
        e2 = AuditEntry(boundary="b", user_id="u1", agent_id="a2")
        await log.log(e1)
        await log.log(e2)
        entries = await log.get_entries(agent_id="a1")
        assert entries == [e1]

    @pytest.mark.asyncio
    async def test_respects_limit(self) -> None:
        log = InMemoryAuditLog()
        for i in range(5):
            await log.log(AuditEntry(boundary="b", user_id=f"u{i}"))
        entries = await log.get_entries(limit=2)
        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_no_entries_returns_empty_list(self) -> None:
        log = InMemoryAuditLog()
        assert await log.get_entries() == []
