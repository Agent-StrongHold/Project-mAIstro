"""The archive boundary (ADR-082226-f436 decision 3).

Deliberately narrow: get-by-key is everything the engine needs, and every method
here has to be reimplemented correctly for every backend. No listing by prefix,
no server-side copy, no lifecycle rules — those are operator concerns that
belong to whatever runs the bucket, not to a protocol two implementations must
agree on.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from maistro.archive.types import ArchiveKey


@runtime_checkable
class ArchiveStore(Protocol):
    """Cold, durable storage for records that are still authoritative."""

    async def put(self, payload: bytes, *, scope: str) -> ArchiveKey:
        """Store bytes and return the key that addresses them.

        Idempotent by construction: the key is the payload's digest, so storing
        the same bytes twice writes the same object.
        """
        ...

    async def get(self, key: ArchiveKey) -> bytes:
        """Return the archived bytes.

        Raises :class:`~maistro.archive.types.ArchivedRecordNotFound` when the
        object is missing and
        :class:`~maistro.archive.types.ArchiveIntegrityError` when the bytes do
        not hash to the key. Never returns empty for a record that should exist.
        """
        ...

    async def exists(self, key: ArchiveKey) -> bool:
        """Whether an object exists, without transferring it."""
        ...

    def list_scope(self, scope: str) -> AsyncIterator[ArchiveKey]:
        """Every key under `scope`, in no guaranteed order.

        An async *iterator* rather than a list: a scope is unbounded by design —
        it is the tier everything cold accumulates in — and a caller that only
        wants the first few must not pay for the last million. S3 pages
        natively, and the filesystem walk is lazy for the same reason.

        Scope-at-a-time rather than a free prefix. `ArchiveKey` is
        `<scope>/<digest>`, and the digest half is content-addressed, so a
        prefix inside it selects an arbitrary hash bucket rather than anything a
        caller meant. Scope is the only prefix with a meaning.
        """
        ...

    async def delete(self, key: ArchiveKey) -> None:
        """Remove an object. Deleting what is not there is not an error."""
        ...


__all__ = ["ArchiveStore"]
