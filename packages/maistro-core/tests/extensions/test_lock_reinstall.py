"""Lock-driven reinstall through the real install store (M9-C2, #956).

These are the reproducibility acceptance tests, executed end-to-end with the
durable SQLite twin and real Ed25519 signatures: a resolved lock is fed to
:func:`materialize_lock`, every entry is fetched and driven through the
store's digest + signature verification, and the installed identity set must
equal the locked identity set — or the failure must be loud, complete (every
missing artifact named), and leave nothing installed or activated.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from extensions.extension_fixtures import (
    catalog_entry,
    install_bundle,
    make_publisher,
)
from maistro.extensions.resolution import (
    ExtensionCatalog,
    ExtensionDependency,
    LockArtifacts,
    LockEntry,
    LockState,
    MissingLockArtifacts,
    RootRequest,
    diff_locks,
    materialize_lock,
    resolve_lock,
)
from maistro.extensions.sqlite_store import SqliteExtensionInstallStore
from maistro.extensions.store import ActivationCallback, InMemoryExtensionInstallStore
from maistro.extensions.types import (
    InstallRecord,
    PackageDigestMismatch,
    PackageIdentity,
    UnknownPublisher,
    identity_key,
)

IdentityKey = tuple[str, str, str, str]

#: tool-a requires lib-b and optionally wants opt-c; the lib-b version is a
#: parameter so the update test can lock two different identities of it.
_SPECS: dict[str, tuple[str, tuple[tuple[str, str, bool], ...]]] = {
    "tool-a": ("1.0.0", (("lib-b", ">=1.0.0", True), ("opt-c", ">=1.0.0", False))),
    "lib-b": ("1.2.0", ()),
    "opt-c": ("1.0.0", ()),
}


class _RecordingFetcher:
    """Serves artifacts from a map and records every entry it was asked for."""

    def __init__(self, artifacts: dict[IdentityKey, LockArtifacts | None]) -> None:
        self._artifacts = artifacts
        self.requested: list[IdentityKey] = []

    async def fetch_lock_artifact(self, entry: LockEntry) -> LockArtifacts | None:
        key = entry.sort_key()
        self.requested.append(key)
        return self._artifacts.get(key)


class _ActivationSpy:
    """Records activation callbacks; a call here means an install happened."""

    def __init__(self) -> None:
        self.activated: list[PackageIdentity] = []

    def callback(self) -> ActivationCallback:
        def activate(record: InstallRecord) -> None:
            self.activated.append(record.identity)

        return activate


def _resolve_ecosystem(
    signer: Ed25519PrivateKey, *, lib_b_version: str = "1.2.0"
) -> tuple[LockState, dict[IdentityKey, LockArtifacts]]:
    """The locked ecosystem: lock state plus the artifact map serving it.

    One publisher signs every entry, so the store needs a single pinned
    trust root; ``lib_b_version`` lets a caller lock a different identity of
    lib-b against the same ranges (the update scenario).
    """
    specs = dict(_SPECS)
    specs["lib-b"] = (lib_b_version, _SPECS["lib-b"][1])
    bundles = {
        name: install_bundle(name=name, version=version, publisher_id="pub-1", signer=signer)
        for name, (version, _deps) in specs.items()
    }
    artifacts: dict[IdentityKey, LockArtifacts] = {}
    for bundle in bundles.values():
        identity: PackageIdentity = bundle["identity"]
        key: IdentityKey = identity_key(identity)
        artifacts[key] = LockArtifacts(
            package_bytes=bundle["package_bytes"], manifest_body=bundle["manifest_body"]
        )
    catalog = ExtensionCatalog(
        entries=(
            catalog_entry(
                bundles["tool-a"],
                dependencies=tuple(
                    ExtensionDependency(target=t, range_text=r, required=req)
                    for t, r, req in specs["tool-a"][1]
                ),
            ),
            catalog_entry(bundles["lib-b"]),
            catalog_entry(bundles["opt-c"]),
        )
    )
    lock = resolve_lock([RootRequest(extension_name="tool-a")], catalog)
    assert len(lock.entries) == 3, "the ecosystem must resolve to all three extensions"
    return lock, artifacts


def _fresh_store(
    db_dir: Path, signer: Ed25519PrivateKey
) -> tuple[SqliteExtensionInstallStore, aiosqlite.Connection]:
    """A durable store over a fresh database, with the publisher registered."""

    async def build() -> tuple[SqliteExtensionInstallStore, aiosqlite.Connection]:
        conn = await aiosqlite.connect(db_dir / "installs.db")
        store = SqliteExtensionInstallStore(conn)
        await store.ensure_schema()
        publisher, _key = make_publisher(publisher_id="pub-1", signer=signer)
        await store.register_publisher(publisher)
        return store, conn

    return asyncio.run(build())


async def _all_history(store: SqliteExtensionInstallStore) -> list[InstallRecord]:
    """Every record across the ecosystem's extensions (caller runs the loop)."""
    history: list[InstallRecord] = []
    for name in ("tool-a", "lib-b", "opt-c"):
        history.extend(await store.install_history(name))
    return history


