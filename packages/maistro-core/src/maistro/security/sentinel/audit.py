"""Audit log: every boundary crossing logged."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maistro.security._types import AuditEntry


class InMemoryAuditLog:
    """In-memory audit log for testing."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    async def log(self, entry: AuditEntry) -> None:
        self._entries.append(entry)

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
        return list(reversed(result))[:limit]
