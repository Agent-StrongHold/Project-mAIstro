"""One suite, both archive backends (ADR-082226-f436).

The tier's defining claim is that an archived record is still authoritative — it
moved, it was not backed up and it was not deleted. Almost every test here is a
way of checking that a caller can never confuse "archived" with "gone", because
that confusion turns a cost optimisation into data loss at the API boundary.

Both backends run the same bodies. The S3 one goes over HTTP to a real
S3-compatible server (see conftest), not a patched client: #122 found six
PostgreSQL defects that were invisible to client-level mocking, and there is no
reason to expect object storage to be kinder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from maistro.archive import (
    ArchivedRecordNotFound,
    ArchiveIntegrityError,
    ArchiveKey,
    ArchiveStore,
    FilesystemArchiveStore,
)

from .conftest import BUCKET

SCOPE = "learnings/org-1"
PAYLOAD = b'{"learning": "roll back before redeploying"}'


@pytest.fixture(params=["filesystem", "s3"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    if request.param == "filesystem":
        return FilesystemArchiveStore(tmp_path / "archive")
    client = request.getfixturevalue("s3_bucket")
    from maistro.archive import S3ArchiveStore

    return S3ArchiveStore(BUCKET, client=client)


# ── round trip ────────────────────────────────────────────────────


async def test_an_archived_record_comes_back_byte_identical(store: Any) -> None:
    key = await store.put(PAYLOAD, scope=SCOPE)

    assert await store.get(key) == PAYLOAD


async def test_empty_payloads_round_trip(store: Any) -> None:
    """Zero bytes is a legitimate record, and the one most likely to be
    confused with absence by a backend that returns falsy on missing."""
    key = await store.put(b"", scope=SCOPE)

    assert await store.exists(key) is True
    assert await store.get(key) == b""


async def test_binary_payloads_are_not_mangled(store: Any) -> None:
    payload = bytes(range(256)) * 8

    key = await store.put(payload, scope=SCOPE)

    assert await store.get(key) == payload


async def test_a_large_payload_round_trips(store: Any) -> None:
    payload = b"x" * (2 * 1024 * 1024)

    key = await store.put(payload, scope=SCOPE)

    assert await store.get(key) == payload


# ── content addressing ────────────────────────────────────────────


async def test_the_same_bytes_get_the_same_key(store: Any) -> None:
    """Re-archiving an unchanged record is a no-op, not a second copy."""
    first = await store.put(PAYLOAD, scope=SCOPE)
    second = await store.put(PAYLOAD, scope=SCOPE)

    assert first == second


async def test_different_bytes_get_different_keys(store: Any) -> None:
    first = await store.put(PAYLOAD, scope=SCOPE)
    second = await store.put(PAYLOAD + b" ", scope=SCOPE)

    assert first != second
    assert await store.get(first) == PAYLOAD


async def test_the_same_bytes_in_different_scopes_are_different_objects(store: Any) -> None:
    """Scope is part of the address, so one tenant's record is not another's."""
    first = await store.put(PAYLOAD, scope="learnings/org-1")
    second = await store.put(PAYLOAD, scope="learnings/org-2")

    assert first != second
    await store.delete(first)

    assert await store.exists(second) is True


# ── absence is explicit ───────────────────────────────────────────


async def test_a_missing_object_raises_rather_than_returning_empty(store: Any) -> None:
    """ADR decision 6. A caller holding a key got it from a tombstone row that
    says the payload is there; an empty result is indistinguishable from
    deletion to every caller."""
    key = ArchiveKey.for_payload(b"never archived", scope=SCOPE)

    with pytest.raises(ArchivedRecordNotFound):
        await store.get(key)


async def test_exists_is_false_rather_than_raising(store: Any) -> None:
    key = ArchiveKey.for_payload(b"never archived", scope=SCOPE)

    assert await store.exists(key) is False


async def test_deleting_what_is_not_there_is_not_an_error(store: Any) -> None:
    key = ArchiveKey.for_payload(b"never archived", scope=SCOPE)

    await store.delete(key)


async def test_a_deleted_object_is_gone_and_says_so(store: Any) -> None:
    key = await store.put(PAYLOAD, scope=SCOPE)

    await store.delete(key)

    assert await store.exists(key) is False
    with pytest.raises(ArchivedRecordNotFound):
        await store.get(key)


# ── integrity ─────────────────────────────────────────────────────


async def test_corrupted_bytes_are_refused_not_returned(store: Any) -> None:
    """Content addressing is only worth having if reads check it. A backend
    that returned truncated bytes would hand a caller something that looks like
    the record and is not."""
    key = await store.put(PAYLOAD, scope=SCOPE)
    _overwrite(store, key, b"not the record")

    with pytest.raises(ArchiveIntegrityError):
        await store.get(key)


def _overwrite(store: Any, key: ArchiveKey, payload: bytes) -> None:
    """Corrupt an object in place, per backend."""
    if isinstance(store, FilesystemArchiveStore):
        store._path(key).write_bytes(payload)
        return
    store._client.put_object(Bucket=BUCKET, Key=str(key), Body=payload)


# ── the protocol itself ───────────────────────────────────────────


def test_both_backends_satisfy_the_protocol(store: Any) -> None:
    assert isinstance(store, ArchiveStore)
