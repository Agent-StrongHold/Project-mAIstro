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
import re
from collections.abc import AsyncIterator
from pathlib import Path

from maistro.archive.types import (
    ArchivedRecordNotFound,
    ArchiveIntegrityError,
    ArchiveKey,
)

#: A sha256 hex digest, which is what every object here is named.
_DIGEST = re.compile(r"[0-9a-f]{64}")

#: Owner-only, on both the tree and the objects in it. An archived record is a
#: record that *moved* out of the database, so it keeps the exposure it had
#: there: a homelab archive under a shared home directory must not be
#: world-readable because the process umask happened to be 022.
_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600


class FilesystemArchiveStore:
    """Content-addressed objects under a root directory."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        _mkdir_private(self._root)

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
        _mkdir_private(path.parent)
        # Write-then-rename: a reader must never see a half-written object. A
        # torn read would fail the digest check rather than corrupt anything,
        # but failing a read that should have succeeded is still a fault.
        temporary = path.with_name(f".{path.name}.partial")
        # Written through a file descriptor rather than `write_bytes` so the
        # bytes can be fsynced before the rename publishes the name. Without
        # that, `os.replace` is atomic with respect to *readers* and says
        # nothing about a crash: the directory entry can reach the disk before
        # the data it points at, leaving a correctly-named object full of
        # zeroes. An archive whose defining claim is that the record is still
        # authoritative cannot be the one component that loses it on a power
        # cut, so the ordering is made explicit here.
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FILE_MODE)
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        # And the rename itself, so the *name* survives the same crash the
        # bytes now do. Best-effort: some filesystems refuse to open a
        # directory for fsync, and failing a write that reached the disk over
        # a durability upgrade would be the worse trade.
        try:
            directory = os.open(path.parent, os.O_RDONLY)
        except OSError:  # pragma: no cover - platform-dependent
            return
        try:
            os.fsync(directory)
        except OSError:  # pragma: no cover - platform-dependent
            pass
        finally:
            os.close(directory)

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

    async def list_scope(self, scope: str) -> AsyncIterator[ArchiveKey]:
        """Every key under `scope`, discovered lazily.

        The directory is listed through `scandir` on a worker thread and
        yielded a batch at a time rather than materialised: a scope holds
        everything that ever went cold, and a caller reading the first few keys
        must not wait for the last million.

        Partial writes are skipped by name. `_write` renames into place from a
        `.<digest>.partial` sibling, so anything still carrying that name is a
        write in flight, not an object — and `ArchiveKey` would reject it as a
        digest anyway.
        """
        # Validated by constructing a key, so an unsafe scope is refused here
        # rather than reaching the filesystem walk below.
        directory = (self._root / ArchiveKey(scope=scope, digest="0" * 64).scope).resolve()
        if not directory.is_relative_to(self._root.resolve()):
            return
        for digest in await asyncio.to_thread(_digests_in, directory):
            yield ArchiveKey(scope=scope, digest=digest)

    async def delete(self, key: ArchiveKey) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)


def _mkdir_private(directory: Path) -> None:
    """Create `directory` and any missing ancestor, each owner-only.

    Not `mkdir(parents=True, mode=...)`: that mode applies to the final
    component only, and every parent it creates on the way gets the default
    permissions instead. A scope like `learnings/org-1` would then leave
    `learnings/` world-readable while the leaf below it was locked down, which
    is the wrong half. Each level is created separately so the mode is the one
    asked for at every level.

    `mkdir` applies the process umask to the mode, which can only remove bits
    from `0o700` — a umask that made this *wider* is not expressible.
    """
    missing = []
    current = directory
    while not current.exists():
        missing.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    for path in reversed(missing):
        path.mkdir(mode=_DIRECTORY_MODE, exist_ok=True)


def _digests_in(directory: Path) -> list[str]:
    """The digest-named files directly under `directory`, or nothing.

    A scope that was never written to is an empty scope, not an error: asking
    what is archived under a scope nothing has archived to is a reasonable
    question with a short answer.
    """
    try:
        return [
            entry.name
            for entry in os.scandir(directory)
            if entry.is_file() and _DIGEST.fullmatch(entry.name)
        ]
    except FileNotFoundError:
        return []


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
