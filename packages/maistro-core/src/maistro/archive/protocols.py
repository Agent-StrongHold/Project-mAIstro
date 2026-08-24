"""The archive boundary (ADR-082226-f436 decision 3).

Deliberately narrow: get-by-key is everything the engine needs, and every method
here has to be reimplemented correctly for every backend. No listing by prefix,
no server-side copy, no lifecycle rules — those are operator concerns that
belong to whatever runs the bucket, not to a protocol two implementations must
agree on.
"""

from __future__ import annotations

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

    async def delete(self, key: ArchiveKey) -> None:
        """Remove an object. Deleting what is not there is not an error."""
        ...


__all__ = ["ArchiveStore"]
