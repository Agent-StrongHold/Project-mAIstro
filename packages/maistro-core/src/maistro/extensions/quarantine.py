"""Quarantine, disable and health-response authority for extensions (#972, M9-G4).

Canonical security and health evidence drives a governed suspension response
without ever letting the extension touch that response:

- **Canonical inputs.** Violations enter only as :class:`ExtensionViolationEvent`
  rows whose ``source`` must be a canonical host subsystem
  (:data:`CANONICAL_VIOLATION_SOURCES` — the Warden, the sandbox fence, the
  orchestrator, the health prober). An extension cannot fabricate evidence: a
  source it controls is refused closed, and every row carries full
  extension/version/publisher attribution plus an optional ``evidence_ref``
  pointing at the canonical Run/NodeRun/Attempt or Warden event that proved it.
- **Threshold/policy-driven states.** :class:`QuarantinePolicy` decides when
  evidence becomes suspension: a security violation at or above the severity
  floor quarantines immediately; repeated health failures strike out within a
  window and auto-quarantine at the limit. A single health failure below the
  limit is a *transient health failure* — recorded evidence, zero admission
  effect — and the three responses stay structurally distinct: package
  quarantine (``version=""``), version disable (one version), transient
  failure (no state change at all).
- **Immediate block.** Admission and suspension share one per-identity lock,
  so once :meth:`ExtensionQuarantineAuthority.quarantine` returns, no new
  invocation can be admitted — not for a UI request, not for a client retry.
  In-flight admissions are dispositioned by policy (cancel or let-finish) at
  the moment of suspension; completing them records evidence but can never
  lift the state.
- **Canonical re-enable.** Only an explicitly acted, accountable operator
  transition lifts a suspension. Actors under the reserved ``extension:``
  namespace — the identity the runtime attributes to extension-initiated
  actions — are refused, so an extension cannot write or clear its own
  quarantine/security state. Re-enable erases nothing: the store protocol has
  no delete or rewrite seam, and strike/violation history remains queryable.
- **Attribution without collateral damage.** Version disable condemns exactly
  the misbehaving version; unrelated signed versions keep running unless
  policy (or an explicit operator action) chooses publisher-wide quarantine.

The evidence ledger is append-only by construction — every retention question
is answered by keeping rows, never by rewriting them, and historical
invocation records stay queryable across any quarantine/re-enable cycle.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable

from maistro.capabilities.invocation import (
    TERMINAL_INVOCATION_STATUSES,
    InvocationStatus,
)
from maistro.extensions.types import ExtensionScope

__all__ = [
    "CANONICAL_VIOLATION_SOURCES",
    "ExtensionQuarantineAuthority",
    "ExtensionQuarantineError",
    "ExtensionQuarantined",
    "ExtensionViolationEvent",
    "HealthVerdict",
    "InFlightDisposition",
    "InMemoryQuarantineStore",
    "InvocationAdmission",
    "NonCanonicalViolationSource",
    "QuarantineNotActive",
    "QuarantinePolicy",
    "QuarantineRecord",
    "QuarantineState",
    "QuarantineStore",
    "QuarantineTransition",
    "UnauthorizedQuarantineActor",
    "ViolationKind",
    "ViolationSeverity",
    "severity_at_least",
]


# --------------------------------------------------------------------------
# Evidence vocabulary
# --------------------------------------------------------------------------


class ViolationKind(StrEnum):
    """Which canonical evidence stream a violation row came from."""

    SECURITY_POLICY = "security_policy"
    HEALTH_FAILURE = "health_failure"


class ViolationSeverity(StrEnum):
    """Severity of one canonical security event (ordered by :func:`severity_at_least`)."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


#: Total order over severities.
_SEVERITY_ORDER: dict[ViolationSeverity, int] = {
    ViolationSeverity.INFO: 0,
    ViolationSeverity.LOW: 1,
    ViolationSeverity.MEDIUM: 2,
    ViolationSeverity.HIGH: 3,
    ViolationSeverity.CRITICAL: 4,
}


def severity_at_least(candidate: ViolationSeverity, floor: ViolationSeverity) -> bool:
    """True when ``candidate`` meets or exceeds ``floor``."""
    return _SEVERITY_ORDER[candidate] >= _SEVERITY_ORDER[floor]