def test_materialize_recreates_the_locked_identity_set(tmp_path: Path) -> None:
    signer = Ed25519PrivateKey.generate()
    lock, artifacts = _resolve_ecosystem(signer)
    store, conn = _fresh_store(tmp_path, signer)
    fetcher = _RecordingFetcher(artifacts)
    spy = _ActivationSpy()

    async def run() -> list[InstallRecord]:
        try:
            return await materialize_lock(lock, store, fetcher, activate=spy.callback())
        finally:
            await conn.close()

    records = asyncio.run(run())
    assert {identity_key(record.identity) for record in records} == lock.identity_keys()
    assert all(record.evidence.verified for record in records)
    # Activation ran exactly once per entry, and the store saw every fetch —
    # the whole set was fetched and verified before anything was activated.
    assert len(spy.activated) == len(lock.entries)
    assert len(fetcher.requested) == len(lock.entries)


def test_reinstall_from_the_same_lock_is_idempotent(tmp_path: Path) -> None:
    signer = Ed25519PrivateKey.generate()
    lock, artifacts = _resolve_ecosystem(signer)
    store, conn = _fresh_store(tmp_path, signer)

    async def run() -> tuple[list[InstallRecord], list[InstallRecord]]:
        try:
            first = await materialize_lock(lock, store, _RecordingFetcher(artifacts))
            second = await materialize_lock(lock, store, _RecordingFetcher(artifacts))
            return first, second
        finally:
            await conn.close()

    first, second = asyncio.run(run())
    assert [identity_key(r.identity) for r in first] == [identity_key(r.identity) for r in second]


def test_missing_artifacts_fail_explicitly_naming_every_gap(tmp_path: Path) -> None:
    signer = Ed25519PrivateKey.generate()
    lock, artifacts = _resolve_ecosystem(signer)
    # Two of three artifacts are gone (a purged catalog, a lost mirror).
    partial = {key: value for key, value in artifacts.items() if key[0] not in {"lib-b", "opt-c"}}
    store, conn = _fresh_store(tmp_path, signer)
    spy = _ActivationSpy()

    async def run() -> None:
        try:
            with pytest.raises(MissingLockArtifacts) as excinfo:
                await materialize_lock(
                    lock, store, _RecordingFetcher(partial), activate=spy.callback()
                )
            message = str(excinfo.value)
            assert "lib-b" in message and "opt-c" in message
            assert "Nothing was installed or activated" in message
            # Nothing leaked into the store before the raise.
            assert await _all_history(store) == []
            assert spy.activated == []
        finally:
            await conn.close()

    asyncio.run(run())


def test_restart_on_a_fresh_host_recreates_the_same_extension_set(tmp_path: Path) -> None:
    signer = Ed25519PrivateKey.generate()
    lock, artifacts = _resolve_ecosystem(signer)

    async def install_on(host: Path) -> set[IdentityKey]:
        host.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(host / "installs.db")
        try:
            store = SqliteExtensionInstallStore(conn)
            await store.ensure_schema()
            publisher, _key = make_publisher(publisher_id="pub-1", signer=signer)
            await store.register_publisher(publisher)
            records = await materialize_lock(lock, store, _RecordingFetcher(artifacts))
            return {identity_key(record.identity) for record in records}
        finally:
            await conn.close()

    # Two hosts, one lock file: the serialized lock is the whole contract.
    rebuilt = LockState.from_json(lock.to_json())
    first = asyncio.run(install_on(tmp_path / "host-a"))
    second = asyncio.run(install_on(tmp_path / "host-b"))
    assert first == second == rebuilt.identity_keys() == lock.identity_keys()


