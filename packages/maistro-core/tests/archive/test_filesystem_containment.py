"""The filesystem backend must not read or write outside its root.

`ArchiveKey` already refuses a scope containing `..` or a leading separator, so
string validation alone would make every path safe. It does not, because the
path is resolved against a real filesystem: a scope directory that is a symlink
elsewhere is a perfectly valid name pointing outside the root, and nothing in the
key can see that. Both `_path` and `list_scope` resolve and re-check for exactly
this case, and neither arc is reachable without a symlink on disk — which is why
these tests exist rather than a comment saying the guard is defensive.

An archive that can be aimed at arbitrary paths is worse than one that loses
data: it reads whatever the process can read and serves it as an archived
record.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from maistro.archive import ArchivedRecordNotFound, ArchiveKey, FilesystemArchiveStore

DIGEST = "0" * 64


def _rooted(tmp_path: Path) -> tuple[FilesystemArchiveStore, Path]:
    """A store whose `escaped` scope is a symlink to a directory outside it."""
    root = tmp_path / "archive"
    outside = tmp_path / "outside"
    (root / "learnings").mkdir(parents=True)
    outside.mkdir()
    (root / "escaped").symlink_to(outside, target_is_directory=True)
    return FilesystemArchiveStore(root), outside


def test_a_symlinked_scope_cannot_be_read_through(tmp_path: Path) -> None:
    """The path that would serve someone else's file as an archived record."""
    store, outside = _rooted(tmp_path)
    (outside / DIGEST).write_bytes(b"not ours")

    with pytest.raises(ArchivedRecordNotFound, match="resolves outside"):
        store._path(ArchiveKey(scope="escaped", digest=DIGEST))


async def test_a_symlinked_scope_lists_nothing(tmp_path: Path) -> None:
    """`list_scope` resolves separately from `_path`, so it needs its own check:
    a listing that walked the symlink would hand back keys that `get` then
    refuses, which reads as corruption rather than as containment."""
    store, outside = _rooted(tmp_path)
    (outside / DIGEST).write_bytes(b"not ours")

    assert [key async for key in store.list_scope("escaped")] == []


async def test_a_scope_inside_the_root_still_lists(tmp_path: Path) -> None:
    """The containment check must not be doing its job by refusing everything."""
    store, _ = _rooted(tmp_path)
    await store.put(b"ours", scope="learnings")

    found = [str(key) async for key in store.list_scope("learnings")]

    assert found == [str(ArchiveKey.for_payload(b"ours", scope="learnings"))]


# ── durability and exposure ───────────────────────────────────────
#
# Both properties the retired `maistro.memory.archive` tier tested and this one
# did not. They came back with the consolidation rather than being lost with the
# deletion: a tier whose whole claim is "the archived record is still
# authoritative" is the wrong component to have the weaker durability story.


async def test_the_payload_and_its_directory_entry_are_both_flushed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`os.replace` is atomic for readers and says nothing about a crash.

    Without an fsync of the bytes before the rename, the directory entry can
    reach the disk first and leave a correctly-named object full of zeroes —
    which then fails its own digest check on read, so the record is not merely
    lost but reads as corrupted. Without an fsync of the directory after, the
    name itself can be the thing that does not survive.

    Descriptors are recorded rather than counted, so this pins *what* was
    flushed and not just how often.
    """
    synced: list[int] = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd))[1])

    store = FilesystemArchiveStore(tmp_path / "archive")
    key = await store.put(b"durable", scope="learnings")

    assert len(synced) == 2, f"expected the payload and its directory, got {len(synced)} fsync(s)"
    assert await store.get(key) == b"durable"


async def test_the_tree_is_owner_only(tmp_path: Path) -> None:
    """An archived record keeps the exposure it had in the database.

    Every level is checked, not just the leaf: `mkdir(parents=True, mode=...)`
    applies the mode to the final component only, so a nested scope is exactly
    where an intermediate directory would come out world-readable while the
    object below it was locked down.
    """
    root = tmp_path / "archive"
    store = FilesystemArchiveStore(root)
    key = await store.put(b"private", scope="learnings/org-1")

    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "learnings").stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "learnings" / "org-1").stat().st_mode) == 0o700
    assert stat.S_IMODE((root / str(key)).stat().st_mode) == 0o600
