"""Types for the extension registry records (M9-B1, #952) and the governed
install lifecycle (#953, M9-B2 / #954, M9-B3).

The registry half records immutable facts about *what was installed*: the
publisher identity as it was at install time, the exact manifest bytes, the
catalog provenance, and the signature/trust verification result minted at
verification time and durably stored — never recomputed on read. The
installed-version identity is :class:`PackageIdentity`: extension name,
semantic version, package digest, and manifest digest together. Two packages
that share a semantic version but differ in digest are *different
identities*.

The lifecycle half is a server-side state machine: candidate packages are
inspected from manifest bytes alone, evaluated for compatibility and trust,
and held for explicit operator/organization authorization before any artifact
is installed or any extension code is loaded. The types here are the machine's
vocabulary; :mod:`maistro.extensions.service` owns the transitions. After
activation, pin/upgrade/rollback/disable/remove move versions and authority
under audited transitions on the same records.

Design constraints taken from the epic (#939) and the issues' acceptance
criteria:

- Inspection and authorization never import or execute extension code. The
  only seam that can run extension code is the host-supplied
  ``ExtensionCodeLoader``, and the service touches it in exactly one place:
  the install phase, after authorization.
- The manifest an operator authorizes is the manifest that installs: parsed
  once from raw bytes, anchored by a SHA-256 digest, and re-verified whenever
  its permissions are displayed or its grant is frozen.
- Install records are immutable: every state change produces a new record via
  ``dataclasses.replace`` plus an audited transition carrying actor, scope,
  version and reason.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

DIGEST_ALGORITHM = "sha256"


class ExtensionRegistryError(RuntimeError):
    """Base class for extension registry/install-record failures."""


class UnknownPublisher(ExtensionRegistryError):
    """An install names a publisher the registry has no identity record for."""


class PublisherKeyConflict(ExtensionRegistryError):
    """A publisher identity would be re-registered under a different key.

    A publisher's signing key is pinned at first registration. Re-registering
    the same publisher id under a different key is exactly the move a registry
    compromise would make, so it fails closed; key rotation is a lifecycle
    concern with its own auditable flow, not a silent overwrite.
    """


class PackageDigestMismatch(ExtensionRegistryError):
    """The bytes in hand do not digest to the identity's declared digest."""


class PackageSignatureInvalid(ExtensionRegistryError):
    """The signature does not verify against the registered publisher key."""


class ExtensionIdentityConflict(ExtensionRegistryError):
    """A package reuses an installed (name, version) under different bytes."""


def sha256_hex(data: bytes) -> str:
    """Hex sha256 of ``data`` — the digest form every record field uses."""
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class PublisherIdentity:
    """Who published an extension, pinned at first registration.

    ``signing_public_key`` is the raw Ed25519 public key, hex-encoded; it is
    the trust root install-time verification runs against.
    ``signing_key_fingerprint`` is the digest of that key, the short form
    records and operators compare.
    """

    publisher_id: str
    display_name: str
    signing_key_fingerprint: str
    signing_public_key: str
    registered_at: datetime


@dataclass(frozen=True)
class PackageIdentity:
    """The immutable identity of one installed extension version.

    A semantic version alone does not name a package: the same
    ``(extension_name, semantic_version)`` must always carry the same package
    and manifest digests. Anything else is a different identity, and the
    stores treat it as a conflict rather than a replacement.
    """

    extension_name: str
    semantic_version: str
    package_sha256: str
    manifest_sha256: str


@dataclass(frozen=True)
class ManifestSnapshot:
    """The exact manifest bytes an install was made from."""

    body: str
    sha256: str


def manifest_snapshot(body: str) -> ManifestSnapshot:
    """Snapshot manifest ``body``, digesting it at snapshot time."""
    return ManifestSnapshot(body=body, sha256=sha256_hex(body.encode()))


@dataclass(frozen=True)
class RegistryProvenance:
    """Where the installed package was discovered and fetched from.

    Recorded once, at install time: if the catalog later rewrites or deletes
    the entry, the record still says what the registry source claimed when the
    bytes were pulled.
    """

    catalog_url: str
    catalog_snapshot_sha256: str
    retrieved_at: datetime


