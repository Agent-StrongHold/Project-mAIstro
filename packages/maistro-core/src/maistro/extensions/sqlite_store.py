"""Durable SQLite twin of the extension install-record store (M9-B1, #952).

Same convention as ``memory/working/sqlite_store.py``: an injected
``aiosqlite`` connection, plain typed columns for everything that filters or
orders, a JSON payload column the record round-trips through, and an
``ensure_schema()`` that runs through the shared ``serialized_schema_upgrade``
discipline. One connection, one operation lock.

Two tables, both append-only — the store issues no ``UPDATE`` and no
``DELETE``, because an install record is evidence:

* ``extension_publishers`` — one row per publisher identity, pinned at first
  registration. The row is written once; re-registration either matches the
  pinned key (no-op) or is refused, so the trust root a historical record was
  verified against cannot drift under it.
* ``extension_installs`` — one row per installed-version identity, keyed by
  ``(extension_name, semantic_version, package_sha256)``. That primary key is
  what makes two packages with the same semantic version but different digests
  two distinct rows instead of one silently overwritten one; the
  ``(name, version)``-different-digest case is refused outright by the shared
  resolve rules before an insert is attempted.

Retention is declared in ``quality/durable-table-retention.json`` as
``indefinite_by_decision`` (issue #952): the epic requires history to remain
queryable after disable/remove, so no purge path exists by design.

Trust evidence is stored with the row and read back from it — the read path
runs no crypto, holds no keys, and consults no catalog, so the evidence stays
queryable after the signing key or catalog that produced it is gone.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from maistro.extensions.store import ActivationCallback, _ensure_same_key, resolve_install
from maistro.extensions.types import (
    InstallRecord,
    InstallRequest,
    PackageIdentity,
    PublisherIdentity,
    identity_key,
    publisher_from_json,
    publisher_to_json,
    record_from_json,
    record_to_json,
)
from maistro.sqlite_schema import serialized_schema_upgrade

if TYPE_CHECKING:  # pragma: no cover - typing only
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS extension_publishers (
    publisher_id TEXT PRIMARY KEY,
    signing_key_fingerprint TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    payload TEXT NOT NULL
)
"""

_INSTALLS_SCHEMA = """
CREATE TABLE IF NOT EXISTS extension_installs (
    extension_name TEXT NOT NULL,
    semantic_version TEXT NOT NULL,
    package_sha256 TEXT NOT NULL,
    installed_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (extension_name, semantic_version, package_sha256)
)
"""

_INSTALLS_INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_extension_installs_name_time
    ON extension_installs (extension_name, installed_at)