def test_tampered_artifact_fails_before_any_activation(tmp_path: Path) -> None:
    signer = Ed25519PrivateKey.generate()
    lock, artifacts = _resolve_ecosystem(signer)
    # Corrupt the *last* entry the batch will verify. An earlier victim would
    # pass vacuously — nothing is persisted or activated before the failure —
    # and hide a partial install; the last entry is the one that can only
    # stay atomic if the batch really is all-or-nothing.
    victim_key = lock.entries[-1].sort_key()
    original = artifacts[victim_key]
    assert original is not None
    tampered = {
        **artifacts,
        victim_key: LockArtifacts(
            package_bytes=b"tampered bytes\n", manifest_body=original.manifest_body
        ),
    }
    store, conn = _fresh_store(tmp_path, signer)
    spy = _ActivationSpy()

    async def run() -> None:
        try:
            with pytest.raises(PackageDigestMismatch):
                await materialize_lock(
                    lock, store, _RecordingFetcher(tampered), activate=spy.callback()
                )
            assert spy.activated == []
            # The lock cannot smuggle different bytes: the batch verified the
            # complete fetched set first, so nothing at all was recorded or
            # activated — not even the entries that precede the victim.
            assert await _all_history(store) == []
        finally:
            await conn.close()

    asyncio.run(run())


def test_unregistered_publisher_fails_closed(tmp_path: Path) -> None:
    signer = Ed25519PrivateKey.generate()
    lock, artifacts = _resolve_ecosystem(signer)
    store = InMemoryExtensionInstallStore()
    spy = _ActivationSpy()

    async def run() -> None:
        with pytest.raises(UnknownPublisher):
            await materialize_lock(
                lock, store, _RecordingFetcher(artifacts), activate=spy.callback()
            )
        assert spy.activated == []
        assert await store.install_history("tool-a") == []

    asyncio.run(run())


def test_update_reinstall_keeps_both_identities_in_history(tmp_path: Path) -> None:
    """Install/update integration: an upgrade is a new identity, not an edit."""
    signer = Ed25519PrivateKey.generate()
    old_lock, old_artifacts = _resolve_ecosystem(signer, lib_b_version="1.2.0")
    new_lock, new_artifacts = _resolve_ecosystem(signer, lib_b_version="1.5.0")
    diff = diff_locks(old_lock, new_lock)
    assert len(diff.changed) == 1
    assert diff.changed[0][0].semantic_version == "1.2.0"
    assert diff.changed[0][1].semantic_version == "1.5.0"

    store, conn = _fresh_store(tmp_path, signer)

    async def run() -> None:
        try:
            await materialize_lock(old_lock, store, _RecordingFetcher(old_artifacts))
            await materialize_lock(new_lock, store, _RecordingFetcher(new_artifacts))
            history = await store.install_history("lib-b")
            # The append-only store keeps both installed versions — the lock
            # moved, history was not rewritten.
            assert {record.identity.semantic_version for record in history} == {"1.2.0", "1.5.0"}
            old_entry = old_lock.get("lib-b")
            new_entry = new_lock.get("lib-b")
            assert old_entry is not None and new_entry is not None
            assert await store.get_install(old_entry.identity) is not None
            assert await store.get_install(new_entry.identity) is not None
        finally:
            await conn.close()

    asyncio.run(run())


def test_publisher_identity_type_round_trips_through_the_store_seam() -> None:
    # Guard the fixture seam the reinstall tests rely on: make_publisher
    # returns the identity for the key it is pinned to.
    signer = Ed25519PrivateKey.generate()
    publisher, key = make_publisher(publisher_id="pub-1", signer=signer)
    assert (
        publisher.signing_public_key
        == key.public_key()
        .public_bytes(
            Encoding.Raw,
            PublicFormat.Raw,
        )
        .hex()
    )
