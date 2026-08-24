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
    ArchiveError,
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


# ── listing a scope (#133 scope item 2: put / get / list / delete) ──


async def _keys_in(store: Any, scope: str) -> set[str]:
    return {str(key) async for key in store.list_scope(scope)}


async def test_a_scope_lists_what_was_archived_to_it(store: Any) -> None:
    first = await store.put(b"one", scope="learnings")
    second = await store.put(b"two", scope="learnings")

    assert await _keys_in(store, "learnings") == {str(first), str(second)}


async def test_a_scope_does_not_list_another_scopes_objects(store: Any) -> None:
    """Scope is the isolation boundary, so listing one must not reach another —
    and the same bytes in two scopes are two objects."""
    mine = await store.put(b"shared bytes", scope="learnings")
    await store.put(b"shared bytes", scope="episodic")

    assert await _keys_in(store, "learnings") == {str(mine)}


async def test_an_empty_scope_lists_nothing_rather_than_raising(store: Any) -> None:
    """Asking what is archived under a scope nothing has archived to is a
    reasonable question with a short answer."""
    assert await _keys_in(store, "never-written") == set()


async def test_a_deleted_object_leaves_the_listing(store: Any) -> None:
    kept = await store.put(b"kept", scope="learnings")
    removed = await store.put(b"removed", scope="learnings")

    await store.delete(removed)

    assert await _keys_in(store, "learnings") == {str(kept)}


async def test_every_listed_key_reads_back(store: Any) -> None:
    """A listing that names keys `get` cannot resolve is worse than no listing:
    a caller iterating a scope to rehydrate it would fail partway through."""
    payloads = [f"record {index}".encode() for index in range(5)]
    for payload in payloads:
        await store.put(payload, scope="learnings")

    found = [await store.get(key) async for key in store.list_scope("learnings")]

    assert sorted(found) == sorted(payloads)


async def test_listing_is_lazy_enough_to_stop_early(store: Any) -> None:
    """The reason it is an iterator. A scope is the tier everything cold
    accumulates in, so a caller wanting one key must not pay for all of them."""
    for index in range(10):
        await store.put(f"record {index}".encode(), scope="learnings")

    seen = []
    async for key in store.list_scope("learnings"):
        seen.append(key)
        break

    assert len(seen) == 1


# ── S3 pagination ─────────────────────────────────────────────────
#
# Backend-specific rather than conformance, because paging is: the filesystem
# backend reads a directory in one `scandir` and has no truncation to follow.
# Still here rather than in `test_s3_error_paths.py` because it needs the live
# server — a stub returning a hand-written `NextContinuationToken` would be
# asserting that the loop reads the key we told it to read.


async def test_a_truncated_listing_follows_the_continuation_token(s3_bucket: Any) -> None:
    """The property the paging loop exists for.

    S3 truncates at 1000 keys by default, so a listing that ignores
    `NextContinuationToken` returns a prefix of the answer and looks correct in
    any test below that size — a scope silently losing its tail is exactly the
    "archived is not gone" claim failing. `page_size` shrinks the boundary to
    where a real server will actually cross it.
    """
    from maistro.archive import S3ArchiveStore

    store = S3ArchiveStore(BUCKET, client=s3_bucket, page_size=2)
    archived = {str(await store.put(f"record {index}".encode(), scope=SCOPE)) for index in range(7)}

    assert len(archived) == 7, "distinct payloads must be distinct keys"
    assert await _keys_in(store, SCOPE) == archived


async def test_paging_stops_when_the_last_page_is_not_truncated(s3_bucket: Any) -> None:
    """The other arc: a listing that fits in one page must not ask for a
    second. Requests are counted rather than inferred, because an extra
    round trip on every listing is invisible to a result-only assertion."""
    from maistro.archive import S3ArchiveStore

    calls: list[dict[str, Any]] = []
    original = s3_bucket.list_objects_v2

    def counting(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return original(**kwargs)

    s3_bucket.list_objects_v2 = counting
    store = S3ArchiveStore(BUCKET, client=s3_bucket, page_size=10)
    await store.put(PAYLOAD, scope=SCOPE)

    assert await _keys_in(store, SCOPE) != set()
    assert len(calls) == 1, f"one page of one key took {len(calls)} requests"


def test_a_page_size_below_one_is_refused() -> None:
    """A zero or negative `MaxKeys` is rejected by the service mid-listing,
    which surfaces as a failed archive read rather than a configuration error.
    Refusing at construction puts the complaint where the mistake is."""
    from maistro.archive import S3ArchiveStore

    with pytest.raises(ArchiveError, match="page_size must be at least 1"):
        S3ArchiveStore(BUCKET, client=object(), page_size=0)
