"""Core types for the governed extension install lifecycle (#953, M9-B2).

Extension installation is a server-side state machine: candidate packages are
inspected from manifest bytes alone, evaluated for compatibility and trust, and
held for explicit operator/organization authorization before any artifact is
installed or any extension code is loaded. The types here are the machine's
vocabulary; :mod:`maistro.extensions.service` owns the transitions.

Design constraints taken from the epic (#939) and this issue's acceptance
criteria:

- Inspection and authorization never import or execute extension code. The
  only seam that can run extension code is the host-supplied
  ``ExtensionCodeLoader``, and the service touches it in exactly one place:
  the install phase, after authorization.
- The manifest an operator authorizes is the manifest that installs: parsed
  once from raw bytes, anchored by a SHA-256 digest, and re-verified whenever
  its permissions are displayed or its grant is frozen.
- Install records are keyed by (org, workspace, extension id, version) and
  immutable: every state change produces a new record via ``dataclasses.replace``
  plus an audited transition carrying actor, scope, version and reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ExtensionState(StrEnum):
    """Durable states of one extension install record.

    The happy path is ``INSPECTING -> AWAITING_AUTHORIZATION -> AUTHORIZED ->
    INSTALLING -> ACTIVE``. ``DENIED``, ``REJECTED`` and ``ABANDONED`` are the
    fail-closed terminals: none of them can reach ``ACTIVE`` without a fresh
    inspection, so a denied or abandoned request never leaves an active
    extension behind. ``FAILED`` is the recoverable post-authorization state —
    the grant stands, the artifact bound at inspection may be presented again.
    """

    INSPECTING = "inspecting"
    AWAITING_AUTHORIZATION = "awaiting_authorization"
    AUTHORIZED = "authorized"
    INSTALLING = "installing"
    ACTIVE = "active"
    DENIED = "denied"
    REJECTED = "rejected"
    ABANDONED = "abandoned"
    FAILED = "failed"


#: The legal transition table. Every state is named here so an unfamiliar
#: edge fails loudly at lookup instead of silently widening the machine.
#: ``ACTIVE`` has no outgoing edges in B2 — pin/upgrade/disable/remove is
#: #954's lifecycle and must not grow here by accident.
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
    ExtensionState.AUTHORIZED: frozenset({ExtensionState.INSTALLING}),
    ExtensionState.INSTALLING: frozenset({ExtensionState.ACTIVE, ExtensionState.FAILED}),
    # A failed activation is retried with the same bound artifact: re-entering
    # INSTALLING is the recovery path, not a new authority grant.
    ExtensionState.FAILED: frozenset({ExtensionState.INSTALLING}),
    ExtensionState.ACTIVE: frozenset(),
    ExtensionState.DENIED: frozenset(),
    ExtensionState.REJECTED: frozenset(),
    ExtensionState.ABANDONED: frozenset(),
}

#: States that can never reach ``ACTIVE`` without a brand-new inspection.
TERMINAL_STATES: frozenset[ExtensionState] = frozenset(
    {
        ExtensionState.DENIED,
        ExtensionState.REJECTED,
        ExtensionState.ABANDONED,
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
class TrustEvidence:
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