class InFlightDisposition(StrEnum):
    """What suspension does to already-admitted, unfinished invocations."""

    #: The host may let them run to completion; their outcomes stay evidence.
    LET_FINISH = "let_finish"
    #: The host must cancel them; completion records the honest terminal
    #: canonical receipt (``InvocationStatus.UNKNOWN``).
    CANCEL = "cancel"


#: Host subsystems allowed to report canonical violation evidence. Extension
#: code is not on this list: it cannot mint security or health events, for
#: itself or for anyone else.
CANONICAL_VIOLATION_SOURCES: frozenset[str] = frozenset(
    {"warden", "sandbox", "orchestrator", "health"}
)

#: Terminal canonical statuses an admitted invocation can end with. The
#: receipt reuses the canonical Binding→Invocation vocabulary
#: (``maistro.capabilities.invocation.InvocationStatus``) rather than minting
#: a second invocation-outcome vocabulary. A dispositioned invocation the
#: host cancelled ends ``UNKNOWN`` — the honest terminal answer at the effect
#: boundary, per the canonical reconciliation semantics.
_TERMINAL_OUTCOMES = frozenset(TERMINAL_INVOCATION_STATUSES)

#: Actor namespace reserved for extension-attributed actions. The runtime
#: names extension-initiated activity ``extension:<id>``; a state change under
#: that actor is by definition the extension trying to govern itself.
RESERVED_ACTOR_PREFIX = "extension:"


class ExtensionQuarantineError(RuntimeError):
    """Base class for quarantine/health-response failures."""


class ExtensionQuarantined(ExtensionQuarantineError):
    """An invocation was refused because the extension is suspended.

    Carries the durable reason from the quarantine record — the same answer
    every later "why was this refused" query returns.
    """


class UnauthorizedQuarantineActor(ExtensionQuarantineError):
    """A state-changing action was attempted under a reserved identity.

    Quarantine and re-enable are canonical operator/authority actions. An
    actor in the reserved ``extension:`` namespace is the extension itself,
    and the one thing this subsystem exists to guarantee is that an extension
    can never write or clear its own security state.
    """


class NonCanonicalViolationSource(ExtensionQuarantineError):
    """Violation evidence was reported from outside the canonical sources.

    Only host subsystems (Warden, sandbox, orchestrator, health prober) can
    mint violation rows. Anything else — including anything an extension
    supplies — is refused before it can pollute the ledger or trigger a
    quarantine.
    """


class QuarantineNotActive(ExtensionQuarantineError):
    """Re-enable was requested but nothing is suspended for that target."""


@dataclass(frozen=True)
class ExtensionViolationEvent:
    """One append-only canonical evidence row (retained forever)."""

    seq: int
    at: datetime
    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    publisher_id: str
    kind: ViolationKind
    severity: ViolationSeverity
    source: str
    reason: str
    #: Canonical pointer to the proving evidence ("run:<id>", "attempt:<id>",
    #: "warden:<event id>", ...). Retained verbatim; never parsed here.
    evidence_ref: str = ""


class QuarantineState(StrEnum):
    """Durable suspension states; a target's record persists after lifting."""

    NONE = "none"
    QUARANTINED = "quarantined"
    DISABLED = "disabled"


@dataclass(frozen=True)
class QuarantineRecord:
    """The durable suspension state for one target.

    ``version`` is the exact installed version for a version disable, or the
    empty string for a package-wide quarantine. A lifted target keeps its row
    with :attr:`QuarantineState.NONE` so re-suspensions have a true
    ``from_state``; only the audit trail carries the full story.
    """

    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    publisher_id: str
    state: QuarantineState
    reason: str
    actor: str
    #: Health strikes already within the policy window when this suspension
    #: landed, kept on the record so the durable answer to "how bad was it"
    #: survives next to the state.
    strikes: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def suspended(self) -> bool:
        """True while this record actually blocks invocations."""
        return self.state is not QuarantineState.NONE


@dataclass(frozen=True)
class QuarantineTransition:
    """One audited suspension/re-enable transition (canonical evidence)."""

    seq: int
    at: datetime
    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    actor: str
    from_state: QuarantineState
    to_state: QuarantineState
    reason: str


