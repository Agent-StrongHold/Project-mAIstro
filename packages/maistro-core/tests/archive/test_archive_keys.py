"""Keys are addresses, and an address that can point anywhere is a hole.

`ArchiveKey`'s scope becomes a path segment on the filesystem backend and an
object-key prefix on S3. The filesystem case is the sharp one: an unvalidated
scope containing `..` writes outside the archive root, which turns a storage
tier into arbitrary file write. Validating in the value type rather than in each
backend means a backend cannot forget.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.archive import (
    ArchivedRecordNotFound,
    ArchiveError,
    ArchiveKey,
    FilesystemArchiveStore,
    InvalidArchiveScope,
)


@pytest.mark.parametrize(
    "scope",
    [
        "..",
        "../etc",
        "learnings/../../etc",
        "/absolute",
        "learnings/",
        "",
        "Learnings",  # uppercase: two scopes that differ only by case are one
        "learnings//org",
        "learnings/org 1",  # whitespace
        "learnings/org\x00",
    ],
)
def test_unsafe_scopes_are_refused(scope: str) -> None:
    with pytest.raises(InvalidArchiveScope):
        ArchiveKey(scope=scope, digest="0" * 64)


@pytest.mark.parametrize(
    "scope",
    ["learnings", "learnings/org-1", "runs/2026/attempts", "a", "a.b_c-d/e"],
)
def test_ordinary_scopes_are_accepted(scope: str) -> None:
    assert ArchiveKey(scope=scope, digest="0" * 64).scope == scope


@pytest.mark.parametrize("digest", ["", "abc", "g" * 64, "0" * 63, "0" * 65, "0" * 64 + "0"])
def test_a_digest_that_is_not_a_sha256_is_refused(digest: str) -> None:
    with pytest.raises(ArchiveError):
        ArchiveKey(scope="learnings", digest=digest)


def test_uppercase_digests_are_refused() -> None:
    """Two spellings of one digest would address two objects."""
    with pytest.raises(ArchiveError):
        ArchiveKey(scope="learnings", digest="A" * 64)


def test_a_key_round_trips_through_its_string_form() -> None:
    key = ArchiveKey.for_payload(b"payload", scope="learnings/org-1")

    assert ArchiveKey.parse(str(key)) == key


def test_a_key_with_no_scope_is_refused() -> None:
    with pytest.raises(ArchiveError):
        ArchiveKey.parse("0" * 64)


async def test_the_filesystem_backend_cannot_be_walked_out_of(tmp_path: Path) -> None:
    """Belt to the value type's braces: even a key that got past validation
    must not resolve outside the root."""
    store = FilesystemArchiveStore(tmp_path / "archive")
    key = ArchiveKey.for_payload(b"payload", scope="learnings")
    escaped = ArchiveKey.__new__(ArchiveKey)
    object.__setattr__(escaped, "scope", "../../escape")
    object.__setattr__(escaped, "digest", key.digest)

    with pytest.raises(ArchivedRecordNotFound):
        await store.get(escaped)

    assert not (tmp_path.parent / "escape").exists()
