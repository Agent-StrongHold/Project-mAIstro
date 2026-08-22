"""Local-filesystem archive store — the homelab tier (ADR-082226-d3dd).

No third-party dependency, which is the point: `maistro-core`'s base install
must be able to archive without a cloud SDK. It is also what the S3
implementation is checked against, since both satisfy one protocol and the
tests run the same conformance suite over each.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from maistro.protocols.archive import (
    ArchivedRecord,
    ArchiveError,
    ArchiveKeyNotFoundError,
    content_digest,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class ArchiveKeyError(ArchiveError):
    """A key that cannot be mapped to a path safely."""


def _validate_key(key: str) -> str:
    """Reject anything that would escape the archive root.

    Keys are `{kind}/{id}` and reach this from stub rows, so in the normal case
    they are engine-generated. That is exactly the argument that gets path
    traversal shipped: `id` is a value, values come from somewhere, and one day
    one of them comes from a request body. `..` in a key would write outside the
    archive root, and on a read would return a file the caller was never
    entitled to.
    """
    if not key or key != key.strip():
        msg = f"archive key must be non-empty and unpadded, got {key!r}"
        raise ArchiveKeyError(msg)
    if key.startswith("/") or "\\" in key:
        msg = f"archive key must be relative and use forward slashes, got {key!r}"
        raise ArchiveKeyError(msg)
    segments = key.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        msg = f"archive key must not contain empty or traversal segments, got {key!r}"
        raise ArchiveKeyError(msg)
    if any("\x00" in seg for seg in segments):
        msg = f"archive key must not contain NUL, got {key!r}"
        raise ArchiveKeyError(msg)
    return key


class FilesystemArchiveStore:
    """`ArchiveStore` over a directory tree."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def _path_for(self, key: str) -> Path:
        path = (self._root / _validate_key(key)).resolve()
        # Belt and braces over `_validate_key`: a symlink inside the tree can
        # point outside it, which no amount of string checking catches.
        if not path.is_relative_to(self._root):
            msg = f"archive key {key!r} resolves outside the archive root"
            raise ArchiveKeyError(msg)
        return path

    async def put(self, key: str, payload: bytes) -> str:
        path = self._path_for(key)
        digest = content_digest(payload)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.read_bytes() == payload:
                return  # idempotent: same bytes, same key, no rewrite
            # Write-then-rename, so a reader never observes a half-written
            # object and a crash mid-write cannot leave one behind.
            tmp = path.with_name(f"{path.name}.{digest.split(':')[1][:12]}.tmp")
            tmp.write_bytes(payload)
            tmp.replace(path)

        await asyncio.to_thread(_write)
        return digest

    async def get(self, key: str) -> ArchivedRecord:
        path = self._path_for(key)
        try:
            payload = await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise ArchiveKeyNotFoundError(key) from exc
        record = ArchivedRecord(key=key, payload=payload, digest=content_digest(payload))
        record.verify()
        return record

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path_for(key).is_file)

    async def list_keys(self, prefix: str = "") -> AsyncIterator[str]:
        def _walk() -> list[str]:
            if not self._root.is_dir():
                return []
            keys = [
                str(p.relative_to(self._root))
                for p in self._root.rglob("*")
                if p.is_file() and not p.name.endswith(".tmp")
            ]
            return sorted(k for k in keys if k.startswith(prefix))

        for key in await asyncio.to_thread(_walk):
            yield key

    async def delete(self, key: str) -> bool:
        path = self._path_for(key)

        def _unlink() -> bool:
            try:
                path.unlink()
            except FileNotFoundError:
                return False
            return True

        return await asyncio.to_thread(_unlink)
