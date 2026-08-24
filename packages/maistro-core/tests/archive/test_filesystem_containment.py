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
