"""Truthful extension operational status, error taxonomy, and telemetry
(M9-I3, issue #978).

The install lifecycle (#953) says whether an extension *was activated*. This
module answers the operator's next questions without ever accepting an
extension's word for it:

- **Operational status projection** — :func:`project_operational_status`
  derives one extension version's operational state from canonical evidence
  only: the install record's lifecycle state, a *fresh* compatibility
  evaluation against the platform and the scope's currently active set, the
  readiness of every declared dependency, host-recorded invocation outcomes,
  and the durable operator decision (enabled/disabled/quarantined). An
  extension cannot report itself ready, healthy, or compatible; it can only
  be observed into those states.
- **Readiness versus liveness** — the same distinction ADR-038 draws for
  services, drawn per extension. ``live`` means the activated record still
  exists in the runtime; ``ready`` additionally requires authorization,
  current compatibility, dependency readiness, health, and an enabled
  operator state. An installed-but-incompatible, unauthorized, quarantined,
  disabled, or unhealthy extension can never project ``ready``.
- **Error taxonomy** — :class:`ExtensionErrorRecord` preserves *provenance*
  (extension id, version, and — for dependency failures — the failing
  dependency and its version) and classifies failures into
  dependency/extension/policy/platform kinds, so a transient dependency
  failure is never recorded as the extension's own fault.
- **Usage telemetry** — host-recorded :class:`ExtensionObservation` rows
  (latency always, cost only when actually metered — an unmeasured metric is
  absent, not zero, per ADR-083026-a91e) aggregate into per-version digests
  that rank extensions by usage, cost, errors, and latency, and feed SLO
  error-budget inputs in the ADR-038 shape.

Durability contract: operator decisions and observations are stored through
:class:`ExtensionHealthStore`. The SQLite twin
(:class:`maistro.extensions.sqlite_health_store.SqliteExtensionHealthStore`)
makes projected health survive a restart: a quarantined extension is still
quarantined, and the observations that made it unhealthy are still there,
after the process that recorded them is gone. Historical telemetry keeps the
exact version string it was recorded under, so a removed or superseded
version stays identifiable — and, keyed against the scope's current active
record, never reports itself active.

The lifecycle service consumes the *same* install store instance the
install-lifecycle service owns (the container wires them together), so the
projections below read lifecycle evidence from the one canonical record of
activation — never from a copy that could drift.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from maistro.extensions.compatibility import (
    CompatibilityReport,
    _range_satisfied,
    evaluate_platform_compatibility,
)
from maistro.extensions.store import ExtensionStore
from maistro.extensions.types import (
    TERMINAL_STATES,
    ExtensionInstallRecord,
    ExtensionManifest,
    ExtensionScope,
    ExtensionState,
)

#: Floor for "newest record" comparisons — the same sentinel store.py uses
#: for records created before timestamps were mandatory.
_EPOCH_FLOOR = datetime.min.replace(tzinfo=UTC)

__all__ = [
    "HEALTHY_STATES",
    "HEALTH_WINDOW",
    "DependencyReadiness",
    "ExtensionErrorKind",
    "ExtensionErrorRecord",
    "ExtensionHealth",
    "ExtensionHealthService",
    "ExtensionHealthStore",
    "ExtensionObservation",
    "ExtensionOperationalState",
    "ExtensionOperationalStatus",
    "ExtensionOperatorAction",
    "ExtensionOperatorState",
    "ExtensionUsageDigest",
    "ObservationOutcome",
    "OperatorDecision",
    "RankingMetric",
    "SloPosition",
    "TelemetryExport",
    "dependency_readiness",
    "digest_observations",
    "evaluate_health",
    "latest_decision",
    "operator_state_for",
    "project_operational_status",
    "rank_digests",
    "slo_position",
    "state_for_action",
]


# --------------------------------------------------------------------------
# Error taxonomy (#978): kinds and provenance-preserving records
# --------------------------------------------------------------------------


class ExtensionErrorKind(StrEnum):
    """Root cause classes of extension failures.

    The taxonomy is deliberately small and provenance-first. ``DEPENDENCY``
    failures are *transient and external* — a declared dependency or its
    provider is failing; they are recorded against the extension's history
    but evaluated as the dependency's condition, never as the extension's
    own fault. ``EXTENSION`` faults belong to the extension's behavior.
    ``POLICY`` covers refusals the platform's rules produced, and
    ``PLATFORM`` covers host-side machinery (loader, store, wiring). Health
    evaluation treats these classes differently, which is exactly what makes
    a transient dependency failure distinguishable from a quarantine or a
    disable in the projection.
    """

    DEPENDENCY = "dependency"
    EXTENSION = "extension"
    POLICY = "policy"
    PLATFORM = "platform"


@dataclass(frozen=True)
class ExtensionErrorRecord:
    """One classified extension failure, with full provenance.

    ``extension_id`` and ``version`` are the identity that actually served —
    recorded verbatim, never rewritten to the currently active version, so a
    removed version remains identifiable in historical telemetry.
    ``dependency``/``dependency_version`` name the failing dependency when
    (and only when) ``kind`` is :attr:`ExtensionErrorKind.DEPENDENCY`; the
    invariant is enforced at construction, so a dependency failure cannot be
    recorded without its dependency provenance.
    """

    error_id: str
    at: datetime
    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    kind: ExtensionErrorKind
    #: Short machine-readable cause code (e.g. ``"provider_unreachable"``).
    code: str
    #: Human-readable detail. Must not carry secrets; this is exportable
    #: telemetry and it outlives the process that wrote it.
    message: str
    dependency: str | None = None
    dependency_version: str | None = None

    def __post_init__(self) -> None:
        if self.kind is ExtensionErrorKind.DEPENDENCY and not self.dependency:
            raise ValueError(
                "a dependency-kind error must name the dependency it failed on: "
                "provenance is the record's purpose"
            )
        if self.kind is not ExtensionErrorKind.DEPENDENCY and self.dependency is not None:
            raise ValueError(
                f"only dependency-kind errors carry dependency provenance, not {self.kind}"
            )


# --------------------------------------------------------------------------
# Host-recorded invocation evidence (#978)
# --------------------------------------------------------------------------


class ObservationOutcome(StrEnum):
    """What the host saw when an invocation finished.

    Recorded by the host that made the call — the one seam extensions cannot
    reach — so the record is canonical evidence, not self-report. There is
    deliberately no API by which an extension could file its own health.
    """

    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True)
class ExtensionObservation:
    """One host-recorded extension invocation outcome.

    ``latency_ms`` is host-measured wall time. ``cost_units`` carries the
    metered cost *only when the host actually measured one*; ``None`` means
    unmeasured and is excluded from cost aggregation (absent, not zero —
    ADR-083026-a91e). ``version`` is the exact version that served, so
    history stays attributable after upgrades and removals. A failed
    observation must carry its classified error; a successful one must not.
    """

    observation_id: str
    at: datetime
    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    latency_ms: float
    outcome: ObservationOutcome
    cost_units: float | None = None
    #: The classified failure, present exactly when ``outcome`` is FAILURE.
    error: ExtensionErrorRecord | None = None

    def __post_init__(self) -> None:
        if self.outcome is ObservationOutcome.FAILURE and self.error is None:
            raise ValueError("a failed observation must carry its classified ExtensionErrorRecord")
        if self.outcome is ObservationOutcome.SUCCESS and self.error is not None:
            raise ValueError("a successful observation cannot carry an error record")


# --------------------------------------------------------------------------
# Operator policy state (#978): durable enable/disable/quarantine
# --------------------------------------------------------------------------


class ExtensionOperatorAction(StrEnum):
    """Operator decisions over an extension's runtime admission.

    ``RELEASE`` returns a held extension to service; its meaning is "the
    hold is lifted", whatever the hold was.
    """

    ENABLE = "enable"
    DISABLE = "disable"
    QUARANTINE = "quarantine"
    RELEASE = "release"


class ExtensionOperatorState(StrEnum):
    """The durable runtime-admission state an operator decision produces.

    Distinct held states on purpose: ``DISABLED`` is a deliberate operator
    stop, ``QUARANTINED`` is a hold pending investigation. Neither is a
    health judgement, and the projection never collapses one into the other
    or into "unhealthy" — the acceptance criteria require exactly that
    distinction to survive restarts and dashboards.
    """

    ENABLED = "enabled"
    DISABLED = "disabled"
    QUARANTINED = "quarantined"


_ACTION_STATES: dict[ExtensionOperatorAction, ExtensionOperatorState] = {
    ExtensionOperatorAction.ENABLE: ExtensionOperatorState.ENABLED,
    ExtensionOperatorAction.DISABLE: ExtensionOperatorState.DISABLED,
    ExtensionOperatorAction.QUARANTINE: ExtensionOperatorState.QUARANTINED,
    ExtensionOperatorAction.RELEASE: ExtensionOperatorState.ENABLED,
}


def state_for_action(action: ExtensionOperatorAction) -> ExtensionOperatorState:
    """The durable state an operator action yields (the decision invariant)."""
    return _ACTION_STATES[action]


@dataclass(frozen=True)
class OperatorDecision:
    """One audited operator decision over an extension's runtime admission.

    Every field is provenance: who decided, when, why, and what state the
    action yields. Decisions are append-only evidence; the newest one for an
    extension is its effective state.
    """

    decision_id: str
    at: datetime
    org_id: str
    workspace_id: str
    extension_id: str
    action: ExtensionOperatorAction
    state: ExtensionOperatorState
    actor: str
    reason: str

    def __post_init__(self) -> None:
        if self.state is not state_for_action(self.action):
            raise ValueError(
                f"action {self.action} cannot produce state {self.state}; "
                "a decision must record the state its action yields"
            )


# --------------------------------------------------------------------------
# Health evaluation (#978): derived from recorded evidence, never asserted
# --------------------------------------------------------------------------


class ExtensionHealth(StrEnum):
    """Health of one extension version, derived from recorded evidence.

    ``UNMEASURED`` is a first-class answer: with no recorded observations the
    extension is not known healthy, and the projection says so instead of
    defaulting to a success-shaped green (ADR-083026-a91e: an unmeasured
    metric is absent, not zero).
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNMEASURED = "unmeasured"


