"""One suite over every extension install-record store (M9-B1, #952).

``InMemoryExtensionInstallStore`` is the reference; the SQLite durable twin
must agree with it on every rule, because the records are the audit trail the
install lifecycle (#953/#954) will be judged by: a twin that dropped the
manifest snapshot on readback or let a same-version/different-digest package
overwrite a row would break exactly the guarantees the issue exists for.

The restart test is the point of the durable leg: it closes the connection the
writes went through, opens a fresh one over the same database file, and reads
the same records back with the same trust evidence — the evidence is read, not
recomputed, and the read path needs no signing key.
"""

from __future__ import annotations

from typing import Any

import aiosqlite
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from extensions.extension_fixtures import (
    MANIFEST_BODY,
    PACKAGE_BYTES,
    install_bundle,
    make_identity,
    make_publisher,
    make_request,
    reidentify,
    sign,
)
from maistro.extensions.sqlite_store import SqliteExtensionInstallStore
from maistro.extensions.store import InMemoryExtensionInstallStore
from maistro.extensions.types import (
    ExtensionIdentityConflict,
    PublisherKeyConflict,
    UnknownPublisher,
    identity_key,
    manifest_snapshot,
)


class _SqliteLeg:
    """Owns the aiosqlite connection lifecycle for the durable leg."""

    def __init__(self, tmp_path: Any) -> None:
        self._path = tmp_path / "extension-installs.db"
        self._conn: aiosqlite.Connection | None = None

    async def store(self) -> SqliteExtensionInstallStore:
        conn = await aiosqlite.connect(self._path)
        self._conn = conn
        store = SqliteExtensionInstallStore(conn)
        await store.ensure_schema()
        return store

    async def stop(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def restart(self) -> SqliteExtensionInstallStore:
        """Close the connection the writes went through; open a fresh one."""
        await self.stop()
        return await self.store()


@pytest.fixture(params=["memory", "sqlite"])
async def store(request: pytest.FixtureRequest, tmp_path: Any) -> Any:
    """Every rule runs against both the reference and the durable twin."""
    if request.param == "memory":
        yield InMemoryExtensionInstallStore()
    else:
        leg = _SqliteLeg(tmp_path)
        yield await leg.store()
        await leg.stop()


async def test_publisher_registration_is_idempotent_for_the_same_key(
    store: InMemoryExtensionInstallStore | SqliteExtensionInstallStore,
) -> None:
    publisher, _ = make_publisher(publisher_id="pub-1")
    await store.register_publisher(publisher)
    await store.register_publisher(publisher)  # same identity: a no-op, not an error


async def test_publisher_key_rotation_is_refused(
    store: InMemoryExtensionInstallStore | SqliteExtensionInstallStore,
) -> None:
    publisher, _ = make_publisher(publisher_id="pub-1")
    # A fresh key under the same publisher id: the supply-chain move the
    # pinning exists to refuse.
    rotated, _ = make_publisher(publisher_id="pub-1")
    await store.register_publisher(publisher)
    with pytest.raises(PublisherKeyConflict):
        await store.register_publisher(rotated)


async def test_install_round_trips_every_field(
    store: InMemoryExtensionInstallStore | SqliteExtensionInstallStore,
) -> None:
    bundle = install_bundle()
    await store.register_publisher(bundle["publisher"])

    record = await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])
    read = await store.get_install(bundle["identity"])

    assert read == record
    assert read is not None  # narrowing for mypy
    assert read.identity == bundle["identity"]
    assert read.publisher == bundle["publisher"]
    assert read.manifest.body == MANIFEST_BODY
    assert read.manifest.sha256 == bundle["identity"].manifest_sha256
    assert read.evidence.verified is True
    assert read.evidence.subject_sha256 == bundle["identity"].package_sha256
    assert (await store.install_history("ext-tool")) == [record]


async def test_unknown_publisher_persists_nothing(
    store: InMemoryExtensionInstallStore | SqliteExtensionInstallStore,
) -> None:
    bundle = install_bundle()
    with pytest.raises(UnknownPublisher):
        await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])
    assert await store.install_history("ext-tool") == []


async def test_tampered_bytes_fail_before_the_record_exists(
    store: InMemoryExtensionInstallStore | SqliteExtensionInstallStore,
) -> None:
    bundle = install_bundle()
    await store.register_publisher(bundle["publisher"])
    with pytest.raises(Exception, match="digest"):
        await store.record_install(bundle["request"], package_bytes=PACKAGE_BYTES + b"tampered")
    assert await store.install_history("ext-tool") == []


