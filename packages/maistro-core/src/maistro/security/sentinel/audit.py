"""Audit log: every boundary crossing logged."""

from __future__ import annotations

from dataclasses import asdict
from heapq import nlargest
from typing import TYPE_CHECKING

from maistro.persistence.audit_pages import MAX_PAGE_SIZE, AuditPage, decode_cursor, make_page

if TYPE_CHECKING:
    from maistro.security._types import AuditEntry


def _matches_page_filters(
    entry: AuditEntry,
    org_id: str,
    user_id: str | None,
    boundary: str | None,
    denied: bool | None,
) -> bool:
    return all(
        expected is None or actual == expected
        for actual, expected in (
            (entry.org_id, org_id),
            (entry.user_id, user_id),
            (entry.boundary, boundary),
            (entry.verdict == "denied", denied),
        )
    )


class InMemoryAuditLog:
    """In-memory audit log for testing."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    async def log(self, entry: AuditEntry) -> None:
        self._entries.append(entry)

    async def get_page(
        self,
        *,
        org_id: str = "",
        user_id: str | None = None,
        boundary: str | None = None,
        denied: bool | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> AuditPage:
        """Ephemeral adapter: bounded result memory, but still a linear scan."""
        if org_id is None:
            raise ValueError("org_id cannot be None; pass '' for an unscoped read")
        before = decode_cursor(cursor) if cursor is not None else None
        size = max(1, min(limit, MAX_PAGE_SIZE))
        candidates = (
            (entry.timestamp.isoformat(), index, entry)
            for index, entry in enumerate(self._entries, start=1)
            if _matches_page_filters(entry, org_id, user_id, boundary, denied)
            and (before is None or (entry.timestamp.isoformat(), index) < before)
        )
        rows = [
            dict(asdict(entry), id=index, timestamp=timestamp)
            for timestamp, index, entry in nlargest(size + 1, candidates)
        ]
        return make_page(rows, size)

    async def get_entries(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        org_id: str = "",
        limit: int = 100,
    ) -> list[AuditEntry]:
        result = self._entries
        if user_id:
            result = [e for e in result if e.user_id == user_id]
        if agent_id:
            result = [e for e in result if e.agent_id == agent_id]
        if org_id is None:
            raise ValueError("org_id cannot be None; pass '' for an unscoped read")
        # Empty is the explicit system/unscoped scope, not an all-org read.
        result = [e for e in result if e.org_id == org_id]
        return list(reversed(result))[:limit]