#: Health states that permit readiness. ``UNMEASURED`` is allowed because
#: readiness gates on recorded evidence *of failure*, not on proof of
#: success; the projection still surfaces ``unmeasured`` so operators can
#: tell "no evidence" from "evidence of health".
HEALTHY_STATES: frozenset[ExtensionHealth] = frozenset(
    {ExtensionHealth.HEALTHY, ExtensionHealth.UNMEASURED}
)

#: How many recent observations the health evaluation looks at. A bounded,
#: deterministic window: "healthy" means the recent recorded record is clean,
#: not that all history ever was.
HEALTH_WINDOW = 20


def evaluate_health(observations: Sequence[ExtensionObservation]) -> ExtensionHealth:
    """Classify health from the most recent recorded observations.

    ``observations`` is the recorded slice, oldest first; the newest
    :data:`HEALTH_WINDOW` entries decide. Any non-dependency failure in the
    window → ``UNHEALTHY``. Otherwise any dependency-kind failure →
    ``DEGRADED`` (transient, external — the extension itself is not
    condemned by it). Otherwise observed successes → ``HEALTHY``. No
    evidence at all → ``UNMEASURED``.
    """
    recent = observations[-HEALTH_WINDOW:]
    if not recent:
        return ExtensionHealth.UNMEASURED
    saw_dependency_failure = False
    for observation in reversed(recent):
        if observation.outcome is ObservationOutcome.SUCCESS:
            continue
        error = observation.error
        if error is not None and error.kind is ExtensionErrorKind.DEPENDENCY:
            saw_dependency_failure = True
        elif error is not None and error.kind in (
            ExtensionErrorKind.EXTENSION,
            ExtensionErrorKind.PLATFORM,
            ExtensionErrorKind.POLICY,
        ):
            return ExtensionHealth.UNHEALTHY
    return ExtensionHealth.DEGRADED if saw_dependency_failure else ExtensionHealth.HEALTHY