@dataclass(frozen=True)
class InvocationAdmission:
    """One admitted invocation: an inert, frozen evidence token.

    Deliberately data-only — no service, store or container back-reference —
    so the surface extension code can ever observe carries no state-mutating
    capability. Suspension dispositions land as replacement rows in the
    store, never by mutating this object.
    """

    admission_id: str
    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    publisher_id: str
    admitted_at: datetime
    open: bool = True
    #: Terminal canonical invocation status recorded at completion.
    outcome: InvocationStatus | None = None
    #: Set when suspension dispositioned this in-flight invocation.
    disposition: InFlightDisposition | None = None
    quarantined_at: datetime | None = None


@dataclass(frozen=True)
class HealthVerdict:
    """Result of recording one health failure."""

    strikes_in_window: int
    cumulative_failures: int
    quarantined: bool
    record: QuarantineRecord | None


@dataclass(frozen=True)
class QuarantinePolicy:
    """Thresholds turning canonical evidence into suspension.

    ``severity_floor`` — a security violation at or above this severity
    quarantines immediately. ``publisher_wide_on_severe`` chooses the blast
    radius of such an auto-quarantine: ``False`` (default) disables exactly
    the violating version; ``True`` condemns every version of the extension —
    the publisher-wide action the issue reserves for policy to choose.
    Health failures strike within ``health_strike_window``; the
    ``health_strike_limit``-th failure within the window auto-quarantines the
    failing version. Suspension disposition of in-flight work is
    ``in_flight_disposition``.
    """

    severity_floor: ViolationSeverity = ViolationSeverity.HIGH
    publisher_wide_on_severe: bool = False
    health_strike_limit: int = 3
    health_strike_window: timedelta = timedelta(minutes=10)
    in_flight_disposition: InFlightDisposition = InFlightDisposition.CANCEL

    def __post_init__(self) -> None:
        if self.health_strike_limit < 1:
            raise ValueError("health_strike_limit must be >= 1")
        if self.health_strike_window <= timedelta(0):
            raise ValueError("health_strike_window must be positive")


# --------------------------------------------------------------------------
# Store seam
# --------------------------------------------------------------------------


@runtime_checkable
class QuarantineStore(Protocol):
    """Persistence seam for suspension state and the append-only evidence.

    Deliberately no delete, history-trimming or ledger-rewrite method exists:
    audit/history retention is structural, not a promise.
    """

    async def save_record(self, record: QuarantineRecord) -> None: ...

    async def record_for(
        self, scope: ExtensionScope, extension_id: str, version: str
    ) -> QuarantineRecord | None: ...

    async def records_for_extension(
        self, scope: ExtensionScope, extension_id: str
    ) -> tuple[QuarantineRecord, ...]: ...

    async def append_event(self, event: ExtensionViolationEvent) -> None: ...

    async def events_for(
        self, scope: ExtensionScope, extension_id: str
    ) -> tuple[ExtensionViolationEvent, ...]: ...

    async def next_event_seq(self) -> int: ...

    async def append_transition(self, transition: QuarantineTransition) -> None: ...

    async def transitions_for(
        self, scope: ExtensionScope, extension_id: str
    ) -> tuple[QuarantineTransition, ...]: ...

    async def next_transition_seq(self) -> int: ...

    async def save_admission(self, admission: InvocationAdmission) -> None: ...

    async def admissions_for(
        self, scope: ExtensionScope, extension_id: str
    ) -> tuple[InvocationAdmission, ...]: ...