"""


class SqliteExtensionInstallStore:
    """The durable twin. Must agree with :class:`InMemoryExtensionInstallStore`
    on every rule the conformance suite exercises."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        """Create the tables; safe to call concurrently and repeatedly."""
        async with self._lock, serialized_schema_upgrade(self._conn):
            for script in (_SCHEMA, _INSTALLS_SCHEMA, _INSTALLS_INDEX_SCHEMA):
                await self._conn.execute(script)
            await self._conn.commit()

    async def register_publisher(self, publisher: PublisherIdentity) -> None:
        """Pin a publisher identity; refuse a key change under the same id."""
        async with self._lock:
            cursor = await self._conn.execute(
                "SELECT payload FROM extension_publishers WHERE publisher_id = ?",
                (publisher.publisher_id,),
            )
            row = await cursor.fetchone()
            if row is not None:
                _ensure_same_key(publisher_from_json(str(row[0])), publisher)
                return
            await self._conn.execute(
                "INSERT INTO extension_publishers "
                "(publisher_id, signing_key_fingerprint, registered_at, payload) "
                "VALUES (?, ?, ?, ?)",
                (
                    publisher.publisher_id,
                    publisher.signing_key_fingerprint,
                    publisher.registered_at.isoformat(),
                    publisher_to_json(publisher),
                ),
            )
            await self._conn.commit()

    async def record_install(
        self,
        request: InstallRequest,
        *,
        package_bytes: bytes,
        activate: ActivationCallback | None = None,
    ) -> InstallRecord:
        """Verify, record, then activate — the same rules as the reference."""
        async with self._lock:
            history = await self._history_in_lock(request.identity.extension_name)
            resolved = resolve_install(
                await self._publishers_in_lock(),
                history,
                request,
                package_bytes=package_bytes,
                now=datetime.now(UTC),
                install_id=uuid.uuid4().hex,
            )
            if resolved is None:
                return self._existing_in_lock(history, request.identity)
            await self._conn.execute(
                "INSERT INTO extension_installs "
                "(extension_name, semantic_version, package_sha256, installed_at, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    resolved.identity.extension_name,
                    resolved.identity.semantic_version,
                    resolved.identity.package_sha256,
                    resolved.installed_at.isoformat(),
                    record_to_json(resolved),
                ),
            )
            await self._conn.commit()
        if activate is not None:
            activate(resolved)
        return resolved

    async def record_installs(
        self,
        installs: Sequence[tuple[InstallRequest, bytes]],
        *,
        activate: ActivationCallback | None = None,
    ) -> list[InstallRecord]:
        """Verify the whole batch, then record all in one commit, then activate.

        Same rules as :meth:`record_install`, with a stronger guarantee: every
        digest, signature, and identity check runs — each entry against the
        persisted history plus the records already resolved in this batch —
        before the first INSERT. A failure anywhere commits nothing and never
        invokes ``activate``, so a batch cannot land half-installed.
        """
        async with self._lock:
            publishers = await self._publishers_in_lock()
            pending: list[InstallRecord] = []
            resolved: list[InstallRecord] = []
            for request, package_bytes in installs:
                prior = [
                    *await self._history_in_lock(request.identity.extension_name),
                    *(
                        record
                        for record in pending
                        if record.identity.extension_name == request.identity.extension_name
                    ),
                ]
                record = resolve_install(
                    publishers,
                    prior,
                    request,
                    package_bytes=package_bytes,
                    now=datetime.now(UTC),
                    install_id=uuid.uuid4().hex,
                )
                if record is None:
                    resolved.append(self._existing_in_lock(prior, request.identity))
                else:
                    pending.append(record)
                    resolved.append(record)
            for record in pending:
                await self._conn.execute(
                    "INSERT INTO extension_installs "
                    "(extension_name, semantic_version, package_sha256, installed_at, payload) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        record.identity.extension_name,
                        record.identity.semantic_version,
                        record.identity.package_sha256,
                        record.installed_at.isoformat(),
                        record_to_json(record),
                    ),
                )
            await self._conn.commit()
        if activate is not None:
            for record in pending:
                activate(record)
        return resolved

    async def install_history(self, extension_name: str) -> list[InstallRecord]:
        """All install records for one extension, oldest first."""
        async with self._lock:
            return await self._history_in_lock(extension_name)

    async def get_install(self, identity: PackageIdentity) -> InstallRecord | None:
        """The record for an exact installed-version identity, or ``None``."""
        async with self._lock:
            wanted = identity_key(identity)
            for record in await self._history_in_lock(identity.extension_name):
                if identity_key(record.identity) == wanted:
                    return record
            return None

    async def all_installs(self) -> list[InstallRecord]:
        """Every install record across every extension, oldest first per name."""
        async with self._lock:
            cursor = await self._conn.execute(
                "SELECT payload FROM extension_installs ORDER BY extension_name, installed_at, payload"
            )
            rows = await cursor.fetchall()
            return [record_from_json(str(row[0])) for row in rows]

    async def _publishers_in_lock(self) -> dict[str, PublisherIdentity]:
        """Every pinned publisher identity, keyed by id (caller holds the lock)."""
        cursor = await self._conn.execute("SELECT payload FROM extension_publishers")
        rows = await cursor.fetchall()
        publishers = [publisher_from_json(str(row[0])) for row in rows]
        return {publisher.publisher_id: publisher for publisher in publishers}

    async def _history_in_lock(self, extension_name: str) -> list[InstallRecord]:
        """One extension's records, oldest first (caller holds the lock)."""
        cursor = await self._conn.execute(
            "SELECT payload FROM extension_installs WHERE extension_name = ? "
            "ORDER BY installed_at, payload",
            (extension_name,),
        )
        rows = await cursor.fetchall()
        return [record_from_json(str(row[0])) for row in rows]

    @staticmethod
    def _existing_in_lock(history: list[InstallRecord], identity: PackageIdentity) -> InstallRecord:
        """The already-persisted record for ``identity`` (idempotent path)."""
        wanted = identity_key(identity)
        for record in history:
            if identity_key(record.identity) == wanted:
                return record
        raise AssertionError("idempotent re-record matched no persisted row")