# --------------------------------------------------------------------------
# Dependency readiness (#978)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DependencyReadiness:
    """Whether an extension's declared dependencies can serve right now."""

    ready: bool
    #: Verbatim failure line for every dependency that is not ready.
    failures: tuple[str, ...] = ()


def dependency_readiness(
    manifest: ExtensionManifest,
    installed_versions: Mapping[str, str],
    *,
    dependency_health: Mapping[str, ExtensionHealth] | None = None,
) -> DependencyReadiness:
    """Re-derive dependency readiness from canonical evidence.

    A dependency is ready when the scope's *currently active* install
    satisfies the declared range (registry evidence) and — when the host
    supplies dependency/provider health — that dependency's own health is
    not failing. The manifest's frozen dependency list is the authority for
    *what* is required; the scope's live active set is the authority for
    *what is actually there right now*. Range grammar and fail-closed
    behavior are the install-time rules (`compatibility.py`) reused, so
    install and runtime can never disagree about what "satisfies" means.
    """
    failures: list[str] = []
    for dependency in manifest.dependencies:
        installed = installed_versions.get(dependency.extension_id)
        if installed is None:
            failures.append(
                f"missing dependency: {dependency.extension_id} "
                f"(range {dependency.range_spec}) is not active in this scope"
            )
        elif not _range_satisfied(dependency.range_spec, installed):
            failures.append(
                f"dependency conflict: {dependency.extension_id} is active at "
                f"{installed}, which does not satisfy {dependency.range_spec}"
            )
        elif dependency_health is not None:
            health = dependency_health.get(dependency.extension_id)
            if health is ExtensionHealth.UNHEALTHY or health is ExtensionHealth.DEGRADED:
                failures.append(
                    f"dependency failing: {dependency.extension_id} reports {health.value}"
                )
    return DependencyReadiness(ready=not failures, failures=tuple(failures))


# --------------------------------------------------------------------------
# Operational status projection (#978)
# --------------------------------------------------------------------------


class ExtensionOperationalState(StrEnum):
    """The projected operational state of one extension *version*.

    Vocabulary note: these names describe health/admission, not a work
    lifecycle — Run/NodeRun/Attempt (ADR-081226-a66b) remains the only
    execution lifecycle. ``SUPERSEDED`` marks a version that still carries
    historical telemetry but is no longer the scope's active install;
    ``NOT_INSTALLED`` marks a version with no activation to stand on. Both
    implement the acceptance requirement that removed versions stay
    identifiable without appearing active.
    """

    READY = "ready"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    QUARANTINED = "quarantined"
    DISABLED = "disabled"
    INCOMPATIBLE = "incompatible"
    UNAUTHORIZED = "unauthorized"
    NOT_INSTALLED = "not_installed"
    INSTALL_FAILING = "install_failing"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class ExtensionOperationalStatus:
    """The truthful operational projection of one extension version.

    Every component names its evidence source on the defining field; the two
    derived answers are ``live`` (liveness) and ``ready`` (readiness), with
    ``not_ready_reasons`` carrying the operator-facing why — empty exactly
    when ``ready`` is true.
    """

    extension_id: str
    version: str
    #: Canonical lifecycle evidence: the record exists and is ACTIVE.
    installed: bool
    #: Canonical lifecycle evidence: the record holds a standing grant.
    authorized: bool
    #: Re-derived now against the current platform API — never the frozen
    #: install-time verdict. Dependency state is the separate
    #: ``dependency_ready`` gate.
    compatible: bool
    #: Declared dependencies resolvable against the current active set and
    #: their supplied health evidence.
    dependency_ready: bool
    #: Derived from host-recorded observation evidence.
    healthy: ExtensionHealth
    #: Durable operator decision state.
    policy_state: ExtensionOperatorState
    #: Readiness: may receive traffic. False whenever any gate fails.
    ready: bool
    #: Liveness: the activated record exists in the runtime. Deliberately
    #: cheap — dependency, health, and policy gates belong to readiness.
    live: bool
    #: The single summary state for dashboards and alert routing.
    summary: ExtensionOperationalState
    #: Why this version is not ready; empty exactly when ``ready``.
    not_ready_reasons: tuple[str, ...] = field(default=())
    #: Current compatibility failures verbatim (empty when compatible).
    incompatibility_failures: tuple[str, ...] = field(default=())
    #: Current dependency failures verbatim (empty when dependency-ready).
    dependency_failures: tuple[str, ...] = field(default=())