async def test_foreign_signature_fails_before_the_record_exists(
    store: InMemoryExtensionInstallStore | SqliteExtensionInstallStore,
) -> None:
    bundle = install_bundle()
    impostor_identity = make_identity()  # honest identity…
    # …signed by a key that is not the registered publisher's.
    forged_key = Ed25519PrivateKey.generate()
    forged_request = make_request(impostor_identity, sign(forged_key, impostor_identity))
    await store.register_publisher(bundle["publisher"])
    with pytest.raises(Exception, match="signature"):
        await store.record_install(forged_request, package_bytes=PACKAGE_BYTES)
    assert await store.install_history("ext-tool") == []


async def test_same_version_different_digest_conflicts_and_persists_nothing(
    store: InMemoryExtensionInstallStore | SqliteExtensionInstallStore,
) -> None:
    first = install_bundle()
    await store.register_publisher(first["publisher"])
    installed = await store.record_install(first["request"], package_bytes=first["package_bytes"])

    other_bytes = b"a different package with the same version\n"
    other_identity = make_identity(package_bytes=other_bytes)
    # Signed by the *registered* publisher: the conflict must be about the
    # bytes, not about a foreign signature.
    conflicting = make_request(other_identity, sign(first["key"], other_identity))
    with pytest.raises(ExtensionIdentityConflict):
        await store.record_install(conflicting, package_bytes=other_bytes)

    history = await store.install_history("ext-tool")
    assert history == [installed]


async def test_identical_re_record_returns_the_original(
    store: InMemoryExtensionInstallStore | SqliteExtensionInstallStore,
) -> None:
    bundle = install_bundle()
    await store.register_publisher(bundle["publisher"])
    installed = await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])

    again = await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])

    assert again == installed
    assert len(await store.install_history("ext-tool")) == 1


async def test_history_orders_versions_and_get_install_matches_exact_identity(
    store: InMemoryExtensionInstallStore | SqliteExtensionInstallStore,
) -> None:
    # One publisher, two versions: reusing the bundle's key keeps both
    # registrations pinned to the same trust root.
    v1 = install_bundle(version="1.0.0")
    v2 = install_bundle(
        version="2.0.0",
        package_bytes=b"v2 payload\n",
        manifest_body="name: ext-tool\nversion: 2.0.0\nentry: main.py\n",
        signer=v1["key"],
    )
    for bundle in (v1, v2):
        await store.register_publisher(bundle["publisher"])
        await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])

    history = await store.install_history("ext-tool")
    assert [record.identity.semantic_version for record in history] == ["1.0.0", "2.0.0"]
    missing = await store.get_install(reidentify(v1["identity"], semantic_version="9.9.9"))
    assert missing is None
    found = await store.get_install(v2["identity"])
    assert found is not None and identity_key(found.identity) == identity_key(v2["identity"])


async def test_history_is_empty_for_unknown_extensions(
    store: InMemoryExtensionInstallStore | SqliteExtensionInstallStore,
) -> None:
    assert await store.install_history("never-installed") == []


async def test_manifest_swap_conflicts_via_identity(
    store: InMemoryExtensionInstallStore | SqliteExtensionInstallStore,
) -> None:
    """Same bytes, different manifest under one (name, version): refused."""
    bundle = install_bundle()
    await store.register_publisher(bundle["publisher"])
    await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])

    other_manifest = MANIFEST_BODY.replace("governed", "rogue")
    other_identity = reidentify(
        bundle["identity"],
        manifest_sha256=manifest_snapshot(other_manifest).sha256,
    )
    request = make_request(
        other_identity, sign(bundle["key"], other_identity), manifest_body=other_manifest
    )
    with pytest.raises(ExtensionIdentityConflict):
        await store.record_install(request, package_bytes=bundle["package_bytes"])
    assert len(await store.install_history("ext-tool")) == 1


async def test_restart_reads_the_same_records_with_the_same_evidence(
    tmp_path: Any,
) -> None:
    """The durable leg's point: evidence survives the process that wrote it."""
    leg = _SqliteLeg(tmp_path)
    store = await leg.store()
    bundle = install_bundle()
    await store.register_publisher(bundle["publisher"])
    installed = await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])

    reopened = await leg.restart()
    history = await reopened.install_history("ext-tool")
    assert history == [installed]
    read = await reopened.get_install(bundle["identity"])
    assert read is not None
    assert read.evidence == installed.evidence
    assert read.manifest == installed.manifest
    assert read.publisher == installed.publisher
    await leg.stop()


async def test_schema_creation_is_repeatable(tmp_path: Any) -> None:
    """ensure_schema twice must be a no-op the second time, not a crash."""
    leg = _SqliteLeg(tmp_path)
    store = await leg.store()
    await store.ensure_schema()
    bundle = install_bundle()
    await store.register_publisher(bundle["publisher"])
    await store.record_install(bundle["request"], package_bytes=bundle["package_bytes"])
    await store.ensure_schema()
    assert len(await store.install_history("ext-tool")) == 1
    await leg.stop()
