"""Local-filesystem archive store — the homelab tier (ADR-082226-d3dd).

No third-party dependency, which is the point: `maistro-core`'s base install
must be able to archive without a cloud SDK. It is also what the S3
implementation is checked against, since both satisfy one protocol and the
tests run the same conformance suite over each.

Three properties this backend has to get right, because the tier below it is
nothing:

- **Durability, not just atomicity.** `put` returning is what lets the archive
  sweep clear the source row, so the bytes must be on the platter by then —
  `write` + `rename` gives atomic *visibility* and no durability at all.
- **A private tree.** Archived Runs, Attempts and memory are authoritative
  records; on a multi-user host the default `022` umask would publish them to
  every local account.
- **One reserved namespace.** Temporary files live under names `_validate_key`
  refuses, so a staging file can never collide with a real key and a real key
  can never be hidden by a listing filter.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
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

#: Owner-only, on the directories and the payloads alike. An archive holds the
#: same records PostgreSQL held before them; publishing them to every local
#: account on the way down a storage tier would be a strange place to lose them.
_DIR_MODE = 0o700
_FILE_MODE = 0o600


class ArchiveKeyError(ArchiveError):
    """A key that cannot be mapped to a path safely."""


def _validate_key(key: str) -> str:
    """Reject anything that would escape the archive root or shadow staging.

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
    _reject_unsafe_segments(key)
    return key


def _reject_unsafe_segments(key: str) -> None:
    """The per-segment half of `_validate_key`, split out to keep either half
    readable — and under the complexity ratchet, which caught the fifth rule.

    Leading dots are refused for a reason the others do not share: this backend
    stages writes under dot-prefixed names, and `list_keys` skips them. Without
    this rule a caller could store a key that `put`, `get` and `exists` all
    honour while `list_keys` silently omits it — a listing that is quietly not a
    listing. Reserving the namespace here is what makes that filter safe.
    """
    segments = key.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        msg = f"archive key must not contain empty or traversal segments, got {key!r}"
        raise ArchiveKeyError(msg)
    if any(seg.startswith(".") for seg in segments):
        msg = f"archive key segments must not start with '.' (reserved for staging), got {key!r}"
        raise ArchiveKeyError(msg)
    if any("\x00" in seg for seg in segments):
        msg = f"archive key must not contain NUL, got {key!r}"
        raise ArchiveKeyError(msg)


def _mkdir_private(directory: Path) -> None:
    """`mkdir -p` with owner-only permissions on every level it creates.

    `Path.mkdir(parents=True, mode=...)` applies `mode` to the leaf only —
    pathlib creates intermediate directories with the default mode, so a nested
    key's parent directories would be world-traversable while the leaf was not.
    """
    missing: list[Path] = []
    probe = directory
    while not probe.exists():
        missing.append(probe)
        if probe.parent == probe:
            break
        probe = probe.parent
    for path in reversed(missing):
        # `exist_ok`: a concurrent writer may have created it since the probe.
        path.mkdir(mode=_DIR_MODE, exist_ok=True)


def _fsync_directory(directory: Path) -> None:
    """Flush the directory entry, so the rename itself survives a crash.

    Fsyncing the file makes its *contents* durable; the link that names it lives
    in the parent directory and needs its own flush. Without this, a crash can
    leave the payload written and unreachable.
    """
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sort_key(name: str, *, is_dir: bool) -> str:
    """Order directory entries the way their full keys order.

    Sorting bare names puts `a/b` before `a.txt`, because it compares `a` with
    `a.txt`; the keys themselves sort the other way round, since `.` (0x2E)
    precedes `/` (0x2F). Comparing a directory as `name + "/"` — the prefix
    every key beneath it actually carries — makes a streaming walk emit exactly
    the order a sorted list of full keys would.
    """
    return f"{name}/" if is_dir else name


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
            _mkdir_private(path.parent)
            if path.exists() and path.read_bytes() == payload:
                return  # idempotent: same bytes, same key, no rewrite
            # A unique staging file per attempt, not one named after the digest.
            # Two sweeps retrying the same record derive the *same* digest by
            # construction, so a digest-named temporary is exactly the case that
            # collides: the first `replace` unlinks it and the second raises
            # FileNotFoundError on an operation that is supposed to be
            # idempotent. `mkstemp` also creates at 0600 rather than umask.
            fd, staged_name = tempfile.mkstemp(
                dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
            )
            staged = Path(staged_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    # Durability, not atomicity. `put` returning is the archive
                    # sweep's cue to drop the source row, so a crash after this
                    # returns must not be able to lose the payload.
                    os.fsync(handle.fileno())
                os.chmod(staged, _FILE_MODE)
                os.replace(staged, path)
            except BaseException:
                staged.unlink(missing_ok=True)
                raise
            _fsync_directory(path.parent)

        await asyncio.to_thread(_write)
        return digest

    async def get(self, key: str, *, expected_digest: str | None = None) -> ArchivedRecord:
        """Read one archived payload.

        `expected_digest` is the attestation, and it comes from the caller's
        stub row. This backend stores the payload and nothing else, so a digest
        computed here is computed from whatever bytes are on disk — including
        corrupted ones. Comparing that against itself would pass on a truncated
        file and hand back a record that reads as authoritative, which is worse
        than a failed read. Pass the digest `put` returned and the check is
        real; omit it and the returned digest describes the bytes rather than
        vouching for them.
        """
        path = self._path_for(key)
        try:
            payload = await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise ArchiveKeyNotFoundError(key) from exc
        record = ArchivedRecord(
            key=key, payload=payload, digest=expected_digest or content_digest(payload)
        )
        record.verify()
        return record

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path_for(key).is_file)

    async def list_keys(self, prefix: str = "") -> AsyncIterator[str]:
        """Stream keys in order, one directory at a time.

        Deliberately not `rglob` into a sorted list: the archive is the one tier
        expected to outgrow memory, and materialising every key before yielding
        the first is the gate that works until the day it matters. Directories
        that cannot contain a match are never descended into at all.
        """
        async for key in self._walk("", prefix):
            yield key

    async def _walk(self, relative: str, prefix: str) -> AsyncIterator[str]:
        directory = self._root / relative if relative else self._root
        for name, is_dir in await asyncio.to_thread(_scan, directory):
            key = f"{relative}/{name}" if relative else name
            if is_dir:
                # Descend only where a match could live: either the whole
                # subtree is under the prefix, or the prefix reaches into it.
                if key.startswith(prefix) or prefix.startswith(f"{key}/"):
                    async for nested in self._walk(key, prefix):
                        yield nested
            elif key.startswith(prefix):
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


def _scan(directory: Path) -> list[tuple[str, bool]]:
    """One directory's entries, key-ordered, with staging files dropped.

    Dot-prefixed names are this backend's staging namespace, which
    `_validate_key` refuses for real keys — so skipping them here can never hide
    something a caller stored.
    """
    try:
        with os.scandir(directory) as entries:
            found = [
                (entry.name, entry.is_dir())
                for entry in entries
                # Symlinks are skipped rather than followed. `_path_for` already
                # refuses a key whose path resolves outside the root, so a
                # symlinked directory would otherwise put keys in the listing
                # that every read of them rejects — the listing-that-is-not-a-
                # listing again, from the other end. This store never creates
                # one, so nothing legitimate is lost.
                if not entry.name.startswith(".") and not entry.is_symlink()
            ]
    except (FileNotFoundError, NotADirectoryError):
        return []
    return sorted(found, key=lambda item: _sort_key(item[0], is_dir=item[1]))
