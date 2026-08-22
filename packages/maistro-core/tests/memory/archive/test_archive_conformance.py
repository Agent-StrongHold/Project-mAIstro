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

import asyncio
import os
import stat

import pytest

from maistro.memory.archive import FilesystemArchiveStore
from maistro.memory.archive.filesystem import ArchiveKeyError
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


class TestAttestedReads:
    """A digest is evidence only when it comes from somewhere other than the
    bytes it judges (Codex review, #179)."""

    async def test_the_callers_digest_is_checked(self, store):
        payload = b"authoritative"
        digest = await store.put("run/attested", payload)
        record = await store.get("run/attested", expected_digest=digest)
        assert record.payload == payload
        assert record.digest == digest

    async def test_a_wrong_expectation_is_rejected(self, store):
        """The stub row and the object disagreeing is a real condition — a
        restored bucket, a half-run migration — and must not read as success."""
        await store.put("run/attested", b"authoritative")
        with pytest.raises(ArchiveDigestMismatchError) as excinfo:
            await store.get("run/attested", expected_digest=content_digest(b"something else"))
        assert excinfo.value.key == "run/attested"


class TestFilesystemCorruptionIsCaught:
    """The filesystem backend stores the payload and nothing else, so it cannot
    be its own witness. Before this, `get` computed the digest from whatever was
    on disk and verified it against itself — a check that could not fail, on the
    one failure mode a cold tier exists to survive."""

    async def test_a_truncated_payload_fails_the_callers_digest(self, filesystem_store):
        digest = await filesystem_store.put("run/rot", b"the whole record")
        path = filesystem_store.root / "run" / "rot"
        path.write_bytes(b"the whole")  # bit rot, a partial restore, a bad sector

        with pytest.raises(ArchiveDigestMismatchError):
            await filesystem_store.get("run/rot", expected_digest=digest)

    async def test_an_unattested_read_reports_the_bytes_it_actually_has(self, filesystem_store):
        """Without an expectation there is nothing to check against, and the
        honest answer is a digest that describes the bytes rather than one that
        pretends to vouch for them."""
        await filesystem_store.put("run/rot", b"the whole record")
        (filesystem_store.root / "run" / "rot").write_bytes(b"the whole")

        record = await filesystem_store.get("run/rot")
        assert record.digest == content_digest(b"the whole")


class TestFilesystemDurability:
    async def test_the_payload_and_its_directory_entry_are_both_flushed(
        self, filesystem_store, monkeypatch
    ):
        """`put` returning is the archive sweep's cue to drop the source row, so
        the bytes must be on the platter by then. `write` + `rename` gives
        atomic visibility and no durability at all — a crash in that window
        loses the object *and* the row it replaced.

        Asserting on `fsync` calls is implementation-shaped, deliberately: the
        black-box alternative is pulling the machine's power cord.
        """
        import os as os_module

        synced: list[str] = []
        real_fsync = os_module.fsync

        def _recording_fsync(fd: int) -> None:
            synced.append("dir" if os_module.fstat(fd).st_mode & 0o040000 else "file")
            real_fsync(fd)

        monkeypatch.setattr(os_module, "fsync", _recording_fsync)
        await filesystem_store.put("run/durable", b"payload")

        assert "file" in synced, "the payload was never flushed"
        assert "dir" in synced, "the rename was never flushed; the object can be unreachable"


class TestFilesystemConcurrency:
    async def test_identical_concurrent_writes_both_succeed(self, filesystem_store):
        """Two sweeps retrying the same record derive the same digest by
        construction, so a digest-named staging file is exactly the case that
        collides: the first `replace` unlinks it and the second raised
        FileNotFoundError — on an operation documented as idempotent."""
        payload = b"the same bytes from two workers"
        digests = await asyncio.gather(
            *(filesystem_store.put("run/raced", payload) for _ in range(12))
        )

        assert len(set(digests)) == 1
        assert (await filesystem_store.get("run/raced")).payload == payload
        assert await _collect(filesystem_store) == ["run/raced"]


class TestFilesystemPermissions:
    async def test_the_tree_is_owner_only(self, filesystem_store):
        """Archived Runs and memory are the same records PostgreSQL held. Under
        the usual 022 umask this tree came out 0755/0644 — readable by every
        local account on a multi-user host."""
        await filesystem_store.put("run/private", b"secret-ish")

        payload = filesystem_store.root / "run" / "private"
        assert stat.S_IMODE(payload.stat().st_mode) == 0o600
        for directory in (filesystem_store.root, payload.parent):
            assert stat.S_IMODE(directory.stat().st_mode) & 0o077 == 0, directory


