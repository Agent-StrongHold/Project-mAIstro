"""One conformance suite, run against every `ArchiveStore` implementation (#133).

Two implementations satisfying one protocol are two chances for them to differ
in a way nobody notices until a deployment swaps one for the other. So the
behavioural tests are parametrised over both rather than written twice, and the
S3 leg runs against a **real MinIO** — a mocked object store proves the call was
made with the arguments the test already knew, which is not the property worth
checking about storage.

The S3 leg skips without `MAISTRO_TEST_S3_ENDPOINT`. `ci.yml`'s `archive` job
sets it against a MinIO service; locally, point it at any S3-compatible server.
Skipping keeps the suite runnable on a laptop, but a skip is not a pass — the
CI job is what makes the S3 leg mean anything.
"""

from __future__ import annotations

import os

import pytest

from maistro.memory.archive import FilesystemArchiveStore
from maistro.protocols.archive import (
    ArchiveDigestMismatchError,
    ArchivedRecord,
    ArchiveKeyNotFoundError,
    ArchiveStore,
    RecordArchivedError,
    content_digest,
)

S3_ENDPOINT = os.environ.get("MAISTRO_TEST_S3_ENDPOINT", "")


async def _collect(store: ArchiveStore, prefix: str = "") -> list[str]:
    return [key async for key in store.list_keys(prefix)]


def _s3_store() -> ArchiveStore:
    """A fresh bucket per test, so listing assertions do not depend on what a
    previous test left behind."""
    from maistro.memory.archive import s3_archive_store

    return s3_archive_store(
        bucket=f"archive-test-{os.urandom(6).hex()}",
        endpoint_url=S3_ENDPOINT,
        region_name="us-east-1",
        access_key_id=os.environ.get("MAISTRO_TEST_S3_ACCESS_KEY", "minioadmin"),
        secret_access_key=os.environ.get("MAISTRO_TEST_S3_SECRET_KEY", "minioadmin"),
    )


@pytest.fixture
def filesystem_store(tmp_path):
    return FilesystemArchiveStore(tmp_path / "archive")


@pytest.fixture(params=["filesystem", "s3"])
async def store(request, tmp_path):
    """The same suite over both implementations.

    Async so the S3 bucket exists before the test body runs — doing it inside
    each test would put setup in twenty places and let one of them forget.
    """
    if request.param == "filesystem":
        return FilesystemArchiveStore(tmp_path / "archive")
    if not S3_ENDPOINT:
        pytest.skip("MAISTRO_TEST_S3_ENDPOINT is unset; the S3 leg needs a real server")
    s3 = _s3_store()
    await s3.ensure_bucket()
    return s3


class TestRoundTrip:
    async def test_a_record_round_trips_byte_identical(self, store):
        """The acceptance criterion, stated on bytes.

        Not "the payload is equal" via some decoded form: an archive that
        round-tripped through JSON would pass a semantic comparison while
        changing key order, float repr and byte length.
        """
        payload = bytes(range(256)) + b"\x00\xff" + "text — with unicode".encode()
        digest = await store.put("run/abc-123", payload)
        record = await store.get("run/abc-123")
        assert record.payload == payload
        assert record.digest == digest
        assert record.key == "run/abc-123"

    async def test_an_empty_payload_round_trips(self, store):
        """Zero bytes is a legitimate payload and the classic off-by-one: a
        store that treats empty as absent turns a real record into a miss."""
        await store.put("run/empty", b"")
        record = await store.get("run/empty")
        assert record.payload == b""
        assert await store.exists("run/empty") is True

    async def test_a_large_payload_round_trips(self, store):
        payload = os.urandom(1_000_000)
        await store.put("run/large", payload)
        assert (await store.get("run/large")).payload == payload

    async def test_put_is_idempotent_for_identical_bytes(self, store):
        """An interrupted sweep is re-run, so this is the normal case rather
        than an edge one. Same bytes, same key, same digest, one object."""
        payload = b"the same bytes"
        first = await store.put("run/idem", payload)
        second = await store.put("run/idem", payload)
        assert first == second
        assert await _collect(store, "run/") == ["run/idem"]

    async def test_rewriting_a_key_with_new_bytes_replaces_it(self, store):
        await store.put("run/rewrite", b"first")
        await store.put("run/rewrite", b"second")
        record = await store.get("run/rewrite")
        assert record.payload == b"second"
        assert record.digest == content_digest(b"second")