def _lifecycle_authorization(state: ExtensionState) -> bool:
    """Whether the lifecycle state carries a standing authorization grant.

    Only AUTHORIZED (granted, not yet installed), INSTALLING, FAILED, and
    ACTIVE hold the frozen grant; the pre-decision states never had one and
    the terminal refusal states revoked their candidacy.
    """
    return state in (
        ExtensionState.AUTHORIZED,
        ExtensionState.INSTALLING,
        ExtensionState.FAILED,
        ExtensionState.ACTIVE,
    )


def _refusal_status(
    record: ExtensionInstallRecord | None,
    extension_id: str,
    version: str,
    health: ExtensionHealth,
    operator_state: ExtensionOperatorState,
) -> ExtensionOperationalStatus:
    """The projection for a version with no standing activation.

    Covers "telemetry names a version we never installed" (``record is
    None`` → NOT_INSTALLED) and "the machine refused this install"
    (terminal states → UNAUTHORIZED). Either way: never installed, never
    ready, never live — while the version string stays on the projection so
    historical telemetry remains attributable.
    """
    if record is None:
        return ExtensionOperationalStatus(
            extension_id=extension_id,
            version=version,
            installed=False,
            authorized=False,
            compatible=False,
            dependency_ready=False,
            healthy=health,
            policy_state=operator_state,
            ready=False,
            live=False,
            summary=ExtensionOperationalState.NOT_INSTALLED,
            not_ready_reasons=("no install record for this version",),
        )
    return ExtensionOperationalStatus(
        extension_id=extension_id,
        version=version,
        installed=False,
        authorized=_lifecycle_authorization(record.state),
        compatible=False,
        dependency_ready=False,
        healthy=health,
        policy_state=operator_state,
        ready=False,
        live=False,
        summary=ExtensionOperationalState.UNAUTHORIZED,
        not_ready_reasons=(f"install record is {record.state.value}",),
    )


def _failing_summary(
    *,
    authorized: bool,
    compatible: bool,
    dependency_ready: bool,
    health: ExtensionHealth,
    operator_state: ExtensionOperatorState,
) -> ExtensionOperationalState:
    """Pick the single most operator-actionable non-ready summary state.

    Precedence: operator admission first (quarantine/disable are deliberate
    holds, not symptoms), then the structural gates (unauthorized,
    incompatible), then the transient ones (dependency, health). A transient
    dependency failure therefore lands on ``DEGRADED`` — distinguishable,
    per the acceptance criteria, from a quarantine or a disable.
    """
    if operator_state is ExtensionOperatorState.QUARANTINED:
        return ExtensionOperationalState.QUARANTINED
    if operator_state is ExtensionOperatorState.DISABLED:
        return ExtensionOperationalState.DISABLED
    if not authorized:
        return ExtensionOperationalState.UNAUTHORIZED
    if not compatible:
        return ExtensionOperationalState.INCOMPATIBLE
    if not dependency_ready:
        return ExtensionOperationalState.DEGRADED
    if health is ExtensionHealth.UNHEALTHY:
        return ExtensionOperationalState.UNHEALTHY
    if health is ExtensionHealth.DEGRADED:
        return ExtensionOperationalState.DEGRADED
    # Unreachable through project_operational_status (every not-ready reason
    # maps to a gate above); the explicit fallback keeps the function total.
    return ExtensionOperationalState.INSTALL_FAILING


def _superseded_status(
    record: ExtensionInstallRecord,
    active_record: ExtensionInstallRecord,
    health: ExtensionHealth,
    operator_state: ExtensionOperatorState,
) -> ExtensionOperationalStatus:
    """The projection for a version whose active pointer another version took.

    The version keeps its telemetry and its identity, and never reports
    active or ready again — the acceptance requirement that superseded
    versions stay identifiable without appearing active.
    """
    return ExtensionOperationalStatus(
        extension_id=record.extension_id,
        version=record.version,
        installed=False,
        authorized=_lifecycle_authorization(record.state),
        compatible=False,
        dependency_ready=False,
        healthy=health,
        policy_state=operator_state,
        ready=False,
        live=False,
        summary=ExtensionOperationalState.SUPERSEDED,
        not_ready_reasons=(
            f"superseded by {active_record.version} (install {active_record.install_id})",
        ),
    )


def _gate_reasons(
    *,
    record: ExtensionInstallRecord,
    installed: bool,
    authorized: bool,
    compatibility: CompatibilityReport,
    readiness_report: DependencyReadiness,
    health: ExtensionHealth,
    operator_state: ExtensionOperatorState,
) -> list[str]:
    """Every reason this version may not report ready, in gate order."""
    not_ready: list[str] = []
    if not installed:
        if record.state is ExtensionState.FAILED:
            not_ready.append(f"activation failed: {record.failure_reason}")
        else:
            not_ready.append(f"install record is {record.state.value}, not active")
    if not authorized:
        not_ready.append("no standing authorization grant for this record")
    for failure in compatibility.failures:
        not_ready.append(f"incompatible: {failure}")
    for failure in readiness_report.failures:
        not_ready.append(f"dependency not ready: {failure}")
    if health not in HEALTHY_STATES:
        not_ready.append(f"health is {health.value} from recorded evidence")
    if operator_state is ExtensionOperatorState.DISABLED:
        not_ready.append("disabled by operator decision")
    elif operator_state is ExtensionOperatorState.QUARANTINED:
        not_ready.append("quarantined by operator decision")
    return not_ready