class InMemoryQuarantineStore:
    """Process-lifetime reference implementation of :class:`QuarantineStore`."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str, str], QuarantineRecord] = {}
        self._events: list[ExtensionViolationEvent] = []
        self._transitions: list[QuarantineTransition] = []
        self._admissions: dict[str, InvocationAdmission] = {}
        self._event_seq = 0
        self._transition_seq = 0

    @staticmethod
    def _key(scope: ExtensionScope, extension_id: str, version: str) -> tuple[str, str, str, str]:
        return (scope.org_id, scope.workspace_id, extension_id, version)

    @staticmethod
    def _record_key(record: QuarantineRecord) -> tuple[str, str, str, str]:
        return (record.org_id, record.workspace_id, record.extension_id, record.version)

    async def save_record(self, record: QuarantineRecord) -> None:
        self._records[self._record_key(record)] = record

    async def record_for(
        self, scope: ExtensionScope, extension_id: str, version: str
    ) -> QuarantineRecord | None:
        return self._records.get(self._key(scope, extension_id, version))

    async def records_for_extension(
        self, scope: ExtensionScope, extension_id: str
    ) -> tuple[QuarantineRecord, ...]:
        return tuple(
            record
            for record in self._records.values()
            if record.org_id == scope.org_id
            and record.workspace_id == scope.workspace_id
            and record.extension_id == extension_id
        )

    async def append_event(self, event: ExtensionViolationEvent) -> None:
        self._events.append(event)

    async def events_for(
        self, scope: ExtensionScope, extension_id: str
    ) -> tuple[ExtensionViolationEvent, ...]:
        return tuple(
            event
            for event in self._events
            if event.org_id == scope.org_id
            and event.workspace_id == scope.workspace_id
            and event.extension_id == extension_id
        )

    async def next_event_seq(self) -> int:
        self._event_seq += 1
        return self._event_seq

    async def append_transition(self, transition: QuarantineTransition) -> None:
        self._transitions.append(transition)

    async def transitions_for(
        self, scope: ExtensionScope, extension_id: str
    ) -> tuple[QuarantineTransition, ...]:
        return tuple(
            transition
            for transition in self._transitions
            if transition.org_id == scope.org_id
            and transition.workspace_id == scope.workspace_id
            and transition.extension_id == extension_id
        )

    async def next_transition_seq(self) -> int:
        self._transition_seq += 1
        return self._transition_seq

    async def save_admission(self, admission: InvocationAdmission) -> None:
        self._admissions[admission.admission_id] = admission

    async def admissions_for(
        self, scope: ExtensionScope, extension_id: str
    ) -> tuple[InvocationAdmission, ...]:
        return tuple(
            admission
            for admission in self._admissions.values()
            if admission.org_id == scope.org_id
            and admission.workspace_id == scope.workspace_id
            and admission.extension_id == extension_id
        )


# --------------------------------------------------------------------------
# Authority service
# --------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(UTC)


#: Resolves the publisher attribution for one installed version from the
#: canonical registry (the B1 install records). Wired by hosts that hold the
#: registry; an absent or ``None`` result falls back to the reporter's claim.
PublisherResolver = Callable[[ExtensionScope, str, str], "str | None"]


def _require_canonical_actor(actor: str) -> None:
    """Every state change needs an accountable, non-extension actor."""
    if not actor.strip():
        raise ValueError("actor is required: every quarantine action needs an accountable actor")
    if actor.strip().lower().startswith(RESERVED_ACTOR_PREFIX):
        raise UnauthorizedQuarantineActor(
            f"actor {actor!r} is in the reserved {RESERVED_ACTOR_PREFIX!r} namespace: "
            "an extension cannot quarantine, disable or re-enable itself (or anything else)"
        )


def _require_reason(reason: str) -> None:
    if not reason.strip():
        raise ValueError(
            "reason is required: a suspension or re-enable without a recorded "
            "reason is not auditable evidence"
        )


class ExtensionQuarantineAuthority:
    """The one authority that turns canonical evidence into suspension.

    Every state change and every admission serializes per extension identity
    on a single lock, which is what makes the quarantine-landed-then-admit
    race unloseable: once :meth:`quarantine` returns, the state is durable
    and every later admission reads it under the same lock. Admission reads
    and admits atomically — there is no window in which a check can pass and
    a concurrent suspension land between the check and the admit.
    """

    def __init__(
        self,
        store: QuarantineStore,
        *,
        policy: QuarantinePolicy | None = None,
        clock: Callable[[], datetime] = _utc_now,
        admission_id_factory: Callable[[], str] | None = None,
        publisher_for: PublisherResolver | None = None,
    ) -> None:
        self._store = store
        self._policy = policy or QuarantinePolicy()
        self._clock = clock
        self._admission_id_factory = admission_id_factory or (lambda: uuid.uuid4().hex)
        self._publisher_for = publisher_for
        self._locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    # -- reads ------------------------------------------------------------

    async def state(self, scope: ExtensionScope, extension_id: str) -> tuple[QuarantineRecord, ...]:
        """Every suspension record (live and lifted) for the extension in ``scope``."""
        return await self._store.records_for_extension(scope, extension_id)

    async def violation_history(
        self, scope: ExtensionScope, extension_id: str
    ) -> tuple[ExtensionViolationEvent, ...]:
        """The full append-only violation ledger (quarantine-proof)."""
        return await self._store.events_for(scope, extension_id)

    async def transition_history(
        self, scope: ExtensionScope, extension_id: str
    ) -> tuple[QuarantineTransition, ...]:
        """The audited suspension/re-enable transition trail."""
        return await self._store.transitions_for(scope, extension_id)

    async def invocation_history(
        self, scope: ExtensionScope, extension_id: str
    ) -> tuple[InvocationAdmission, ...]:
        """Every admission ever recorded, with outcomes (quarantine-proof)."""
        return await self._store.admissions_for(scope, extension_id)

    async def in_flight(
        self, scope: ExtensionScope, extension_id: str
    ) -> tuple[InvocationAdmission, ...]:
        """Open admissions with their current dispositions.

        The token :meth:`admit_invocation` returns is an admission-time
        snapshot; hosts draining suspended work read the authoritative rows
        here — a suspension records each admission's disposition in the
        store at the moment it lands.
        """
        return tuple(
            admission
            for admission in await self._store.admissions_for(scope, extension_id)
            if admission.open
        )

    # -- invocation admission -------------------------------------------------

    async def admit_invocation(
        self, scope: ExtensionScope, extension_id: str, version: str
    ) -> InvocationAdmission:
        """Admit one new invocation or refuse it closed.

        Refusal is unconditional while a package quarantine or a version
        disable covers the request — the caller (UI, client, scheduler) has
        no bypass. Suspended targets get :class:`ExtensionQuarantined` with
        the durable reason.
        """
        if not extension_id.strip() or not version.strip():
            raise ValueError("extension_id and version are required to admit an invocation")
        async with self._lock(scope, extension_id):
            return await self._admit_locked(scope, extension_id, version)

    async def _admit_locked(
        self, scope: ExtensionScope, extension_id: str, version: str
    ) -> InvocationAdmission:
        package = await self._store.record_for(scope, extension_id, "")
        if package is not None and package.suspended:
            raise ExtensionQuarantined(
                f"extension {extension_id} is quarantined in {scope.describe}: {package.reason}"
            )
        version_record = await self._store.record_for(scope, extension_id, version)
        if version_record is not None and version_record.suspended:
            raise ExtensionQuarantined(
                f"extension {extension_id} version {version} is disabled in "
                f"{scope.describe}: {version_record.reason}"
            )
        admission = InvocationAdmission(
            admission_id=self._admission_id_factory(),
            org_id=scope.org_id,
            workspace_id=scope.workspace_id,
            extension_id=extension_id,
            version=version,
            publisher_id=self._publisher(scope, extension_id, version),
            admitted_at=self._clock(),
        )
        await self._store.save_admission(admission)
        return admission

    async def complete_invocation(
        self, admission: InvocationAdmission, *, outcome: InvocationStatus
    ) -> InvocationAdmission:
        """Close an admitted invocation, recording its outcome as evidence.

        ``outcome`` is the canonical terminal invocation status: COMPLETED,
        FAILED, or UNKNOWN — the honest terminal receipt for work a
        suspension dispositioned and the host cancelled. Completion is
        bookkeeping only: it can never alter suspension state, clear
        strikes, or rewrite the ledger.
        """
        if outcome not in _TERMINAL_OUTCOMES:
            raise ValueError(
                "outcome must be a terminal canonical invocation status "
                f"{sorted(str(s) for s in _TERMINAL_OUTCOMES)}, got {outcome!r}"
            )
        scope = ExtensionScope(org_id=admission.org_id, workspace_id=admission.workspace_id)
        async with self._lock(scope, admission.extension_id):
            current = await self._find_admission_locked(
                scope, admission.extension_id, admission.admission_id
            )
            if current is None or not current.open:
                raise ExtensionQuarantineError(
                    f"admission {admission.admission_id} is not open; "
                    "an invocation completes at most once"
                )
            closed = replace(current, open=False, outcome=outcome)
            await self._store.save_admission(closed)
            return closed

    # -- canonical evidence inputs ---------------------------------------------

    async def record_security_violation(
        self,
        scope: ExtensionScope,
        extension_id: str,
        version: str,
        *,
        source: str,
        severity: ViolationSeverity,
        reason: str,
        evidence_ref: str = "",
        publisher_id: str = "",
    ) -> tuple[ExtensionViolationEvent, QuarantineRecord | None]:
        """Record one canonical security violation; quarantine per policy.

        The event always lands. When the severity meets the policy floor the
        suspension is immediate: publisher-wide if the policy chose that
        action, otherwise exactly the violating version. Below the floor the
        violation is retained evidence with no admission effect.
        """
        if source not in CANONICAL_VIOLATION_SOURCES:
            raise NonCanonicalViolationSource(
                f"violation source {source!r} is not a canonical security/health "
                f"subsystem {sorted(CANONICAL_VIOLATION_SOURCES)}; extension-controlled "
                "sources cannot mint security evidence"
            )
        if not reason.strip():
            raise ValueError("reason is required: violation evidence must say what happened")
        async with self._lock(scope, extension_id):
            event = await self._append_event_locked(
                scope,
                extension_id,
                version,
                kind=ViolationKind.SECURITY_POLICY,
                severity=severity,
                source=source,
                reason=reason,
                evidence_ref=evidence_ref,
                publisher_id=publisher_id,
            )
            if not severity_at_least(severity, self._policy.severity_floor):
                return event, None
            target = "" if self._policy.publisher_wide_on_severe else version
            state = QuarantineState.QUARANTINED if target == "" else QuarantineState.DISABLED
            record = await self._suspend_locked(scope, extension_id, target, state, event)
            return event, record

    async def record_health_failure(
        self,
        scope: ExtensionScope,
        extension_id: str,
        version: str,
        *,
        reason: str,
        source: str = "health",
        evidence_ref: str = "",
        publisher_id: str = "",
    ) -> HealthVerdict:
        """Record one health failure; strike out and auto-quarantine per policy.

        A failure below the strike limit is a transient health failure: the
        event is retained but the extension keeps admitting work. The
        limit-th failure within the window suspends the failing version
        immediately and disposition in-flight work per policy.
        """
        if source not in CANONICAL_VIOLATION_SOURCES:
            raise NonCanonicalViolationSource(
                f"health source {source!r} is not a canonical security/health "
                f"subsystem {sorted(CANONICAL_VIOLATION_SOURCES)}"
            )
        if not reason.strip():
            raise ValueError("reason is required: health evidence must say what failed")
        async with self._lock(scope, extension_id):
            event = await self._append_event_locked(
                scope,
                extension_id,
                version,
                kind=ViolationKind.HEALTH_FAILURE,
                severity=ViolationSeverity.MEDIUM,
                source=source,
                reason=reason,
                evidence_ref=evidence_ref,
                publisher_id=publisher_id,
            )
            strikes = await self._strikes_in_window(scope, extension_id, version)
            cumulative = await self._cumulative_failures(scope, extension_id, version)
            if strikes >= self._policy.health_strike_limit:
                record = await self._suspend_locked(
                    scope, extension_id, version, QuarantineState.DISABLED, event
                )
                return HealthVerdict(
                    strikes_in_window=strikes,
                    cumulative_failures=cumulative,
                    quarantined=True,
                    record=record,
                )
            return HealthVerdict(
                strikes_in_window=strikes,
                cumulative_failures=cumulative,
                quarantined=False,
                record=None,
            )

    # -- canonical operator actions ----------------------------------------------

    async def quarantine(
        self,
        scope: ExtensionScope,
        extension_id: str,
        *,
        actor: str,
        reason: str,
        version: str | None = None,
    ) -> QuarantineRecord:
        """Suspend immediately by canonical operator/authority action.

        ``version=None`` quarantines the whole package (every version); a
        version string disables exactly that version. Re-affirming an
        already-active identical suspension refreshes the durable reason
        without a duplicate transition.
        """
        _require_canonical_actor(actor)
        _require_reason(reason)
        target = version or ""
        state = QuarantineState.QUARANTINED if target == "" else QuarantineState.DISABLED
        async with self._lock(scope, extension_id):
            existing = await self._store.record_for(scope, extension_id, target)
            if existing is not None and existing.state is state:
                return await self._save_record_locked(
                    replace(existing, reason=reason, actor=actor, updated_at=self._clock())
                )
            record = await self._suspend_locked(
                scope,
                extension_id,
                target,
                state,
                trigger_reason=reason,
                actor=actor,
                from_state=existing.state if existing else QuarantineState.NONE,
            )
            return record

    async def reenable(
        self,
        scope: ExtensionScope,
        extension_id: str,
        *,
        actor: str,
        reason: str,
        version: str | None = None,
    ) -> QuarantineRecord:
        """Lift a suspension by canonical authorized action.

        Erases nothing: the violation ledger, strike evidence and transition
        history predate and postdate this transition untouched. A version
        re-enable cannot defeat a package-level quarantine — lift the
        quarantine itself, explicitly, or the extension stays suspended.
        """
        _require_canonical_actor(actor)
        _require_reason(reason)
        target = version or ""
        async with self._lock(scope, extension_id):
            if target:
                package = await self._store.record_for(scope, extension_id, "")
                if package is not None and package.suspended:
                    raise QuarantineNotActive(
                        f"extension {extension_id} is package-quarantined in {scope.describe}; "
                        "re-enable the package explicitly — a version re-enable cannot "
                        "undercut a package quarantine"
                    )
            existing = await self._store.record_for(scope, extension_id, target)
            if existing is None or not existing.suspended:
                where = f"version {target}" if target else "package"
                raise QuarantineNotActive(
                    f"extension {extension_id} {where} is not suspended in {scope.describe}"
                )
            return await self._lift_locked(
                scope,
                extension_id,
                target,
                actor=actor,
                reason=reason,
                from_state=existing.state,
            )

    # -- internals -----------------------------------------------------------

    def _lock(self, scope: ExtensionScope, extension_id: str) -> asyncio.Lock:
        # No await between check and set: lazy creation is safe on one loop.
        key = (scope.org_id, scope.workspace_id, extension_id)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _publisher(self, scope: ExtensionScope, extension_id: str, version: str) -> str:
        if self._publisher_for is not None:
            resolved = self._publisher_for(scope, extension_id, version)
            if resolved is not None:
                return resolved
        return ""

    async def _append_event_locked(
        self,
        scope: ExtensionScope,
        extension_id: str,
        version: str,
        *,
        kind: ViolationKind,
        severity: ViolationSeverity,
        source: str,
        reason: str,
        evidence_ref: str,
        publisher_id: str,
    ) -> ExtensionViolationEvent:
        event = ExtensionViolationEvent(
            seq=await self._store.next_event_seq(),
            at=self._clock(),
            org_id=scope.org_id,
            workspace_id=scope.workspace_id,
            extension_id=extension_id,
            version=version,
            publisher_id=publisher_id or self._publisher(scope, extension_id, version),
            kind=kind,
            severity=severity,
            source=source,
            reason=reason,
            evidence_ref=evidence_ref,
        )
        await self._store.append_event(event)
        return event

    async def _suspend_locked(
        self,
        scope: ExtensionScope,
        extension_id: str,
        target: str,
        state: QuarantineState,
        trigger: ExtensionViolationEvent | None = None,
        *,
        trigger_reason: str | None = None,
        actor: str = "policy:auto-quarantine",
        from_state: QuarantineState | None = None,
    ) -> QuarantineRecord:
        """Land a suspension and disposition in-flight work, atomically."""
        existing = await self._store.record_for(scope, extension_id, target)
        if existing is not None and existing.state is state:
            # Already suspended identically: refresh the reason, no duplicate
            # transition, in-flight already dispositioned by the first pass.
            return await self._refresh_suspension_locked(existing, trigger, trigger_reason)
        now = self._clock()
        reason = self._suspension_reason(trigger, trigger_reason)
        strikes = await self._strikes_in_window(scope, extension_id, target)
        record = await self._suspension_record(
            scope, extension_id, target, state, reason, actor, strikes, now
        )
        await self._store.save_record(record)
        await self._store.append_transition(
            QuarantineTransition(
                seq=await self._store.next_transition_seq(),
                at=now,
                org_id=scope.org_id,
                workspace_id=scope.workspace_id,
                extension_id=extension_id,
                version=target,
                actor=actor,
                from_state=self._previous_state(existing, from_state),
                to_state=state,
                reason=reason,
            )
        )
        await self._disposition_in_flight_locked(scope, extension_id, now)
        return record

    async def _refresh_suspension_locked(
        self,
        existing: QuarantineRecord,
        trigger: ExtensionViolationEvent | None,
        trigger_reason: str | None,
    ) -> QuarantineRecord:
        """Refresh an identical active suspension's reason; no new transition."""
        if trigger_reason is not None:
            refreshed_reason = trigger_reason
        elif trigger is not None:
            refreshed_reason = trigger.reason
        else:
            refreshed_reason = existing.reason
        return await self._save_record_locked(
            replace(existing, reason=refreshed_reason, updated_at=self._clock())
        )

    @staticmethod
    def _suspension_reason(
        trigger: ExtensionViolationEvent | None, trigger_reason: str | None
    ) -> str:
        """The durable "why is this suspended" line for record and trail."""
        if trigger is None:
            return trigger_reason or ""
        evidence = trigger.evidence_ref or "n/a"
        return (
            f"{trigger.kind} evidence from {trigger.source} "
            f"(severity {trigger.severity}, evidence {evidence}): {trigger.reason}"
        )

    @staticmethod
    def _previous_state(
        existing: QuarantineRecord | None, from_state: QuarantineState | None
    ) -> QuarantineState:
        if from_state is not None:
            return from_state
        return existing.state if existing else QuarantineState.NONE

    async def _suspension_record(
        self,
        scope: ExtensionScope,
        extension_id: str,
        target: str,
        state: QuarantineState,
        reason: str,
        actor: str,
        strikes: int,
        now: datetime,
    ) -> QuarantineRecord:
        package = await self._store.record_for(scope, extension_id, "")
        publisher = (package.publisher_id if package else "") or self._publisher(
            scope, extension_id, target
        )
        return QuarantineRecord(
            org_id=scope.org_id,
            workspace_id=scope.workspace_id,
            extension_id=extension_id,
            version=target,
            publisher_id=publisher,
            state=state,
            reason=reason,
            actor=actor,
            strikes=strikes,
            created_at=now,
            updated_at=now,
        )

    async def _lift_locked(
        self,
        scope: ExtensionScope,
        extension_id: str,
        target: str,
        *,
        actor: str,
        reason: str,
        from_state: QuarantineState,
    ) -> QuarantineRecord:
        existing = await self._store.record_for(scope, extension_id, target)
        assert existing is not None  # callers verify the suspension exists
        lifted = await self._save_record_locked(
            replace(
                existing,
                state=QuarantineState.NONE,
                reason=reason,
                actor=actor,
                updated_at=self._clock(),
            )
        )
        await self._store.append_transition(
            QuarantineTransition(
                seq=await self._store.next_transition_seq(),
                at=self._clock(),
                org_id=scope.org_id,
                workspace_id=scope.workspace_id,
                extension_id=extension_id,
                version=target,
                actor=actor,
                from_state=from_state,
                to_state=QuarantineState.NONE,
                reason=reason,
            )
        )
        return lifted

    async def _save_record_locked(self, record: QuarantineRecord) -> QuarantineRecord:
        await self._store.save_record(record)
        return record

    async def _disposition_in_flight_locked(
        self, scope: ExtensionScope, extension_id: str, now: datetime
    ) -> int:
        """Apply the policy's in-flight disposition to every open admission."""
        dispositioned = 0
        for admission in await self._store.admissions_for(scope, extension_id):
            if not admission.open or admission.disposition is not None:
                continue
            await self._store.save_admission(
                replace(
                    admission,
                    disposition=self._policy.in_flight_disposition,
                    quarantined_at=now,
                )
            )
            dispositioned += 1
        return dispositioned

    async def _strikes_in_window(
        self, scope: ExtensionScope, extension_id: str, version: str
    ) -> int:
        now = self._clock()
        window_start = now - self._policy.health_strike_window
        return sum(
            1
            for event in await self._store.events_for(scope, extension_id)
            if event.kind is ViolationKind.HEALTH_FAILURE
            and event.version == version
            and window_start <= event.at <= now
        )

    async def _cumulative_failures(
        self, scope: ExtensionScope, extension_id: str, version: str
    ) -> int:
        return sum(
            1
            for event in await self._store.events_for(scope, extension_id)
            if event.kind is ViolationKind.HEALTH_FAILURE and event.version == version
        )

    async def _find_admission_locked(
        self, scope: ExtensionScope, extension_id: str, admission_id: str
    ) -> InvocationAdmission | None:
        for admission in await self._store.admissions_for(scope, extension_id):
            if admission.admission_id == admission_id:
                return admission
        return None
