"""Audit log: every boundary crossing logged."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maistro.security.sentinel.signing import AuditSigner

if TYPE_CHECKING:
    from maistro.security._types import AuditEntry


class InMemoryAuditLog:
    """In-memory audit log with tamper-evident Sentinel decision proofs.

    The default generated key is intentionally process-local. A deployment
    using this store for anything beyond tests must pass the same externally
    managed signer key it uses for its durable audit store.
    """

    def __init__(self, *, signer: AuditSigner | None = None) -> None:
        self._entries: list[AuditEntry] = []
        self.signer = signer or AuditSigner()

    async def log(self, entry: AuditEntry) -> None:
        self._entries.append(self.signer.sign(entry))

    def verify(self, entry: Any) -> bool:
        """Verify an entry with this store's public verification key."""
        return self.signer.verify(entry)

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