@dataclass(frozen=True)
class TrustEvidence:
    """The durable result of signature/trust verification.

    Minted by the store when an install is recorded and stored with it. Reads
    never re-verify: the evidence is the audit trail of the check that already
    happened, so it stays queryable even when the signing key or catalog that
    produced it is long gone.
    """

    verified: bool
    verifier_key_fingerprint: str
    policy: str
    subject_sha256: str
    verified_at: datetime


@dataclass(frozen=True)
class InstallRequest:
    """Everything the caller supplies to record one install.

    ``package_bytes`` is passed to :meth:`record_install` separately (it is
    the bytes being verified, not record metadata). The signature is over
    :func:`canonical_install_payload` — the canonical identity string — made
    with the registered publisher's key.
    """

    identity: PackageIdentity
    publisher_id: str
    signature: str
    manifest_body: str
    provenance: RegistryProvenance


@dataclass(frozen=True)
class InstallRecord:
    """One immutable installed-version record, and the whole audit trail."""

    install_id: str
    identity: PackageIdentity
    publisher: PublisherIdentity
    signature: str
    manifest: ManifestSnapshot
    provenance: RegistryProvenance
    evidence: TrustEvidence
    installed_at: datetime


def canonical_install_payload(identity: PackageIdentity) -> bytes:
    """The exact bytes a publisher signs for one package identity.

    Version-tagged and newline-delimited so fields cannot run together and an
    old signature can never be replayed as a new format.
    """
    return "\n".join(
        (
            "maistro-extension-install:v1",
            identity.extension_name,
            identity.semantic_version,
            identity.package_sha256,
            identity.manifest_sha256,
        )
    ).encode()


def identity_key(identity: PackageIdentity) -> tuple[str, str, str, str]:
    """Hashable key for the full installed-version identity."""
    return (
        identity.extension_name,
        identity.semantic_version,
        identity.package_sha256,
        identity.manifest_sha256,
    )


def _payload_object(record: InstallRecord) -> dict[str, Any]:
    """JSON-safe dict of one record, with datetimes as ISO-8601 strings."""
    payload = asdict(record)
    payload["publisher"]["registered_at"] = record.publisher.registered_at.isoformat()
    payload["provenance"]["retrieved_at"] = record.provenance.retrieved_at.isoformat()
    payload["evidence"]["verified_at"] = record.evidence.verified_at.isoformat()
    payload["installed_at"] = record.installed_at.isoformat()
    return payload