def _subject(
    record: ExtensionInstallRecord | None, active_record: ExtensionInstallRecord | None
) -> tuple[str, str]:
    """The (extension_id, version) a projection is about."""
    extension_id = (
        record.extension_id
        if record is not None
        else (active_record.extension_id if active_record else "")
    )
    version = record.version if record is not None else ""
    return extension_id, version


def _is_superseded(
    record: ExtensionInstallRecord, active_record: ExtensionInstallRecord | None
) -> bool:
    """Whether another version of this extension owns the active pointer."""
    return (
        record.state is ExtensionState.ACTIVE
        and active_record is not None
        and active_record.install_id != record.install_id
    )


def _uninstalled_summary(record: ExtensionInstallRecord) -> ExtensionOperationalState:
    """The truthful summary for a record that cannot serve: recoverable
    FAILED activation vs everything else that simply is not active."""
    if record.state is ExtensionState.FAILED:
        return ExtensionOperationalState.INSTALL_FAILING
    return ExtensionOperationalState.NOT_INSTALLED


def project_operational_status(
    *,
    record: ExtensionInstallRecord | None,
    active_record: ExtensionInstallRecord | None,
    installed_versions: Mapping[str, str],
    platform_api_version: str,
    health: ExtensionHealth = ExtensionHealth.UNMEASURED,
    dependency_health: Mapping[str, ExtensionHealth] | None = None,
    operator_state: ExtensionOperatorState = ExtensionOperatorState.ENABLED,
) -> ExtensionOperationalStatus:
    """Project one version's operational status from canonical evidence.

    ``record`` is the install record *of the version being projected*
    (``None`` when telemetry names a version the registry never installed).
    ``active_record`` is the scope's current active install for the same
    extension id, which decides whether this version is superseded.
    ``installed_versions`` maps extension ids to their currently ACTIVE
    versions in the scope. All other arguments are the live evidence inputs
    documented on :class:`ExtensionOperationalStatus`.
    """
    extension_id, version = _subject(record, active_record)

    if record is None or record.state in TERMINAL_STATES:
        return _refusal_status(record, extension_id, version, health, operator_state)

    if _is_superseded(record, active_record):
        assert active_record is not None  # narrowing for the record builder
        return _superseded_status(record, active_record, health, operator_state)

    # Platform compatibility is re-derived against the *current* platform:
    # a platform upgrade can make an installed extension structurally
    # incompatible, and the projection must say so rather than replay the
    # install-day verdict (acceptance: installed-but-incompatible cannot
    # report ready). Dependency state is its own, transient, gate below.
    compatibility = evaluate_platform_compatibility(
        record.manifest,
        platform_api_version,
    )
    readiness_report = dependency_readiness(
        record.manifest,
        installed_versions,
        dependency_health=dependency_health,
    )
    authorized = _lifecycle_authorization(record.state)
    installed = record.state is ExtensionState.ACTIVE
    not_ready = _gate_reasons(
        record=record,
        installed=installed,
        authorized=authorized,
        compatibility=compatibility,
        readiness_report=readiness_report,
        health=health,
        operator_state=operator_state,
    )
    ready = not not_ready

    if not installed:
        summary = _uninstalled_summary(record)
    elif ready:
        summary = ExtensionOperationalState.READY
    else:
        summary = _failing_summary(
            authorized=authorized,
            compatible=compatibility.compatible,
            dependency_ready=readiness_report.ready,
            health=health,
            operator_state=operator_state,
        )

    return ExtensionOperationalStatus(
        extension_id=extension_id,
        version=version,
        installed=installed,
        authorized=authorized,
        compatible=compatibility.compatible,
        dependency_ready=readiness_report.ready,
        healthy=health,
        policy_state=operator_state,
        ready=ready,
        live=installed,
        summary=summary,
        not_ready_reasons=tuple(not_ready),
        incompatibility_failures=compatibility.failures,
        dependency_failures=readiness_report.failures,
    )


# --------------------------------------------------------------------------
# Usage telemetry: digests, ranking, SLO inputs (#978)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtensionUsageDigest:
    """Aggregated per-(scope, extension, version) usage facts.

    ``error_rate``, ``latency_avg_ms``, ``latency_max_ms`` and
    ``cost_units_total`` are ``None`` when the window holds no data for them
    — absent, never zero, so an unmeasured extension cannot rank as a free
    or fast one (ADR-083026-a91e). ``active`` reports whether this exact
    version is the scope's current active install; historical rows keep
    their identity and aggregate with ``active=False``.
    """

    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    invocations: int
    failures: int
    error_rate: float | None
    latency_samples: int
    latency_avg_ms: float | None
    latency_max_ms: float | None
    cost_units_total: float | None
    active: bool


class RankingMetric(StrEnum):
    """What operators rank extension contributors by (#978)."""

    USAGE = "usage"
    COST = "cost"
    FAILURES = "failures"
    ERROR_RATE = "error_rate"
    LATENCY = "latency"


def rank_digests(
    digests: Iterable[ExtensionUsageDigest], by: RankingMetric, *, limit: int = 10
) -> list[ExtensionUsageDigest]:
    """Rank digests descending by one metric; unmeasured sorts last.

    Absence ordering is the truthful one: an extension with no measured cost
    or no latency samples must not be read as zero. Ties break by extension
    id then version, so the ranking is deterministic for identical inputs.
    """

    def value(digest: ExtensionUsageDigest) -> float | None:
        match by:
            case RankingMetric.USAGE:
                return float(digest.invocations)
            case RankingMetric.COST:
                return digest.cost_units_total
            case RankingMetric.FAILURES:
                return float(digest.failures)
            case RankingMetric.ERROR_RATE:
                return digest.error_rate
            case RankingMetric.LATENCY:
                return digest.latency_max_ms

    measured = [digest for digest in digests if value(digest) is not None]
    unmeasured = [digest for digest in digests if value(digest) is None]
    measured.sort(key=lambda digest: (-(value(digest) or 0.0), digest.extension_id, digest.version))
    unmeasured.sort(key=lambda digest: (digest.extension_id, digest.version))
    return (measured + unmeasured)[:limit]