class TestListingIsStreamedAndOrdered:
    async def test_a_key_ending_in_tmp_is_not_hidden(self, store):
        """`put`, `get` and `exists` all honoured such a key while `list_keys`
        filtered it out by suffix — a listing that was quietly not a listing.
        The staging namespace is now one the key validator refuses instead."""
        await store.put("run/build.tmp", b"x")
        assert await _collect(store, "run/") == ["run/build.tmp"]

    async def test_staging_names_are_refused_rather_than_filtered(self, filesystem_store):
        with pytest.raises(ArchiveKeyError):
            await filesystem_store.put("run/.staging", b"x")

    async def test_keys_come_out_in_full_key_order(self, filesystem_store):
        """The order a sorted list of keys would give, which is not the order a
        per-directory sort of bare names gives: `.` (0x2E) precedes `/` (0x2F),
        so `a.txt` sorts before `a/b` even though `a` sorts before `a.txt`."""
        for key in ("a/b", "a.txt", "ab/c"):
            await filesystem_store.put(key, key.encode())

        assert await _collect(filesystem_store) == sorted(["a/b", "a.txt", "ab/c"])

    async def test_the_first_key_arrives_without_walking_the_archive(
        self, filesystem_store, monkeypatch
    ):
        """The signature promised streaming and the implementation collected
        every key into a list and sorted it before yielding anything — the gate
        that works until the archive is big enough to matter."""
        from maistro.memory.archive import filesystem as fs_module

        for kind in ("aaa", "bbb", "ccc", "ddd", "eee"):
            for index in range(3):
                await filesystem_store.put(f"{kind}/{index}", b"x")

        scanned: list[str] = []
        real_scan = fs_module._scan

        def _recording_scan(directory):
            scanned.append(str(directory))
            return real_scan(directory)

        monkeypatch.setattr(fs_module, "_scan", _recording_scan)

        keys = filesystem_store.list_keys()
        first = await anext(keys)
        await keys.aclose()

        assert first == "aaa/0"
        assert scanned == [str(filesystem_store.root), str(filesystem_store.root / "aaa")], (
            f"reached beyond the first match: {scanned}"
        )

    async def test_directories_that_cannot_match_are_not_descended(
        self, filesystem_store, monkeypatch
    ):
        from maistro.memory.archive import filesystem as fs_module

        for key in ("run/a", "learning/b", "outcome/c"):
            await filesystem_store.put(key, b"x")

        scanned: list[str] = []
        real_scan = fs_module._scan
        monkeypatch.setattr(fs_module, "_scan", lambda d: (scanned.append(d.name), real_scan(d))[1])

        assert await _collect(filesystem_store, "run/") == ["run/a"]
        assert "learning" not in scanned
        assert "outcome" not in scanned

    async def test_a_symlinked_directory_is_not_listed(self, filesystem_store, tmp_path):
        """`_path_for` refuses a key that resolves outside the root, so a
        followed symlink would have put keys in the listing that every read of
        them rejects — the same listing-that-is-not-a-listing, from the other
        end."""
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        (outside / "secret").write_bytes(b"not ours")
        await filesystem_store.put("run/a", b"ours")
        (filesystem_store.root / "escape").symlink_to(outside)

        assert await _collect(filesystem_store) == ["run/a"]


