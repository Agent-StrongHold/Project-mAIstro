"""A local directory as the archive tier (ADR-082226-f436 decision 3).

This is the homelab default and the test default. It exists so that "archiving"
is not a synonym for "has cloud credentials": a deployment with a NAS should not
have to buy an object-storage account to stop its row store growing forever.

It is a real implementation, not a stub. Writes are atomic, reads verify the
digest, and it satisfies the same conformance suite the S3 backend does.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from maistro.archive.types import (
    ArchivedRecordNotFound,
    ArchiveIntegrityError,
    ArchiveKey,
)


class FilesystemArchiveStore:
    """Content-addressed objects under a root directory."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def _path(self, key: ArchiveKey) -> Path:
        # `ArchiveKey` validates the scope against a pattern that excludes `..`
        # and absolute segments, so joining it here cannot escape the root. The
        # resolve() check below is the belt to that braces: a symlinked scope
        # directory could still point outside, and an archive that can write
        # anywhere on the filesystem is a worse problem than an unbounded table.
        candidate = (self._root / key.scope / key.digest).resolve()
        root = self._root.resolve()
        if not candidate.is_relative_to(root):
            raise ArchivedRecordNotFound(f"archive key {key} resolves outside {root}")
        return candidate

    async def put(self, payload: bytes, *, scope: str) -> ArchiveKey:
        key = ArchiveKey.for_payload(payload, scope=scope)
        await asyncio.to_thread(self._write, key, payload)
        return key

    def _write(self, key: ArchiveKey, payload: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a reader must never see a half-written object. A
        # torn read would fail the digest check rather than corrupt anything,
        # but failing a read that should have succeeded is still a fault.
        temporary = path.with_name(f".{path.name}.partial")
        temporary.write_bytes(payload)
        os.replace(temporary, path)

    async def get(self, key: ArchiveKey) -> bytes:
        payload = await asyncio.to_thread(self._read, key)
        verify(key, payload)
        return payload

    def _read(self, key: ArchiveKey) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise ArchivedRecordNotFound(str(key)) from exc

    async def exists(self, key: ArchiveKey) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def delete(self, key: ArchiveKey) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)


def verify(key: ArchiveKey, payload: bytes) -> None:
    """Refuse bytes that do not hash to the key that addressed them.

    Shared by both backends: content addressing is only worth having if reads
    actually check it.
    """
    actual = ArchiveKey.for_payload(payload, scope=key.scope)
    if actual.digest != key.digest:
        raise ArchiveIntegrityError(
            f"archived object {key} hashes to {actual.digest}; the stored bytes are not "
            f"the record this key addresses"
        )


__all__ = ["FilesystemArchiveStore", "verify"]
