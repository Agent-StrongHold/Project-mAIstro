"""Durable homes for extension registry records and activation state (#939).

Two stores share this module, one per layer of the M9-B epic:

- **M9-B1 install-record store (issue #952)**: append-only records of who
  published what, and what was installed. There is no update and no delete: an
  install record is evidence, and evidence is not rewritten. Every record
  snapshots the publisher identity, digest, signature, manifest, catalog
  provenance and trust evidence from install time. Verification runs before
  persistence and before the ``activate`` callback is invoked, so a tampered
  package fails before any extension code is imported. Identity discipline:
  an exact re-record of an installed identity is idempotent; a *different*
  package under an installed ``(extension_name, semantic_version)`` raises
  :class:`~maistro.extensions.types.ExtensionIdentityConflict`.
- **M9-B2 activation store (issue #953)**: the persistence seam the
  activation state machine speaks to — lifecycle records plus their audited
  transition trail. The in-memory implementation keeps full history for the
  process lifetime, explicitly not a restart-surviving store; a PostgreSQL
  backend can arrive behind the same protocol without touching the machine.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from maistro.extensions.types import (
    ExtensionIdentityConflict,
    ExtensionInstallRecord,
    ExtensionRegistryError,
    ExtensionScope,
    ExtensionState,
    ExtensionTransition,
    InstallRecord,
    InstallRequest,
    PackageIdentity,
    PublisherIdentity,
    PublisherKeyConflict,
    TrustEvidence,
    UnknownPublisher,
    identity_key,
    manifest_snapshot,
)
from maistro.extensions.verify import verify_package_bytes, verify_package_signature

# --------------------------------------------------------------------------
# M9-B1: install-record store (issue #952)
# --------------------------------------------------------------------------

#: The trust policy an install-time verification is recorded under. One value,
#: on purpose: this store records exactly one kind of check, and the string is
#: what auditors match evidence rows on.
TRUST_POLICY = "ed25519-canonical-install:v1"

#: Invoked with the persisted record only after verification and persistence
#: succeeded. This is the code-import/activation boundary: verification fails
#: before it, never after.
ActivationCallback = Callable[[InstallRecord], None]


@runtime_checkable
class ExtensionInstallStore(Protocol):
    """Durable record of who published what, and what was installed.

    The same protocol for the in-memory reference and the SQLite durable twin;
    the conformance suite holds the twins to identical behavior.
    """

    async def register_publisher(self, publisher: PublisherIdentity) -> None:
        """Pin a publisher identity. Refuses a key change under the same id."""
        ...

    async def record_install(
        self,
        request: InstallRequest,
        *,
        package_bytes: bytes,
        activate: ActivationCallback | None = None,
    ) -> InstallRecord:
        """Verify, then durably record one install, then activate.

        Raises before persisting — and before ``activate`` runs — on any
        verification or identity failure. Returns the immutable record.
        """
        ...

    async def record_installs(
        self,
        installs: Sequence[tuple[InstallRequest, bytes]],
        *,
        activate: ActivationCallback | None = None,
    ) -> list[InstallRecord]:
        """Atomic batch form of :meth:`record_install`.

        Verification and identity rules run for *every* entry first — each
        against the store's history plus the records already resolved in this
        batch — before the first record is persisted. Any failure raises
        having persisted nothing and invoked ``activate`` zero times, so a
        batch can never land half-installed. On success every record is
        persisted, then ``activate`` runs once per newly persisted record in
        batch order; idempotent re-records return the existing record without
        re-activating, exactly as the single-record path does.
        """
        ...

    async def install_history(self, extension_name: str) -> list[InstallRecord]:
        """All install records for one extension, oldest first."""
        ...

    async def get_install(self, identity: PackageIdentity) -> InstallRecord | None:
        """The record for an exact installed-version identity, or ``None``."""
        ...

    async def all_installs(self) -> list[InstallRecord]:
        """Every install record across every extension, oldest first per name.

        The whole installed lock state in one read — the input surface the
        upgrade preflight evaluates. Records from different extensions are
        ordered by extension name; records for one extension keep install
        order.
        """
        ...


def make_trust_evidence(
    publisher: PublisherIdentity, identity: PackageIdentity, *, now: datetime
) -> TrustEvidence:
    """Mint the durable evidence of the verification that just passed."""
    return TrustEvidence(
        verified=True,
        verifier_key_fingerprint=publisher.signing_key_fingerprint,
        policy=TRUST_POLICY,
        subject_sha256=identity.package_sha256,
        verified_at=now,
    )


def resolve_install(
    publishers: Mapping[str, PublisherIdentity],
    existing: Sequence[InstallRecord],
    request: InstallRequest,
    *,
    package_bytes: bytes,
    now: datetime,
    install_id: str,
) -> InstallRecord | None:
    """Run the fail-closed install rules; return the record to persist.

    Returns ``None`` when the request is an idempotent re-record of an already
    installed identity (the caller returns the existing record). Raises —
    persisting nothing — on every failure path:

    * :class:`UnknownPublisher` — no publisher identity record;
    * :class:`PackageDigestMismatch` — package or manifest bytes differ from
      the identity's digests;
    * :class:`PackageSignatureInvalid` — the signature does not verify against
      the registered publisher key;
    * :class:`ExtensionIdentityConflict` — a different package already occupies
      the requested ``(extension_name, semantic_version)``.
    """
    publisher = publishers.get(request.publisher_id)
    if publisher is None:
        raise UnknownPublisher(f"no publisher identity registered under {request.publisher_id!r}")

    verify_package_bytes(request.identity, package_bytes)
    verify_package_signature(
        request.identity,
        request.manifest_body,
        request.signature,
        publisher.signing_public_key,
    )

    requested = identity_key(request.identity)
    for record in existing:
        if record.identity.extension_name != request.identity.extension_name:
            continue
        if record.identity.semantic_version != request.identity.semantic_version:
            continue
        if identity_key(record.identity) == requested:
            return None
        raise ExtensionIdentityConflict(
            f"{request.identity.extension_name}@{request.identity.semantic_version} "
            f"is already installed with different bytes (package "
            f"{record.identity.package_sha256[:12]}…, manifest "
            f"{record.identity.manifest_sha256[:12]}…); a semantic version never "
            "silently names a second package"
        )

    manifest = manifest_snapshot(request.manifest_body)
    return InstallRecord(
        install_id=install_id,
        identity=request.identity,
        publisher=publisher,
        signature=request.signature,
        manifest=manifest,
        provenance=request.provenance,
        evidence=make_trust_evidence(publisher, request.identity, now=now),
        installed_at=now,
    )


def _record_for_identity(
    records: Sequence[InstallRecord], identity: PackageIdentity
) -> InstallRecord:
    """The already-known record for ``identity`` (idempotent path)."""
    wanted = identity_key(identity)
    for record in records:
        if identity_key(record.identity) == wanted:
            return record
    raise ExtensionRegistryError(
        "idempotent re-record matched no persisted record; store state is inconsistent"
    )


def _ensure_same_key(existing: PublisherIdentity, incoming: PublisherIdentity) -> None:
    """Refuse to re-register a publisher id under a different signing key."""
    if existing.signing_key_fingerprint != incoming.signing_key_fingerprint:
        raise PublisherKeyConflict(
            f"publisher {existing.publisher_id!r} is pinned to signing key "
            f"{existing.signing_key_fingerprint[:12]}…; re-registering it under "
            f"{incoming.signing_key_fingerprint[:12]}… is refused (rotation is a "
            "lifecycle flow, not a registry overwrite)"
        )


class InMemoryExtensionInstallStore:
    """Reference implementation. Process-local; the durable twin is
    :class:`~maistro.extensions.sqlite_store.SqliteExtensionInstallStore`."""

    def __init__(self) -> None:
        self._publishers: dict[str, PublisherIdentity] = {}
        self._installs: dict[str, list[InstallRecord]] = {}

    async def register_publisher(self, publisher: PublisherIdentity) -> None:
        """Pin a publisher identity; refuse a key change under the same id."""
        existing = self._publishers.get(publisher.publisher_id)
        if existing is not None:
            _ensure_same_key(existing, publisher)
            return
        self._publishers[publisher.publisher_id] = publisher

    async def record_install(
        self,
        request: InstallRequest,
        *,
        package_bytes: bytes,
        activate: ActivationCallback | None = None,
    ) -> InstallRecord:
        """Verify, record, then activate. See the module docstring for rules."""
        history = self._installs.setdefault(request.identity.extension_name, [])
        resolved = resolve_install(
            self._publishers,
            history,
            request,
            package_bytes=package_bytes,
            now=datetime.now(UTC),
            install_id=uuid.uuid4().hex,
        )
        if resolved is None:
            return _record_for_identity(
                self._installs.get(request.identity.extension_name, ()), request.identity
            )
        history.append(resolved)
        if activate is not None:
            activate(resolved)
        return resolved

    async def record_installs(
        self,
        installs: Sequence[tuple[InstallRequest, bytes]],
        *,
        activate: ActivationCallback | None = None,
    ) -> list[InstallRecord]:
        """Verify the whole batch, then record all, then activate.

        See the protocol docstring for the all-or-nothing contract.
        """
        pending: list[InstallRecord] = []
        resolved: list[InstallRecord] = []
        for request, package_bytes in installs:
            prior = [
                *self._installs.get(request.identity.extension_name, ()),
                *(
                    record
                    for record in pending
                    if record.identity.extension_name == request.identity.extension_name
                ),
            ]
            record = resolve_install(
                self._publishers,
                prior,
                request,
                package_bytes=package_bytes,
                now=datetime.now(UTC),
                install_id=uuid.uuid4().hex,
            )
            if record is None:
                resolved.append(_record_for_identity(prior, request.identity))
            else:
                pending.append(record)
                resolved.append(record)
        for record in pending:
            self._installs.setdefault(record.identity.extension_name, []).append(record)
        if activate is not None:
            for record in pending:
                activate(record)
        return resolved

    async def install_history(self, extension_name: str) -> list[InstallRecord]:
        """All install records for one extension, oldest first."""
        return list(self._installs.get(extension_name, ()))

    async def get_install(self, identity: PackageIdentity) -> InstallRecord | None:
        """The record for an exact installed-version identity, or ``None``."""
        wanted = identity_key(identity)
        for record in self._installs.get(identity.extension_name, ()):
            if identity_key(record.identity) == wanted:
                return record
        return None

    async def all_installs(self) -> list[InstallRecord]:
        """Every install record across every extension, oldest first per name."""
        records: list[InstallRecord] = []
        for name in sorted(self._installs):
            records.extend(self._installs[name])
        return records


# --------------------------------------------------------------------------
# M9-B2: activation store (issue #953)
# --------------------------------------------------------------------------


@runtime_checkable
class ExtensionStore(Protocol):
    """Persistence seam for install records and their audit trail."""

    async def save_record(self, record: ExtensionInstallRecord) -> None: ...

    async def get_record(self, install_id: str) -> ExtensionInstallRecord | None: ...

    async def latest_record(
        self, scope: ExtensionScope, extension_id: str, version: str
    ) -> ExtensionInstallRecord | None:
        """Most recent record for the (scope, extension, version) key."""
        ...

    async def active_record(
        self, scope: ExtensionScope, extension_id: str
    ) -> ExtensionInstallRecord | None: ...

    async def set_active(self, record: ExtensionInstallRecord) -> None:
        """Swap the scope's active pointer for the record's extension id.

        Implementations must make this a single atomic replacement: callers
        rely on it for caller-perceived activation atomicity.
        """
        ...

    async def clear_active(self, record: ExtensionInstallRecord) -> None:
        """Drop the scope's active pointer iff it names this record.

        The condition matters: disable/remove must not clobber a pointer that
        a concurrent activation has already moved to a different record.
        """
        ...

    async def installed_versions(self, scope: ExtensionScope) -> dict[str, str]:
        """extension_id -> version for every ACTIVE record in the scope."""
        ...

    async def records_in_state(self, state: ExtensionState) -> list[ExtensionInstallRecord]: ...

    async def append_transition(self, transition: ExtensionTransition) -> None: ...

    async def transitions_for(self, install_id: str) -> tuple[ExtensionTransition, ...]: ...

    async def next_seq(self) -> int: ...


class InMemoryExtensionStore:
    """Process-lifetime implementation of :class:`ExtensionStore`."""

    def __init__(self) -> None:
        self._records: dict[str, ExtensionInstallRecord] = {}
        self._active: dict[tuple[str, str, str], str] = {}
        self._transitions: list[ExtensionTransition] = []
        self._seq = 0

    async def save_record(self, record: ExtensionInstallRecord) -> None:
        self._records[record.install_id] = record

    async def get_record(self, install_id: str) -> ExtensionInstallRecord | None:
        return self._records.get(install_id)

    async def latest_record(
        self, scope: ExtensionScope, extension_id: str, version: str
    ) -> ExtensionInstallRecord | None:
        candidates = [
            record
            for record in self._records.values()
            if record.org_id == scope.org_id
            and record.workspace_id == scope.workspace_id
            and record.extension_id == extension_id
            and record.version == version
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda record: record.created_at or datetime.min.replace(tzinfo=UTC),
        )

    async def active_record(
        self, scope: ExtensionScope, extension_id: str
    ) -> ExtensionInstallRecord | None:
        install_id = self._active.get((scope.org_id, scope.workspace_id, extension_id))
        if install_id is None:
            return None
        return self._records.get(install_id)

    async def set_active(self, record: ExtensionInstallRecord) -> None:
        self._active[(record.org_id, record.workspace_id, record.extension_id)] = record.install_id

    async def clear_active(self, record: ExtensionInstallRecord) -> None:
        key = (record.org_id, record.workspace_id, record.extension_id)
        if self._active.get(key) == record.install_id:
            del self._active[key]

    async def installed_versions(self, scope: ExtensionScope) -> dict[str, str]:
        versions: dict[str, str] = {}
        for record in self._records.values():
            if (
                record.org_id == scope.org_id
                and record.workspace_id == scope.workspace_id
                and record.state is ExtensionState.ACTIVE
            ):
                versions[record.extension_id] = record.version
        return versions

    async def records_in_state(self, state: ExtensionState) -> list[ExtensionInstallRecord]:
        return [record for record in self._records.values() if record.state is state]

    async def append_transition(self, transition: ExtensionTransition) -> None:
        self._transitions.append(transition)

    async def transitions_for(self, install_id: str) -> tuple[ExtensionTransition, ...]:
        return tuple(t for t in self._transitions if t.install_id == install_id)

    async def next_seq(self) -> int:
        self._seq += 1
        return self._seq