class TestS3NamespaceIsolation:
    async def test_a_neighbouring_prefix_is_not_listed_as_this_stores_keys(self):
        """`Prefix=self._prefix` is a string match, so a store rooted at
        `archive` also listed `archive-old/run` — and `_strip_prefix` then cut a
        fixed number of characters off it and reported `old/run`, inventing a
        record that does not exist."""
        if not S3_ENDPOINT:
            pytest.skip("MAISTRO_TEST_S3_ENDPOINT is unset; the S3 leg needs a real server")
        from maistro.memory.archive import s3_archive_store

        bucket = f"archive-test-{os.urandom(6).hex()}"
        common = {
            "bucket": bucket,
            "endpoint_url": S3_ENDPOINT,
            "region_name": "us-east-1",
            "access_key_id": os.environ.get("MAISTRO_TEST_S3_ACCESS_KEY", "minioadmin"),
            "secret_access_key": os.environ.get("MAISTRO_TEST_S3_SECRET_KEY", "minioadmin"),
        }
        mine = s3_archive_store(prefix="archive", **common)
        neighbour = s3_archive_store(prefix="archive-old", **common)
        await mine.ensure_bucket()

        await mine.put("run/a", b"mine")
        await neighbour.put("run/b", b"theirs")

        assert await _collect(mine) == ["run/a"]

    async def test_a_bucket_is_created_in_a_non_default_region(self):
        """AWS rejects a bare `create_bucket` outside us-east-1 and requires the
        region as a LocationConstraint, so first-run setup failed for every
        standard regional deployment."""
        if not S3_ENDPOINT:
            pytest.skip("MAISTRO_TEST_S3_ENDPOINT is unset; the S3 leg needs a real server")
        from maistro.memory.archive import s3_archive_store

        store = s3_archive_store(
            bucket=f"archive-test-{os.urandom(6).hex()}",
            endpoint_url=S3_ENDPOINT,
            region_name="eu-west-1",
            access_key_id=os.environ.get("MAISTRO_TEST_S3_ACCESS_KEY", "minioadmin"),
            secret_access_key=os.environ.get("MAISTRO_TEST_S3_SECRET_KEY", "minioadmin"),
        )
        await store.ensure_bucket()

        await store.put("run/regional", b"x")
        assert (await store.get("run/regional")).payload == b"x"


class TestS3CredentialsAreExplicitOrAbsent:
    """Half a credential silently became no credential, and boto fell back to
    the host's ambient chain — so a malformed secret configuration archived into
    whatever account an instance role or developer profile pointed at.

    These need no server but they do need the SDK, since they construct the
    store. `importorskip` rather than the `S3_ENDPOINT` gate the rest of the S3
    tests use: the distinction is the dependency, not the endpoint. They still
    run in CI — the `archive` job installs `maistro-core[s3]` — they are only
    skipped in the plain `test` job, which deliberately runs a base install.
    """

    @pytest.mark.parametrize(
        ("access_key_id", "secret_access_key", "missing"),
        [("AKIA-something", None, "secret_access_key"), (None, "a-secret", "access_key_id")],
    )
    def test_half_a_pair_is_rejected(self, access_key_id, secret_access_key, missing):
        pytest.importorskip("aioboto3")
        from maistro.memory.archive import s3_archive_store

        with pytest.raises(ValueError, match=missing):
            s3_archive_store(
                bucket="b", access_key_id=access_key_id, secret_access_key=secret_access_key
            )

    def test_neither_is_accepted_as_a_deliberate_choice(self):
        """Omitting both is how a deployment asks for the instance role."""
        pytest.importorskip("aioboto3")
        from maistro.memory.archive import s3_archive_store

        assert s3_archive_store(bucket="b") is not None


class TestAMissingBucketIsAnOutageNotAMiss:
    async def test_get_against_an_absent_bucket_does_not_report_a_missing_record(self):
        """Folding `NoSuchBucket` into the missing-object codes made the archive
        report that a record is not there because it could not look — the one
        answer this protocol forbids."""
        if not S3_ENDPOINT:
            pytest.skip("MAISTRO_TEST_S3_ENDPOINT is unset; the S3 leg needs a real server")
        from botocore.exceptions import ClientError

        from maistro.memory.archive import s3_archive_store

        store = s3_archive_store(
            bucket=f"never-created-{os.urandom(6).hex()}",
            endpoint_url=S3_ENDPOINT,
            region_name="us-east-1",
            access_key_id=os.environ.get("MAISTRO_TEST_S3_ACCESS_KEY", "minioadmin"),
            secret_access_key=os.environ.get("MAISTRO_TEST_S3_SECRET_KEY", "minioadmin"),
        )

        with pytest.raises(ClientError):
            await store.get("run/anything")
        with pytest.raises(ClientError):
            await store.exists("run/anything")


class TestBothImplementationsSatisfyTheProtocol:
    def test_the_filesystem_store_is_an_archive_store(self, filesystem_store):
        assert isinstance(filesystem_store, ArchiveStore)

    def test_the_s3_store_is_an_archive_store(self):
        if not S3_ENDPOINT:
            pytest.skip("MAISTRO_TEST_S3_ENDPOINT is unset")
        assert isinstance(_s3_store(), ArchiveStore)
