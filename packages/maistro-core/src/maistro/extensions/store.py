"""Extension install-record store: protocol and in-memory reference (M9-B1).

The store is append-only. There is no update and no delete: an install record
is evidence, and evidence is not rewritten. Every record snapshots the
publisher identity, digest, signature, manifest, catalog provenance and trust
evidence from install time, so registry-side changes — a re-registered
publisher, an edited catalog entry, a deleted catalog — cannot reach back into
history.

Two rules give the records their identity discipline:

* **Idempotent re-record.** Recording the exact same identity (same name,
  version, package digest, manifest digest) again returns the original record.
  Nothing is duplicated, and activation is not re-run.
* **Identity conflict.** Recording a *different* package under an already
  installed ``(extension_name, semantic_version)`` raises
  :class:`ExtensionIdentityConflict` and persists nothing. Two packages that
  share a semantic version but differ in digest never silently share identity:
  the second one is a loud refusal, not an overwrite.

Verification runs before persistence and before the ``activate`` callback is
invoked, so a tampered package fails before any extension code is imported.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from maistro.extensions.types import (
    ExtensionIdentityConflict,
    ExtensionRegistryError,
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
            return self._existing(request.identity)
        history.append(resolved)
        if activate is not None:
            activate(resolved)
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

    def _existing(self, identity: PackageIdentity) -> InstallRecord:
        """The already-persisted record for ``identity`` (idempotent path)."""
        for record in self._installs.get(identity.extension_name, ()):
            if identity_key(record.identity) == identity_key(identity):
                return record
        raise ExtensionRegistryError(
            "idempotent re-record matched no persisted record; store state is inconsistent"
        )