def _datetime_value(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def record_to_json(record: InstallRecord) -> str:
    """Serialize one install record for the durable payload column."""
    return json.dumps(_payload_object(record), sort_keys=True)


def publisher_to_json(publisher: PublisherIdentity) -> str:
    """Serialize a publisher identity for the durable payload column."""
    payload = asdict(publisher)
    payload["registered_at"] = publisher.registered_at.isoformat()
    return json.dumps(payload, sort_keys=True)


def publisher_from_json(raw: str) -> PublisherIdentity:
    """Rebuild a publisher identity from its durable payload."""
    payload = json.loads(raw)
    payload["registered_at"] = _datetime_value(payload["registered_at"])
    return PublisherIdentity(**payload)


def record_from_json(raw: str) -> InstallRecord:
    """Rebuild a record from its durable payload.

    Datetimes are restored timezone-aware (naive values are read as UTC), so
    a record round-trips equal to what was written.
    """

    def build(value: dict[str, Any], cls: type) -> Any:
        fields = dict(value)
        if cls is PublisherIdentity:
            fields["registered_at"] = _datetime_value(fields["registered_at"])
        elif cls is RegistryProvenance:
            fields["retrieved_at"] = _datetime_value(fields["retrieved_at"])
        elif cls is TrustEvidence:
            fields["verified_at"] = _datetime_value(fields["verified_at"])
        return cls(**fields)

    payload = json.loads(raw)
    return InstallRecord(
        install_id=str(payload["install_id"]),
        identity=PackageIdentity(**payload["identity"]),
        publisher=build(payload["publisher"], PublisherIdentity),
        signature=str(payload["signature"]),
        manifest=ManifestSnapshot(**payload["manifest"]),
        provenance=build(payload["provenance"], RegistryProvenance),
        evidence=build(payload["evidence"], TrustEvidence),
        installed_at=_datetime_value(payload["installed_at"]),
    )


class ExtensionState(StrEnum):
    """Durable states of one extension install record.

    The happy path is ``INSPECTING -> AWAITING_AUTHORIZATION -> AUTHORIZED ->
    INSTALLING -> ACTIVE``. ``DENIED``, ``REJECTED`` and ``ABANDONED`` are the
    fail-closed terminals: none of them can reach ``ACTIVE`` without a fresh
    inspection, so a denied or abandoned request never leaves an active
    extension behind. ``FAILED`` is the recoverable post-authorization state —
    the grant stands, the artifact bound at inspection may be presented again.

    B3 (#954) finishes the lifecycle on this same machine with three durable
    post-install states:

    - ``DISABLED`` — suspended by an operator. The scope's active pointer is
      dropped, so invocation resolution stops immediately; the record, its
      frozen grant and its audit trail are retained verbatim.
    - ``SUPERSEDED`` — was ACTIVE, replaced by another version of the same
      extension (an upgrade activation, a rollback away, or crash
      reconciliation). Retained as the rollback candidate pool: its bound
      artifact digest and frozen grant are exactly what a rollback restores.
    - ``REMOVED`` — uninstalled. Terminal for the record's authority; the
      record and its transitions are canonical historical evidence and are
      never deleted. The (scope, extension, version) key is released so the
      same version can be reinstalled through a fresh authorization track.

    Resume and rollback re-enter ``INSTALLING`` rather than jumping straight
    to ``ACTIVE``: the loader is the only code-execution seam, so restoring a
    runtime handle goes through the same checked activation path as a first
    install, never around it.
    """

    INSPECTING = "inspecting"
    AWAITING_AUTHORIZATION = "awaiting_authorization"
    AUTHORIZED = "authorized"
    INSTALLING = "installing"
    ACTIVE = "active"
    DISABLED = "disabled"
    SUPERSEDED = "superseded"
    REMOVED = "removed"
    DENIED = "denied"
    REJECTED = "rejected"
    ABANDONED = "abandoned"
    FAILED = "failed"


#: The legal transition table. Every state is named here so an unfamiliar
#: edge fails loudly at lookup instead of silently widening the machine.
#:
#: B2 installed the inspect→authorize→install edges; B3 (#954) finishes the
#: post-install lifecycle on the same machine — one table, one authority.
TRANSITIONS: dict[ExtensionState, frozenset[ExtensionState]] = {
    ExtensionState.INSPECTING: frozenset(
        {ExtensionState.AWAITING_AUTHORIZATION, ExtensionState.REJECTED}
    ),
    ExtensionState.AWAITING_AUTHORIZATION: frozenset(
        {
            ExtensionState.AUTHORIZED,
            ExtensionState.DENIED,
            ExtensionState.ABANDONED,
        }
    ),
    # B3: an authorized grant may be released without ever activating — the
    # operator withdraws before install. REMOVED is terminal.
    ExtensionState.AUTHORIZED: frozenset({ExtensionState.INSTALLING, ExtensionState.REMOVED}),
    ExtensionState.INSTALLING: frozenset({ExtensionState.ACTIVE, ExtensionState.FAILED}),
    # A failed activation is retried with the same bound artifact: re-entering
    # INSTALLING is the recovery path, not a new authority grant. B3: a failed
    # install may also be abandoned outright, releasing its (scope, extension,
    # version) key for a fresh inspection of fixed bytes.
    ExtensionState.FAILED: frozenset({ExtensionState.INSTALLING, ExtensionState.REMOVED}),
    # B3: the post-install lifecycle. DISABLED suspends invocation resolution;
    # SUPERSEDED retires a version while keeping it rollback-eligible;
    # REMOVED uninstalls. Resume and rollback re-enter INSTALLING so restored
    # code goes through the loader seam again, never around it.
    ExtensionState.ACTIVE: frozenset(
        {
            ExtensionState.DISABLED,
            ExtensionState.SUPERSEDED,
            ExtensionState.REMOVED,
        }
    ),
    ExtensionState.DISABLED: frozenset({ExtensionState.INSTALLING, ExtensionState.REMOVED}),
    ExtensionState.SUPERSEDED: frozenset({ExtensionState.INSTALLING, ExtensionState.REMOVED}),
    ExtensionState.REMOVED: frozenset(),
    ExtensionState.DENIED: frozenset(),
    ExtensionState.REJECTED: frozenset(),
    ExtensionState.ABANDONED: frozenset(),
}

#: States that can never reach ``ACTIVE`` without a brand-new inspection.
#: ``REMOVED`` is deliberately absent: removal is terminal for the record's
#: authority, but the (scope, extension, version) key it held is released —
#: reinstalling the same version must open a *fresh* authorization track,
#: which a terminal classification would silently forbid by handing the old
#: record back (see ``ExtensionInstallService.inspect``).
TERMINAL_STATES: frozenset[ExtensionState] = frozenset(
    {
        ExtensionState.DENIED,
        ExtensionState.REJECTED,
        ExtensionState.ABANDONED,
    }
)

#: States whose records hold neither an open authorization track nor any
#: authority: re-inspecting the same key never resumes the old record, it
#: opens a new one.
INSPECT_SKIP_STATES: frozenset[ExtensionState] = TERMINAL_STATES | frozenset(
    {ExtensionState.REMOVED}
)

#: States an install record may be removed from (#954). The fail-closed
#: terminals hold nothing to remove — they never held a grant — and REMOVED
#: is already the target state.
REMOVABLE_STATES: frozenset[ExtensionState] = frozenset(
    {
        ExtensionState.AUTHORIZED,
        ExtensionState.FAILED,
        ExtensionState.ACTIVE,
        ExtensionState.DISABLED,
        ExtensionState.SUPERSEDED,
    }
)


class ExtensionLifecycleError(Exception):
    """Base class for governed-install failures surfaced to callers."""


class ManifestRejected(ExtensionLifecycleError):
    """The manifest bytes are not a valid manifest for this platform.

    Raised only from parsing — a manifest that cannot be parsed has no
    extension identity to key an install record with, so it is refused at the
    door rather than recorded.
    """


class InspectionConflict(ExtensionLifecycleError):
    """An inspection contradicts the record already open for its key.

    Same (scope, extension, version) with different manifest or artifact bytes
    means the candidate changed under an open authorization request; the
    service refuses to fork a second authorization track for one version.
    """


class InvalidTransition(ExtensionLifecycleError):
    """A lifecycle operation was attempted from a state that forbids it."""


class UnknownInstall(ExtensionLifecycleError):
    """No install record exists for the given id *in the given scope*.

    Deliberately one error for a missing id and a foreign-scope id, so
    probing another scope's install ids discloses nothing.
    """


class ArtifactMismatch(ExtensionLifecycleError):
    """The artifact bytes presented at install differ from the inspected ones.

    No transition is recorded: the record keeps its state, because a payload
    that fails the digest check never happened to the machine.
    """


class PreflightError(ExtensionLifecycleError):
    """A version-change preflight (upgrade or rollback) refused.

    Raised before any state change, any transition, and any record write: a
    refused preflight leaves the scope exactly as it was. The message names
    every failed check so the refusal is auditable from the log alone.
    """


class PinConflict(PreflightError):
    """The operation contradicts the scope's version pin.

    A pin holds one version against version changes; moving to another
    version requires an explicit unpin first. Nothing is mutated.
    """


@dataclass(frozen=True)
class ExtensionScope:
    """Where an extension install lives.

    ``org_id`` is the authorization authority (the operator/organization that
    decides); ``workspace_id`` optionally narrows the install to one canonical
    Workspace. Blank ``org_id`` is refused — an install nobody is the
    authority for must not be recordable.
    """

    org_id: str
    workspace_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.org_id, str) or not self.org_id.strip():
            raise ValueError("org_id is required: an install must name its authorizing scope")

    @property
    def describe(self) -> str:
        """Human-readable scope for audit lines and failure reasons."""
        if self.workspace_id:
            return f"org:{self.org_id}/workspace:{self.workspace_id}"
        return f"org:{self.org_id}"


