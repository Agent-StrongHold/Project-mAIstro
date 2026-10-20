"""Audit log: every boundary crossing logged."""

from __future__ import annotations

from bisect import bisect_left, insort
from dataclasses import asdict
from itertools import product
from threading import Lock
from typing import TYPE_CHECKING, Any

from maistro.persistence.audit_pages import MAX_PAGE_SIZE, AuditPage, decode_cursor, make_page
from maistro.security.sentinel.signing import AuditSigner

if TYPE_CHECKING:
    from maistro.security._types import AuditEntry


class InMemoryAuditLog:
    """Ephemeral audit adapter with write-maintained pagination indexes.

    Immutable entries and a single append seam make the indexes authoritative
    projections of `_entries`, not a second audit store. Every optional filter
    shape has an ordered index, so sparse filters cannot turn a page into a
    corpus scan. Writes retain eight keys per record; out-of-order inserts may
    shift an index, while page reads cost O(log n + limit).

    Entries are signed with the store's signer before retention (ADR-073
    decision proofs). The default generated key is intentionally process-local:
    a deployment using this store for anything beyond tests must pass the same
    externally managed signer key it uses for its durable audit store.
    """

    def __init__(self, *, signer: AuditSigner | None = None) -> None:
        self._lock = Lock()
        self._entries: list[AuditEntry] = []
        self.signer = signer or AuditSigner()
        self._page_indexes: dict[
            tuple[str, str | None, str | None, bool | None], list[tuple[str, int]]
        ] = {}

    async def log(self, entry: AuditEntry) -> None:
        self.log_sync(entry)

    def log_sync(self, entry: AuditEntry) -> None:
        """Shared append seam for async callers and synchronous bridge threads."""
        signed = self.signer.sign(entry)
        with self._lock:
            key = (signed.timestamp.isoformat(), len(self._entries) + 1)
            self._entries.append(signed)
            for user, boundary, denied in product(
                (None, signed.user_id), (None, signed.boundary), (None, signed.verdict == "denied")
            ):
                index = self._page_indexes.setdefault((signed.org_id, user, boundary, denied), [])
                insort(index, key)

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
        """Seek the scope/filter index and materialize at most limit + 1 rows."""
        if org_id is None:
            raise ValueError("org_id cannot be None; pass '' for an unscoped read")
        before = decode_cursor(cursor) if cursor is not None else None
        size = max(1, min(limit, MAX_PAGE_SIZE))
        # The sync Hive bridge may append from worker threads. Hold the same
        # lock while seeking/copying keys so no partial index update is visible.
        with self._lock:
            index = self._page_indexes.get((org_id, user_id, boundary, denied), [])
            end = len(index) if before is None else bisect_left(index, before)
            keys = index[max(0, end - size - 1) : end]
            rows = [
                dict(asdict(self._entries[row_id - 1]), id=row_id, timestamp=timestamp)
                for timestamp, row_id in reversed(keys)
            ]
        return make_page(rows, size)

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
        if org_id is None:
            raise ValueError("org_id cannot be None; pass '' for an unscoped read")
        # Empty is the explicit system/unscoped scope, not an all-org read.
        result = [e for e in result if e.org_id == org_id]
        return list(reversed(result))[:limit]