@dataclass(frozen=True)
class SloPosition:
    """SLO/alert inputs for one extension version (ADR-038 shape).

    ``error_budget_remaining`` is the fraction (0..1) of the window's
    allowed failures still unspent; ``None`` when the window holds no
    observations. ``budget_exhausted`` is ``False`` when unknown — absence
    of data must not page anyone. Consumers map the remaining fraction onto
    the ADR-038 budget metric for their deployment.
    """

    slo_target: float
    window_observations: int
    observed_success_rate: float | None
    error_budget_remaining: float | None
    budget_exhausted: bool


def slo_position(*, invocations: int, failures: int, slo_target: float = 0.99) -> SloPosition:
    """Compute the error-budget position over one aggregation window."""
    if not 0.0 < slo_target < 1.0:
        raise ValueError("slo_target is a success fraction strictly between 0 and 1")
    if invocations <= 0:
        return SloPosition(
            slo_target=slo_target,
            window_observations=0,
            observed_success_rate=None,
            error_budget_remaining=None,
            budget_exhausted=False,
        )
    allowed = (1.0 - slo_target) * invocations
    if allowed <= 0.0:
        # A target with no arithmetic budget (approaching 1.0): the observed
        # rate is the only truthful statement, and any failure exhausts it.
        return SloPosition(
            slo_target=slo_target,
            window_observations=invocations,
            observed_success_rate=(invocations - failures) / invocations,
            error_budget_remaining=None,
            budget_exhausted=failures > 0,
        )
    # The allowed budget is a float derived from a fraction, so the exact
    # boundary (failures == allowed) can land a hair on either side; the
    # tolerance makes the contract deterministic at the boundary.
    exhausted = (allowed - failures) <= 1e-9
    return SloPosition(
        slo_target=slo_target,
        window_observations=invocations,
        observed_success_rate=(invocations - failures) / invocations,
        error_budget_remaining=max(0.0, (allowed - failures) / allowed),
        budget_exhausted=exhausted,
    )


def digest_observations(
    *,
    scope: ExtensionScope,
    extension_id: str,
    version: str,
    observations: Sequence[ExtensionObservation],
    active: bool,
) -> ExtensionUsageDigest:
    """Aggregate one version's observations into its usage digest."""
    invocations = len(observations)
    failures = sum(
        1 for observation in observations if observation.outcome is ObservationOutcome.FAILURE
    )
    latencies = [observation.latency_ms for observation in observations]
    costs = [
        observation.cost_units for observation in observations if observation.cost_units is not None
    ]
    return ExtensionUsageDigest(
        org_id=scope.org_id,
        workspace_id=scope.workspace_id,
        extension_id=extension_id,
        version=version,
        invocations=invocations,
        failures=failures,
        error_rate=(failures / invocations) if invocations else None,
        latency_samples=len(latencies),
        latency_avg_ms=(sum(latencies) / len(latencies)) if latencies else None,
        latency_max_ms=max(latencies) if latencies else None,
        cost_units_total=sum(costs) if costs else None,
        active=active,
    )


# --------------------------------------------------------------------------
# Durable health evidence store (#978)
# --------------------------------------------------------------------------


@runtime_checkable
class ExtensionHealthStore(Protocol):
    """Persistence seam for observations, errors, and operator decisions.

    The in-memory reference keeps process-lifetime history; the SQLite twin
    (:mod:`maistro.extensions.sqlite_health_store`) is the restart-surviving
    implementation the acceptance criteria require. Evidence is append-only:
    operator decisions are appended, never overwritten, and the newest
    decision for an extension is its effective state.
    """

    async def append_observation(self, observation: ExtensionObservation) -> None:
        """Record one host-observed invocation outcome."""
        ...

    async def append_error(self, error: ExtensionErrorRecord) -> None:
        """Record one classified failure with its provenance."""
        ...

    async def observations(
        self,
        scope: ExtensionScope,
        *,
        extension_id: str | None = None,
        version: str | None = None,
        limit: int | None = None,
    ) -> tuple[ExtensionObservation, ...]:
        """Recorded observations, oldest first, optionally filtered."""
        ...

    async def errors(
        self,
        scope: ExtensionScope,
        *,
        extension_id: str | None = None,
        kind: ExtensionErrorKind | None = None,
        limit: int | None = None,
    ) -> tuple[ExtensionErrorRecord, ...]:
        """Recorded failures, oldest first, optionally filtered."""
        ...

    async def append_decision(self, decision: OperatorDecision) -> None:
        """Append one operator decision; the newest decision is the state."""
        ...

    async def decisions(
        self, scope: ExtensionScope, extension_id: str | None = None
    ) -> tuple[OperatorDecision, ...]:
        """All operator decisions in scope, oldest first."""
        ...


def latest_decision(
    decisions: Sequence[OperatorDecision], extension_id: str
) -> OperatorDecision | None:
    """The newest decision for one extension, or ``None`` when unmanaged."""
    chosen: OperatorDecision | None = None
    for decision in decisions:
        if decision.extension_id == extension_id:
            chosen = decision
    return chosen