@dataclass(frozen=True)
class ExtensionEntryPoint:
    """A *declared* entry point. Inspection records names; it never resolves
    modules — resolving/importing happens only inside the host loader, during
    install, after authorization."""

    name: str
    module: str
    attribute: str


@dataclass(frozen=True)
class ExtensionDependency:
    """A declared dependency on another extension, with a version range.

    ``range_spec`` is one of: an exact semver (``1.2.3``), a caret range
    (``^1.2.0`` — same major, at or above the floor), or ``*`` (any installed
    version). Anything else fails compatibility closed.
    """

    extension_id: str
    range_spec: str


@dataclass(frozen=True)
class ExtensionManifest:
    """The immutable snapshot of one inspected extension manifest.

    ``raw`` is the exact bytes the operator's decision will be about and
    ``source_sha256`` anchors them; :func:`maistro.extensions.manifest.
    assert_snapshot_intact` re-verifies the pair so displayed permissions can
    never drift from what was inspected.
    """

    manifest_version: int
    extension_id: str
    name: str
    version: str
    publisher: str
    api_version: str
    permissions: tuple[str, ...]
    entry_points: tuple[ExtensionEntryPoint, ...]
    dependencies: tuple[ExtensionDependency, ...]
    artifact_sha256: str
    artifact_size: int
    source_sha256: str
    raw: bytes = field(repr=False, compare=False)


