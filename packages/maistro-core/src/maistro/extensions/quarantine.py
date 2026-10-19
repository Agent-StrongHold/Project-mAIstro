"""Quarantine and disable for misbehaving extensions (#972, M9-G4).

One governed flow connects canonical violation evidence (security events,
M9-G2 sandbox boundary events, health failures) to a suspension response,
under three structural rules:

1. **The extension never holds the pen.** Every mutating method demands a
   governance actor (:class:`GovernanceActor`) whose kind is a host/org
   administrator or the system; an extension-kind actor raises
   :class:`QuarantineAuthorityError`. No method accepts an
   :class:`~maistro.extensions.context.ExtensionContext`, so extension code
   structurally cannot reach the ledger, let alone write or clear its own
   security state.
2. **Evidence is retained, never rewritten.** Events append to
   :class:`ExtensionGovernanceLedger` history; re-enable flips state, and
   the strike counts keep accumulating across disable/re-enable cycles — a
   re-enabled extension that misbehaves again re-quarantines from its
   lifetime strikes, not from a fresh slate.
3. **The authoritative state change is immediate and admission is checked
   after it.** Mutations and admission checks are synchronous (no await
   between the state write and its visibility), so under concurrent asyncio
   callers no :meth:`record`/``quarantine``/``disable`` completion can be
   followed by a successful admission of the governed identity: quarantine
   and invocation race, and quarantine always wins anything it precedes.

Three distinct responses keep the record truthful: **version disable**
(one bad version stops admitting; other signed versions of the same package
keep running), **package quarantine** (every version of the extension stops
admitting), and **publisher-wide quarantine** (a policy decision, off by
default — one bad package does not falsely condemn unrelated signed
packages unless the operator chooses it). Transient **health failures**
below the configured threshold are recorded as evidence but change no
state: an unavailable extension is not a policy violator.

In-flight work follows the policy's :class:`InFlightDisposition`: leases
begun before the state change either drain to completion (default) or are
marked for termination — new work is refused either way. Historical
invocations stay with the canonical Run/NodeRun/Attempt evidence; this
module only ever refuses *new* work.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from maistro.extensions.isolation import ExtensionSandboxViolation
from maistro.extensions.types import ExtensionRegistryError


class QuarantineAuthorityError(ExtensionRegistryError):
    """A governance mutation lacked an authorized actor.

    The extension itself can never pass this gate: only host/org
    administrators and the system may change governed state, which is what
    keeps an extension from writing or clearing its own quarantine/security
    evidence.
    """


class EvidenceKind(StrEnum):
    """The canonical violation inputs the governance flow consumes."""

    #: A canonical security event attributed to the extension (Warden,
    #: Sentinel, or a host security seam).
    SECURITY_VIOLATION = "security_violation"
    #: A sandbox boundary event (M9-G2's attributable violation record).
    SANDBOX_VIOLATION = "sandbox_violation"
    #: A health failure — availability, not a policy violation, until the
    #: threshold says otherwise.
    HEALTH_FAILURE = "health_failure"


class GovernanceState(StrEnum):
    """Admission state of one governed identity."""

    ACTIVE = "active"
    #: Version-level disable: this version stops admitting; sibling versions
    #: of the same package keep running.
    DISABLED = "disabled"
    #: Package- or publisher-level quarantine: everything under the target
    #: stops admitting.
    QUARANTINED = "quarantined"


class GovernanceTarget(StrEnum):
    """What a decision was about."""

    VERSION = "version"
    PACKAGE = "package"
    PUBLISHER = "publisher"


class InFlightDisposition(StrEnum):
    """What happens to work already begun when a target is suspended."""

    #: Leases begun before the state change run to completion.
    DRAIN = "drain"
    #: Leases begun before the state change are marked for termination.
    TERMINATE = "terminate"


class ActorKind(StrEnum):
    """Who is acting on governed state."""

    HOST_ADMIN = "host_admin"
    ORG_ADMIN = "org_admin"
    SYSTEM = "system"
    EXTENSION = "extension"


#: Actor kinds that may mutate governed state. An EXTENSION actor never is
#: one — that is the "cannot write or clear its own state" rule.
GOVERNANCE_ACTOR_KINDS = frozenset({ActorKind.HOST_ADMIN, ActorKind.ORG_ADMIN, ActorKind.SYSTEM})


@dataclass(frozen=True)
class GovernanceActor:
    """The authenticated principal behind a governance action."""

    kind: ActorKind
    id: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise QuarantineAuthorityError("governance actor id is required")


@dataclass(frozen=True)
class ExtensionEvidence:
    """One canonical violation/health event, attributed to identity/version."""

    kind: EvidenceKind
    extension_id: str
    version: str
    publisher: str
    at: datetime
    #: The canonical seam that produced the evidence (e.g. "sandbox",
    #: "warden", "health").
    source: str
    detail: str = ""
    #: SHA-256 over the canonical evidence payload — stable identity for
    #: audit joins; identical evidence always digests identically.
    digest: str = field(default="")

    def __post_init__(self) -> None:
        if not self.extension_id.strip() or not self.version.strip() or not self.publisher.strip():
            raise QuarantineAuthorityError(
                "evidence must attribute extension id, version, and publisher"
            )
        if not self.digest:
            payload = {
                "detail": self.detail,
                "extension_id": self.extension_id,
                "kind": self.kind.value,
                "publisher": self.publisher,
                "source": self.source,
                "version": self.version,
            }
            object.__setattr__(
                self,
                "digest",
                hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            )


@dataclass(frozen=True)
class ExtensionGovernancePolicy:
    """Thresholds and dispositions driving automatic suspension.

    Thresholds are lifetime strike counts per evidence kind and identity:
    ``security_threshold=1`` quarantines on the first security violation,
    while sandbox and health evidence accumulate. A health count below the
    threshold is recorded but changes no state — the transient-failure
    distinction the issue asks for.
    """

    security_threshold: int = 1
    sandbox_threshold: int = 3
    health_threshold: int = 3
    #: Quarantine the whole publisher on a triggered quarantine. Off by
    #: default: one bad version must not condemn unrelated signed packages
    #: unless policy chooses publisher-wide action.
    publisher_wide: bool = False
    #: Disposition for leases begun before a suspension.
    in_flight: InFlightDisposition = InFlightDisposition.DRAIN

    def __post_init__(self) -> None:
        for name in ("security_threshold", "sandbox_threshold", "health_threshold"):
            value = getattr(self, name)
            if value < 1:
                raise QuarantineAuthorityError(f"{name} must be >= 1, got {value}")


@dataclass(frozen=True)
class GovernanceEvent:
    """One appended ledger row — evidence, suspension, or re-enable."""

    seq: int
    at: datetime
    action: str
    target: GovernanceTarget
    extension_id: str
    version: str
    publisher: str
    actor: str
    reason: str
    state_after: GovernanceState
    evidence_digest: str = ""


@dataclass(frozen=True)
class GovernanceDecision:
    """The outcome of one governance mutation."""

    seq: int
    target: GovernanceTarget
    extension_id: str
    version: str
    publisher: str
    state_after: GovernanceState
    reason: str
    changed: bool

    @property
    def suspended(self) -> bool:
        return self.state_after is GovernanceState.QUARANTINED


@dataclass(frozen=True)
class AdmissionDecision:
    """Whether one extension identity may begin new work right now."""

    extension_id: str
    version: str
    publisher: str
    allowed: bool
    #: Empty exactly when allowed; otherwise names the governing scope.
    reason: str = ""
    governing_state: GovernanceState = GovernanceState.ACTIVE


@dataclass(frozen=True)
class InvocationLease:
    """Proof that one invocation began before any later state change.

    The disposition of a lease is a service query (:meth:`ExtensionGovernanceService.disposition`),
    never a lease method — the lease carries no authority of its own.
    """

    lease_id: str
    extension_id: str
    version: str
    publisher: str


@dataclass
class _PackageState:
    """Mutable per-package governance state (the authoritative record)."""

    publisher: str
    state: GovernanceState = GovernanceState.ACTIVE
    versions: dict[str, GovernanceState] = field(default_factory=dict)
    strikes: dict[tuple[str, str], int] = field(default_factory=dict)  # (version, kind) -> count


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ExtensionGovernanceLedger:
    """Append-only governance history (#972).

    Every evidence record, suspension, and re-enable appends here with
    actor, reason, and attribution, and stays queryable forever — there is
    no delete or update API, so a suspension's evidence cannot be erased by
    the re-enable that follows it.
    """

    def __init__(self) -> None:
        self._events: list[GovernanceEvent] = []
        self._seq = 0

    def append(self, event: GovernanceEvent) -> GovernanceEvent:
        self._seq += 1
        stamped = GovernanceEvent(
            seq=self._seq, **{k: v for k, v in event.__dict__.items() if k != "seq"}
        )
        self._events.append(stamped)
        return stamped

    def history(
        self, *, extension_id: str | None = None, version: str | None = None
    ) -> tuple[GovernanceEvent, ...]:
        """All retained events, optionally narrowed to identity/version."""
        if extension_id is None:
            return tuple(self._events)
        return tuple(
            event
            for event in self._events
            if event.extension_id == extension_id and (version is None or event.version == version)
        )

    def __len__(self) -> int:
        return len(self._events)


class ExtensionGovernanceService:
    """Admission gate and suspension flow for extensions (#972, M9-G4).

    The service is the single authority for "may this extension/version
    begin new work": hosts check :meth:`admit` (or :meth:`begin_invocation`)
    before every invocation. Evidence arrives only from canonical host-side
    seams — security, the sandbox violation log, health — never from
    extension code, and every state change is immediate: the mutation
    returns only after the authoritative state has been swapped, and later
    admission checks see it.
    """

    def __init__(
        self,
        *,
        policy: ExtensionGovernancePolicy | None = None,
        ledger: ExtensionGovernanceLedger | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.policy = policy or ExtensionGovernancePolicy()
        self.ledger = ledger if ledger is not None else ExtensionGovernanceLedger()
        self._clock = clock
        self._packages: dict[str, _PackageState] = {}
        self._publishers: dict[str, GovernanceState] = {}
        self._leases: dict[str, InvocationLease] = {}

    # -- admission ---------------------------------------------------------

    def _governing(
        self, *, extension_id: str, version: str, publisher: str
    ) -> tuple[GovernanceState, str]:
        """The strictest state governing this identity, and why.

        One authority for admission, disposition, and evidence reporting —
        checked in the fixed order publisher → package → version, so a
        publisher quarantine can never be read as anything narrower.
        """
        mismatch = self._publisher_mismatch(
            extension_id=extension_id, publisher=publisher
        )
        if mismatch:
            # Fail closed: a mismatched publisher is not a new identity but
            # a false label on the pinned one, so it can never admit.
            return GovernanceState.QUARANTINED, mismatch
        if self._publishers.get(publisher) is GovernanceState.QUARANTINED:
            return (
                GovernanceState.QUARANTINED,
                f"publisher {publisher!r} is quarantined by governance",
            )
        package = self._packages.get(extension_id)
        if package is not None:
            if package.state is GovernanceState.QUARANTINED:
                return (
                    GovernanceState.QUARANTINED,
                    f"extension {extension_id!r} is quarantined by governance",
                )
            version_state = package.versions.get(version, GovernanceState.ACTIVE)
            if version_state is not GovernanceState.ACTIVE:
                label = "disabled" if version_state is GovernanceState.DISABLED else "quarantined"
                return (
                    version_state,
                    f"extension {extension_id!r} version {version!r} is {label}",
                )
        return GovernanceState.ACTIVE, ""

    def _publisher_mismatch(self, *, extension_id: str, publisher: str) -> str:
        """Why this identity is refused, or "" when the publisher is pinned.

        A package's publisher is pinned the first time its extension id is
        seen. A caller naming a different publisher for the same id is not
        a new identity — it is the pinned identity under a false label —
        so it is refused rather than resolved against the impostor
        publisher, which would otherwise let admission bypass a quarantine
        hold and let evidence strikes or re-enables blend across
        publishers.
        """
        package = self._packages.get(extension_id)
        if package is not None and package.publisher != publisher:
            return (
                f"extension {extension_id!r} is pinned to publisher "
                f"{package.publisher!r}; refusing identity attributed to "
                f"publisher {publisher!r}"
            )
        return ""

    def _require_pinned_publisher(self, *, extension_id: str, publisher: str) -> None:
        """Refuse mutations that name a publisher other than the pinned one."""
        mismatch = self._publisher_mismatch(
            extension_id=extension_id, publisher=publisher
        )
        if mismatch:
            raise QuarantineAuthorityError(mismatch)

    def admit(self, *, extension_id: str, version: str, publisher: str) -> AdmissionDecision:
        """May this identity begin new work? Checked before every invocation.

        Synchronous by contract: once a suspension mutation has returned,
        every subsequent admission of the governed identity is refused —
        there is no await between the state swap and this check.
        """
        state, reason = self._governing(
            extension_id=extension_id, version=version, publisher=publisher
        )
        if state is not GovernanceState.ACTIVE:
            return AdmissionDecision(
                extension_id=extension_id,
                version=version,
                publisher=publisher,
                allowed=False,
                reason=reason,
                governing_state=state,
            )
        return AdmissionDecision(
            extension_id=extension_id, version=version, publisher=publisher, allowed=True
        )

    def begin_invocation(
        self, *, extension_id: str, version: str, publisher: str
    ) -> InvocationLease:
        """Admit-and-open a lease in one authoritative step.

        Admission is refused by raising :class:`QuarantineAuthorityError`
        when the identity is suspended — a caller that skips the separate
        :meth:`admit` check cannot begin work.
        """
        decision = self.admit(extension_id=extension_id, version=version, publisher=publisher)
        if not decision.allowed:
            raise QuarantineAuthorityError(decision.reason)
        lease = InvocationLease(
            lease_id=uuid4().hex,
            extension_id=extension_id,
            version=version,
            publisher=publisher,
        )
        self._leases[lease.lease_id] = lease
        return lease

    def disposition(self, lease: InvocationLease) -> InFlightDisposition:
        """The policy disposition for work begun under ``lease``.

        A pure query: it never changes state, so a disposition may be
        re-checked as often as the runner needs.
        """
        state, _ = self._governing(
            extension_id=lease.extension_id,
            version=lease.version,
            publisher=lease.publisher,
        )
        return (
            self.policy.in_flight
            if state is not GovernanceState.ACTIVE
            else InFlightDisposition.DRAIN
        )

    def finish_invocation(self, lease: InvocationLease) -> None:
        """Close a completed lease (bookkeeping only; admission was at begin)."""
        self._leases.pop(lease.lease_id, None)

    # -- canonical evidence --------------------------------------------------

    def record(self, evidence: ExtensionEvidence, *, actor: GovernanceActor) -> GovernanceDecision:
        """Record canonical evidence and apply the policy thresholds.

        Thresholds key on (extension id, version) strikes per evidence kind
        and are lifetime — they survive disable/re-enable cycles. A health
        count below ``health_threshold`` records evidence only (the
        transient-failure distinction). Crossing a threshold quarantines the
        package — or the whole publisher when policy sets
        ``publisher_wide``.
        """
        self._require_authorized(actor, "record security/health evidence")
        self._require_pinned_publisher(
            extension_id=evidence.extension_id, publisher=evidence.publisher
        )
        package = self._packages.setdefault(
            evidence.extension_id, _PackageState(publisher=evidence.publisher)
        )
        key = (evidence.version, evidence.kind.value)
        package.strikes[key] = package.strikes.get(key, 0) + 1

        threshold = {
            EvidenceKind.SECURITY_VIOLATION: self.policy.security_threshold,
            EvidenceKind.SANDBOX_VIOLATION: self.policy.sandbox_threshold,
            EvidenceKind.HEALTH_FAILURE: self.policy.health_threshold,
        }[evidence.kind]
        strikes = package.strikes[key]
        if strikes < threshold:
            return self._append(
                action="evidence_recorded",
                target=GovernanceTarget.VERSION,
                extension_id=evidence.extension_id,
                version=evidence.version,
                publisher=evidence.publisher,
                actor=actor,
                reason=f"{evidence.kind.value} #{strikes} below threshold {threshold}: {evidence.detail}".strip(),
                state_after=self._governing(
                    extension_id=evidence.extension_id,
                    version=evidence.version,
                    publisher=evidence.publisher,
                )[0],
                evidence_digest=evidence.digest,
                changed=False,
            )

        target = (
            GovernanceTarget.PUBLISHER if self.policy.publisher_wide else GovernanceTarget.PACKAGE
        )
        if target is GovernanceTarget.PUBLISHER:
            self._publishers[evidence.publisher] = GovernanceState.QUARANTINED
        else:
            package.state = GovernanceState.QUARANTINED
        return self._append(
            action="quarantined",
            target=target,
            extension_id=evidence.extension_id,
            version=evidence.version,
            publisher=evidence.publisher,
            actor=actor,
            reason=f"{evidence.kind.value} reached threshold {threshold} "
            f"({strikes} strikes): {evidence.detail}".strip(),
            state_after=GovernanceState.QUARANTINED,
            evidence_digest=evidence.digest,
            changed=True,
        )

    # -- explicit governance actions ----------------------------------------

    def disable_version(
        self,
        *,
        extension_id: str,
        version: str,
        publisher: str,
        actor: GovernanceActor,
        reason: str,
    ) -> GovernanceDecision:
        """Disable one version; sibling versions keep admitting."""
        self._require_authorized(actor, "disable an extension version")
        self._require_pinned_publisher(extension_id=extension_id, publisher=publisher)
        package = self._packages.setdefault(extension_id, _PackageState(publisher=publisher))
        package.versions[version] = GovernanceState.DISABLED
        return self._append(
            action="version_disabled",
            target=GovernanceTarget.VERSION,
            extension_id=extension_id,
            version=version,
            publisher=publisher,
            actor=actor,
            reason=reason,
            state_after=GovernanceState.DISABLED,
            changed=True,
        )

    def quarantine_package(
        self,
        *,
        extension_id: str,
        publisher: str,
        actor: GovernanceActor,
        reason: str,
    ) -> GovernanceDecision:
        """Quarantine every version of one extension package."""
        self._require_authorized(actor, "quarantine an extension package")
        self._require_pinned_publisher(extension_id=extension_id, publisher=publisher)
        package = self._packages.setdefault(extension_id, _PackageState(publisher=publisher))
        package.state = GovernanceState.QUARANTINED
        return self._append(
            action="quarantined",
            target=GovernanceTarget.PACKAGE,
            extension_id=extension_id,
            version="*",
            publisher=publisher,
            actor=actor,
            reason=reason,
            state_after=GovernanceState.QUARANTINED,
            changed=True,
        )

    def quarantine_publisher(
        self, *, publisher: str, actor: GovernanceActor, reason: str
    ) -> GovernanceDecision:
        """Quarantine every package of one publisher (an explicit choice)."""
        self._require_authorized(actor, "quarantine a publisher")
        self._publishers[publisher] = GovernanceState.QUARANTINED
        return self._append(
            action="quarantined",
            target=GovernanceTarget.PUBLISHER,
            extension_id="*",
            version="*",
            publisher=publisher,
            actor=actor,
            reason=reason,
            state_after=GovernanceState.QUARANTINED,
            changed=True,
        )

    def re_enable_version(
        self,
        *,
        extension_id: str,
        version: str,
        publisher: str,
        actor: GovernanceActor,
        reason: str,
    ) -> GovernanceDecision:
        """Re-enable one version. Strikes and history are never erased."""
        self._require_authorized(actor, "re-enable an extension version")
        self._require_pinned_publisher(extension_id=extension_id, publisher=publisher)
        package = self._packages.setdefault(extension_id, _PackageState(publisher=publisher))
        package.versions[version] = GovernanceState.ACTIVE
        return self._append(
            action="version_re_enabled",
            target=GovernanceTarget.VERSION,
            extension_id=extension_id,
            version=version,
            publisher=publisher,
            actor=actor,
            reason=reason,
            state_after=GovernanceState.ACTIVE,
            changed=True,
        )

    def re_enable_package(
        self,
        *,
        extension_id: str,
        publisher: str,
        actor: GovernanceActor,
        reason: str,
    ) -> GovernanceDecision:
        """Lift a package quarantine. Strikes and history are never erased.

        ``state_after`` is the effective governing state, not the package
        layer alone: a quarantined publisher or disabled versions keep the
        identity suspended even after this lift.
        """
        self._require_authorized(actor, "re-enable an extension package")
        self._require_pinned_publisher(extension_id=extension_id, publisher=publisher)
        package = self._packages.setdefault(extension_id, _PackageState(publisher=publisher))
        package.state = GovernanceState.ACTIVE
        state_after, _ = self._governing(
            extension_id=extension_id, version="*", publisher=publisher
        )
        return self._append(
            action="package_re_enabled",
            target=GovernanceTarget.PACKAGE,
            extension_id=extension_id,
            version="*",
            publisher=publisher,
            actor=actor,
            reason=reason,
            state_after=state_after,
            changed=True,
        )

    def re_enable_publisher(
        self, *, publisher: str, actor: GovernanceActor, reason: str
    ) -> GovernanceDecision:
        """Lift a publisher quarantine. Strikes and history are never erased."""
        self._require_authorized(actor, "re-enable a publisher")
        self._publishers[publisher] = GovernanceState.ACTIVE
        return self._append(
            action="publisher_re_enabled",
            target=GovernanceTarget.PUBLISHER,
            extension_id="*",
            version="*",
            publisher=publisher,
            actor=actor,
            reason=reason,
            state_after=GovernanceState.ACTIVE,
            changed=True,
        )

    # -- introspection -------------------------------------------------------

    def strikes(self, *, extension_id: str, version: str, kind: EvidenceKind) -> int:
        """Lifetime strike count for one identity and evidence kind."""
        package = self._packages.get(extension_id)
        if package is None:
            return 0
        return package.strikes.get((version, kind.value), 0)

    def _require_authorized(self, actor: GovernanceActor, action: str) -> None:
        if actor.kind not in GOVERNANCE_ACTOR_KINDS:
            raise QuarantineAuthorityError(
                f"actor {actor.id!r} of kind {actor.kind.value!r} may not {action}: "
                "extensions hold no authority over their own governance state"
            )

    def _append(
        self,
        *,
        action: str,
        target: GovernanceTarget,
        extension_id: str,
        version: str,
        publisher: str,
        actor: GovernanceActor,
        reason: str,
        state_after: GovernanceState,
        evidence_digest: str = "",
        changed: bool,
    ) -> GovernanceDecision:
        event = self.ledger.append(
            GovernanceEvent(
                seq=0,
                at=self._clock(),
                action=action,
                target=target,
                extension_id=extension_id,
                version=version,
                publisher=publisher,
                actor=f"{actor.kind.value}:{actor.id}",
                reason=reason,
                state_after=state_after,
                evidence_digest=evidence_digest,
            )
        )
        return GovernanceDecision(
            seq=event.seq,
            target=target,
            extension_id=extension_id,
            version=version,
            publisher=publisher,
            state_after=state_after,
            reason=reason,
            changed=changed,
        )


class SandboxViolationBridge:
    """The M9-G2 → M9-G4 seam: sandbox boundary events become evidence.

    Feeds :class:`~maistro.extensions.isolation.SandboxViolationLog`-shaped
    violations into the governance service as :attr:`EvidenceKind.
    SANDBOX_VIOLATION` records, so the escalation the sandbox log warns
    about ("candidate for disable/quarantine") reaches the canonical flow
    that can actually suspend the extension.
    """

    def __init__(
        self,
        service: ExtensionGovernanceService,
        *,
        publisher: str,
        source: str = "sandbox",
    ) -> None:
        self._service = service
        self._publisher = publisher
        self._source = source

    def record(self, violation: ExtensionSandboxViolation) -> GovernanceDecision:
        """Attribute one boundary event and feed it to governance."""
        return self._service.record(
            ExtensionEvidence(
                kind=EvidenceKind.SANDBOX_VIOLATION,
                extension_id=violation.extension_id,
                version=violation.version,
                publisher=self._publisher,
                at=violation.at,
                source=self._source,
                detail=f"{violation.kind.value}: {violation.detail}",
            ),
            actor=GovernanceActor(kind=ActorKind.SYSTEM, id="sandbox-boundary"),
        )


def security_evidence(
    *,
    extension_id: str,
    version: str,
    publisher: str,
    detail: str,
    at: datetime | None = None,
) -> ExtensionEvidence:
    """Build a canonical security-violation evidence record (host-side seam)."""
    return ExtensionEvidence(
        kind=EvidenceKind.SECURITY_VIOLATION,
        extension_id=extension_id,
        version=version,
        publisher=publisher,
        at=at if at is not None else _utc_now(),
        source="security",
        detail=detail,
    )


def health_evidence(
    *,
    extension_id: str,
    version: str,
    publisher: str,
    detail: str,
    at: datetime | None = None,
) -> ExtensionEvidence:
    """Build a canonical health-failure evidence record (host-side seam)."""
    return ExtensionEvidence(
        kind=EvidenceKind.HEALTH_FAILURE,
        extension_id=extension_id,
        version=version,
        publisher=publisher,
        at=at if at is not None else _utc_now(),
        source="health",
        detail=detail,
    )