def operator_state_for(
    decisions: Sequence[OperatorDecision], extension_id: str
) -> ExtensionOperatorState:
    """The effective operator state; no decision at all means enabled."""
    decision = latest_decision(decisions, extension_id)
    return decision.state if decision is not None else ExtensionOperatorState.ENABLED


class InMemoryExtensionHealthStore:
    """Process-lifetime reference implementation of
    :class:`ExtensionHealthStore`.

    Ordering is deterministic: evidence is kept in append order and every
    read returns it oldest first, so identical operation sequences produce
    identical reads on both store twins (the conformance suite holds them to
    that). Restart survival is the SQLite twin's contract, not this one's.
    """

    def __init__(self) -> None:
        self._observations: list[ExtensionObservation] = []
        self._errors: list[ExtensionErrorRecord] = []
        self._decisions: list[OperatorDecision] = []

    async def append_observation(self, observation: ExtensionObservation) -> None:
        """Record one observation, filing its error row with it.

        The observation-and-its-error pair lands atomically: a failed
        observation always yields a queryable error row in both twins, so
        the provenance view can never miss a failure the digest counts.
        """
        self._observations.append(observation)
        if observation.error is not None:
            self._errors.append(observation.error)

    async def append_error(self, error: ExtensionErrorRecord) -> None:
        self._errors.append(error)

    async def observations(
        self,
        scope: ExtensionScope,
        *,
        extension_id: str | None = None,
        version: str | None = None,
        limit: int | None = None,
    ) -> tuple[ExtensionObservation, ...]:
        rows = [
            observation
            for observation in self._observations
            if observation.org_id == scope.org_id
            and observation.workspace_id == scope.workspace_id
            and (extension_id is None or observation.extension_id == extension_id)
            and (version is None or observation.version == version)
        ]
        return tuple(rows[-limit:] if limit is not None else rows)

    async def errors(
        self,
        scope: ExtensionScope,
        *,
        extension_id: str | None = None,
        kind: ExtensionErrorKind | None = None,
        limit: int | None = None,
    ) -> tuple[ExtensionErrorRecord, ...]:
        rows = [
            error
            for error in self._errors
            if error.org_id == scope.org_id
            and error.workspace_id == scope.workspace_id
            and (extension_id is None or error.extension_id == extension_id)
            and (kind is None or error.kind is kind)
        ]
        return tuple(rows[-limit:] if limit is not None else rows)

    async def append_decision(self, decision: OperatorDecision) -> None:
        self._decisions.append(decision)

    async def decisions(
        self, scope: ExtensionScope, extension_id: str | None = None
    ) -> tuple[OperatorDecision, ...]:
        rows = [
            decision
            for decision in self._decisions
            if decision.org_id == scope.org_id
            and decision.workspace_id == scope.workspace_id
            and (extension_id is None or decision.extension_id == extension_id)
        ]
        # Order by (extension_id, append position) so the read matches the
        # SQLite twin's ORDER BY extension_id, decision_seq exactly.
        order = {id(decision): position for position, decision in enumerate(self._decisions)}
        return tuple(
            sorted(rows, key=lambda decision: (decision.extension_id, order[id(decision)]))
        )


@dataclass(frozen=True)
class TelemetryExport:
    """The exportable telemetry payload for one scope (#978).

    Typed rather than a free-form dict so the HTTP export view and the
    projections it carries can never drift apart.
    """

    statuses: list[ExtensionOperationalStatus]
    usage: list[ExtensionUsageDigest]
    errors: list[ExtensionErrorRecord]
    operator_decisions: list[OperatorDecision]