@dataclass(frozen=True)
class ExtensionPackage:
    """A candidate extension: manifest bytes plus the payload artifact."""

    manifest_bytes: bytes
    payload: bytes


@dataclass(frozen=True)
class OperatorTrustEvidence:
    """Publisher/package evidence consumed by the trust evaluation.

    Until the B1 signing substrate (#952) lands, this evidence is asserted by
    the operator pipeline that fetched the package; the evaluation still fails
    closed on absence, publisher mismatch, or a policy that requires
    signatures none were presented for.
    """

    publisher_id: str
    signature_present: bool = False
    signer_key_id: str | None = None
    package_sha256: str = ""


@dataclass(frozen=True)
class ExtensionInstallRecord:
    """One governed install: identity, immutable manifest snapshot, state."""

    install_id: str
    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    manifest: ExtensionManifest
    state: ExtensionState
    #: Permissions exactly as the immutable snapshot declares them. Display
    #: goes through the snapshot check, never through a mutable copy.
    requested_permissions: tuple[str, ...]
    #: Frozen at authorization to the snapshot's requested set. Retries and
    #: re-installs cannot widen it; #954's upgrade flow re-authorizes instead.
    granted_permissions: tuple[str, ...] = ()
    #: Permissions the authority delta flags as new against the scope baseline
    #: (already-active grants for this extension plus platform pre-approvals).
    authority_delta: tuple[str, ...] = ()
    artifact_sha256: str | None = None
    failure_reason: str | None = None
    requested_by: str = ""
    authorized_by: str | None = None
    installed_by: str | None = None
    install_attempts: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    #: Decision deadline for the AWAITING_AUTHORIZATION state. Expired
    #: requests become ABANDONED — lazily on touch and via the sweep.
    expires_at: datetime | None = None
    #: Why the record sits in its current lifecycle state, for the B3
    #: post-install states that are not failures (DISABLED, SUPERSEDED,
    #: REMOVED). Failure-shaped states keep carrying ``failure_reason``;
    #: this is the durable answer to "why is this disabled/superseded/removed".
    status_reason: str | None = None


@dataclass(frozen=True)
class ExtensionTransition:
    """One audited lifecycle transition (canonical evidence, #939/#953)."""

    seq: int
    at: datetime
    install_id: str
    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    actor: str
    from_state: ExtensionState
    to_state: ExtensionState
    reason: str


@dataclass(frozen=True)
class PinRecord:
    """A version pin (#954): the scope holds this extension at this version.

    Pinning is operator metadata with authority consequences — upgrade and
    rollback preflights refuse version changes that contradict it — so it is
    persisted in the same store as the records it constrains and every
    pin/unpin is audited (see :class:`PinEvent`). At most one pin exists per
    (scope, extension); re-pinning the same version refreshes it.
    """

    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    pinned_by: str
    reason: str
    pinned_at: datetime | None = None


@dataclass(frozen=True)
class PinEvent:
    """One audited pin/unpin operation (canonical evidence, #939/#954)."""

    seq: int
    at: datetime
    org_id: str
    workspace_id: str
    extension_id: str
    action: str
    #: The pinned version for ``pin``/``refresh``; ``None`` for ``unpin``.
    version: str | None
    actor: str
    reason: str


@dataclass(frozen=True)
class RemovalNote:
    """The owned-resource cleanup report of one remove operation (#954).

    Canonical evidence (records and transitions) is never deleted; what
    removal *may* delete is the extension's owned operational resources, via
    a host-supplied janitor. This note records what that policy actually
    purged — and what it failed to purge — so a removal is auditable down to
    its cleanup, including the retries of a crashed cleanup.
    """

    seq: int
    at: datetime
    install_id: str
    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    actor: str
    purged: tuple[str, ...]
    failed: tuple[str, ...]