class TestMissingKeys:
    async def test_getting_an_absent_key_raises_rather_than_returning_none(self, store):
        """The decision the whole tier rests on (ADR-082226-d3dd §3). A `None`
        here is indistinguishable from "no such record" to every caller."""
        with pytest.raises(ArchiveKeyNotFoundError) as excinfo:
            await store.get("run/never-written")
        assert excinfo.value.key == "run/never-written"

    async def test_exists_is_false_for_an_absent_key(self, store):
        assert await store.exists("run/never-written") is False

    async def test_deleting_an_absent_key_reports_false_rather_than_raising(self, store):
        assert await store.delete("run/never-written") is False


class TestListing:
    async def test_keys_are_listed_under_their_prefix_in_order(self, store):
        for key in ("run/c", "run/a", "learning/b", "run/b"):
            await store.put(key, key.encode())
        assert await _collect(store, "run/") == ["run/a", "run/b", "run/c"]

    async def test_an_empty_prefix_lists_everything(self, store):
        await store.put("run/a", b"1")
        await store.put("learning/b", b"2")
        assert sorted(await _collect(store)) == ["learning/b", "run/a"]

    async def test_listing_an_empty_archive_yields_nothing(self, store):
        assert await _collect(store) == []

    async def test_a_deleted_key_leaves_the_listing(self, store):
        await store.put("run/gone", b"x")
        assert await store.delete("run/gone") is True
        assert await _collect(store, "run/") == []
        assert await store.exists("run/gone") is False


class TestContentAddressing:
    def test_the_digest_names_its_algorithm(self):
        """A bare hex digest cannot be re-verified after the algorithm changes,
        and "wrong digest" then reads identically to "different function"."""
        assert content_digest(b"x").startswith("sha256:")

    def test_identical_payloads_share_a_digest(self):
        assert content_digest(b"same") == content_digest(b"same")

    def test_different_payloads_do_not(self):
        assert content_digest(b"a") != content_digest(b"b")

    def test_verify_accepts_a_matching_record(self):
        payload = b"intact"
        ArchivedRecord(key="k", payload=payload, digest=content_digest(payload)).verify()

    def test_verify_rejects_a_corrupted_payload(self):
        """A store that returned truncated bytes would otherwise rehydrate a
        record that reads as authoritative — worse than a failed read, because
        the caller has no reason to doubt it."""
        record = ArchivedRecord(key="k", payload=b"truncat", digest=content_digest(b"truncated"))
        with pytest.raises(ArchiveDigestMismatchError) as excinfo:
            record.verify()
        assert excinfo.value.key == "k"
        assert excinfo.value.expected != excinfo.value.actual


class TestRecordArchivedError:
    def test_it_names_the_record_and_the_key_to_rehydrate_from(self):
        """The error is the whole interface for a caller that hits an archived
        record, so it has to carry enough to act on rather than just report."""
        error = RecordArchivedError("run-42", "run/run-42")
        assert error.record_id == "run-42"
        assert error.key == "run/run-42"
        assert "run/run-42" in str(error)


class TestBothImplementationsSatisfyTheProtocol:
    def test_the_filesystem_store_is_an_archive_store(self, filesystem_store):
        assert isinstance(filesystem_store, ArchiveStore)

    def test_the_s3_store_is_an_archive_store(self):
        if not S3_ENDPOINT:
            pytest.skip("MAISTRO_TEST_S3_ENDPOINT is unset")
        assert isinstance(_s3_store(), ArchiveStore)