class ExtensionHealthService:
    """Read/projection facade over the lifecycle store and the health store.

    The service is the only place views are assembled: it resolves the
    scope's canonical lifecycle evidence from the *same* install store the
    :class:`~maistro.extensions.service.ExtensionInstallService` owns, the
    recorded health evidence, and the durable operator decisions, and
    projects them. Recording observations is deliberately host-only — there
    is no route by which an extension could file its own health — so every
    projected state is canonical evidence, not self-report.
    """

    def __init__(
        self,
        install_store: ExtensionStore,
        health_store: ExtensionHealthStore,
        *,
        platform_api_version: str = "1.0.0",
    ) -> None:
        self._install_store = install_store
        self._health_store = health_store
        self._platform_api_version = platform_api_version

    # -- recording (host seam) -----------------------------------------------

    async def record_observation(self, observation: ExtensionObservation) -> None:
        """Record one host-observed outcome; a failure files its error row.

        This is the seam the invocation host calls after each extension
        invocation. Extensions have no access to it: health evidence enters
        the system only through the host that made the call.
        """
        await self._health_store.append_observation(observation)

    async def apply_decision(self, decision: OperatorDecision) -> OperatorDecision:
        """Append one operator decision durably; returns what was recorded."""
        await self._health_store.append_decision(decision)
        return decision

    # -- projections -----------------------------------------------------------

    async def status(
        self,
        scope: ExtensionScope,
        extension_id: str,
        *,
        version: str | None = None,
    ) -> ExtensionOperationalStatus | None:
        """Project one extension's status; the active version by default.

        With no active install, the newest record for the extension is
        projected instead, so a refused candidate surfaces UNAUTHORIZED
        rather than disappearing from the operator view. ``version`` selects
        a specific historical version. Returns ``None`` when the scope holds
        no record for the request — an unknown extension has no status,
        rather than a fabricated one.
        """
        active = await self._install_store.active_record(scope, extension_id)
        if version is not None:
            target = await self._install_store.latest_record(scope, extension_id, version)
        elif active is not None:
            target = active
        else:
            records = await self._install_store.records_for(scope, extension_id)
            target = (
                max(records, key=lambda record: record.created_at or _EPOCH_FLOOR)
                if records
                else None
            )
        if target is None:
            return None
        return await self._project(scope, extension_id, target, active)

    async def statuses(self, scope: ExtensionScope) -> tuple[ExtensionOperationalStatus, ...]:
        """Project every extension recorded in the scope, by extension id.

        One projection per extension: the currently active record, or — for
        an extension with no active install — its newest record, so refused
        (terminal) candidates still surface as UNAUTHORIZED instead of
        disappearing from the operator view.
        """
        records = await self._install_store.records_in_scope(scope)
        by_extension: dict[str, list[ExtensionInstallRecord]] = {}
        for record in records:
            by_extension.setdefault(record.extension_id, []).append(record)
        projected: list[ExtensionOperationalStatus] = []
        for extension_id in sorted(by_extension):
            active = await self._install_store.active_record(scope, extension_id)
            target = active
            if target is None:
                target = max(
                    by_extension[extension_id],
                    key=lambda record: record.created_at or _EPOCH_FLOOR,
                )
            status = await self._project(scope, extension_id, target, active)
            if status is not None:
                projected.append(status)
        return tuple(projected)

    async def version_status(
        self, scope: ExtensionScope, extension_id: str, version: str
    ) -> ExtensionOperationalStatus | None:
        """Project one historical version's status (superseded/removed aware).

        The active pointer decides the verdict: a previously active version
        that has since been upgraded projects SUPERSEDED — identifiable,
        never active.
        """
        active = await self._install_store.active_record(scope, extension_id)
        record = await self._install_store.latest_record(scope, extension_id, version)
        if record is None:
            return None
        return await self._project(scope, extension_id, record, active)

    async def _project(
        self,
        scope: ExtensionScope,
        extension_id: str,
        record: ExtensionInstallRecord,
        active: ExtensionInstallRecord | None,
    ) -> ExtensionOperationalStatus:
        """Assemble the evidence inputs and project them for one record."""
        installed_versions = await self._install_store.installed_versions(scope)
        observations = await self._health_store.observations(scope, extension_id=extension_id)
        health = evaluate_health(observations)
        decisions = await self._health_store.decisions(scope)
        return project_operational_status(
            record=record,
            active_record=active,
            installed_versions=installed_versions,
            platform_api_version=self._platform_api_version,
            health=health,
            operator_state=operator_state_for(decisions, extension_id),
        )

    # -- telemetry views ---------------------------------------------------------

    async def usage_digests(self, scope: ExtensionScope) -> tuple[ExtensionUsageDigest, ...]:
        """One digest per (extension, version) that has recorded telemetry.

        The active flag comes from the canonical lifecycle store, so a
        version with traffic but no active install still ranks —
        identifiable, with ``active=False``.
        """
        observations = await self._health_store.observations(scope)
        grouped: dict[tuple[str, str], list[ExtensionObservation]] = {}
        for observation in observations:
            grouped.setdefault((observation.extension_id, observation.version), []).append(
                observation
            )
        digests: list[ExtensionUsageDigest] = []
        for (extension_id, version), rows in grouped.items():
            active = await self._install_store.active_record(scope, extension_id)
            digests.append(
                digest_observations(
                    scope=scope,
                    extension_id=extension_id,
                    version=version,
                    observations=rows,
                    active=active is not None and active.version == version,
                )
            )
        return tuple(sorted(digests, key=lambda digest: (digest.extension_id, digest.version)))

    async def rank(
        self, scope: ExtensionScope, by: RankingMetric, *, limit: int = 10
    ) -> list[ExtensionUsageDigest]:
        """Top contributors by usage, cost, failures, error rate, or latency."""
        return rank_digests(await self.usage_digests(scope), by, limit=limit)

    async def slo(
        self,
        scope: ExtensionScope,
        extension_id: str,
        *,
        slo_target: float = 0.99,
    ) -> SloPosition | None:
        """Error-budget inputs for an extension's active version.

        With no active install the position covers the extension's recorded
        telemetry across versions (historical evidence, still attributable).
        ``None`` when the extension has no recorded observations at all:
        there is no SLO position without data, and fabricating a perfect one
        would be success-shaped telemetry of exactly the kind this issue
        removes.
        """
        active = await self._install_store.active_record(scope, extension_id)
        version = active.version if active is not None else None
        observations = await self._health_store.observations(
            scope, extension_id=extension_id, version=version
        )
        if not observations:
            return None
        failures = sum(
            1 for observation in observations if observation.outcome is ObservationOutcome.FAILURE
        )
        return slo_position(invocations=len(observations), failures=failures, slo_target=slo_target)

    async def recent_errors(
        self,
        scope: ExtensionScope,
        extension_id: str,
        *,
        kind: ExtensionErrorKind | None = None,
        limit: int = 50,
    ) -> tuple[ExtensionErrorRecord, ...]:
        """The extension's recorded failures, newest first (provenance kept)."""
        recorded = await self._health_store.errors(scope, extension_id=extension_id, kind=kind)
        return tuple(reversed(recorded[-limit:]))

    async def export_telemetry(self, scope: ExtensionScope) -> TelemetryExport:
        """Exportable telemetry for one scope: statuses, digests, evidence.

        The operator views and the export share one code path, so what the
        API claims is exactly what the export carries.
        """
        return TelemetryExport(
            statuses=list(await self.statuses(scope)),
            usage=list(await self.usage_digests(scope)),
            errors=list(await self._health_store.errors(scope)),
            operator_decisions=list(await self._health_store.decisions(scope)),
        )
