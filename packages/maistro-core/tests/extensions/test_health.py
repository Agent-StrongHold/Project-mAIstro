"""Truthful extension operational status, error taxonomy, and telemetry
(M9-I3, #978).

Each test names the acceptance criterion it pins. The projections under test
derive status from canonical evidence only — install records, fresh
compatibility evaluation, dependency readiness, host-recorded observations,
and durable operator decisions — so every test drives the real install
lifecycle and records evidence through the host seam, never by asserting a
status into existence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.extensions.health import (
    HEALTH_WINDOW,
    DependencyReadiness,
    ExtensionErrorKind,
    ExtensionErrorRecord,
    ExtensionHealth,
    ExtensionHealthService,
    ExtensionObservation,
    ExtensionOperationalState,
    ExtensionOperatorAction,
    ExtensionOperatorState,
    ExtensionUsageDigest,
    InMemoryExtensionHealthStore,
    ObservationOutcome,
    OperatorDecision,
    RankingMetric,
    SloPosition,
    dependency_readiness,
    digest_observations,
    evaluate_health,
    latest_decision,
    operator_state_for,
    project_operational_status,
    rank_digests,
    slo_position,
    state_for_action,
)
from maistro.extensions.service import (
    ExtensionCodeLoader,
    ExtensionInstallService,
    LoadedExtension,
)
from maistro.extensions.store import InMemoryExtensionStore
from maistro.extensions.trust import TrustPolicy
from maistro.extensions.types import (
    ExtensionInstallRecord,
    ExtensionPackage,
    ExtensionScope,
    TrustClaim,
)

ORG = "org-1"
WORKSPACE = "ws-1"
SCOPE = ExtensionScope(org_id=ORG, workspace_id=WORKSPACE)
PAYLOAD = b"health-test-payload"
PUBLISHER = "acme"
TRUST_POLICY = TrustPolicy(trusted_publishers=frozenset({PUBLISHER}))


class _ActivatingLoader(ExtensionCodeLoader):
    """The host loader seam: loads whatever was authorized."""

    async def load(self, record: ExtensionInstallRecord, payload: bytes) -> LoadedExtension:
        return LoadedExtension(extension_id=record.extension_id, version=record.version)


def _manifest_json(
    *,
    extension_id: str = "acme.chart",
    version: str = "1.4.0",
    api_version: str = "1.0.0",
    dependencies: tuple[Mapping[str, str], ...] = (),
    payload: bytes = PAYLOAD,
) -> str:
    document: dict[str, Any] = {
        "manifest_version": 1,
        "id": extension_id,
        "name": extension_id,
        "version": version,
        "publisher": PUBLISHER,
        "api_version": api_version,
        "permissions": ["network.http"],
        "entry_points": [{"name": "main", "module": "mod", "attribute": "activate"}],
        "artifact": {"sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)},
    }
    if dependencies:
        document["dependencies"] = [
            {"id": dependency["extension_id"], "range": dependency["range_spec"]}
            for dependency in dependencies
        ]
    return json.dumps(document)


async def _install_active(
    store: InMemoryExtensionStore,
    *,
    extension_id: str = "acme.chart",
    version: str = "1.4.0",
    api_version: str = "1.0.0",
    dependencies: tuple[Mapping[str, str], ...] = (),
) -> ExtensionInstallRecord:
    """Drive one candidate through inspect → authorize → install → ACTIVE."""
    service = ExtensionInstallService(store, loader=_ActivatingLoader(), trust_policy=TRUST_POLICY)
    record = await service.inspect(
        actor="operator",
        scope=SCOPE,
        package=ExtensionPackage(
            manifest_bytes=_manifest_json(
                extension_id=extension_id,
                version=version,
                api_version=api_version,
                dependencies=dependencies,
            ).encode(),
            payload=PAYLOAD,
        ),
        trust_evidence=TrustClaim(
            publisher_id=PUBLISHER,
            signature_present=True,
            signer_key_id="key-1",
            package_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        ),
    )
    record = await service.authorize(
        record.install_id, actor="operator", scope=SCOPE, approve=True, reason="needed"
    )
    return await service.install(record.install_id, actor="operator", scope=SCOPE, payload=PAYLOAD)


def _observation(
    observation_id: str,
    *,
    outcome: ObservationOutcome = ObservationOutcome.SUCCESS,
    version: str = "1.4.0",
    extension_id: str = "acme.chart",
    latency_ms: float = 10.0,
    at: datetime | None = None,
    error: ExtensionErrorRecord | None = None,
    cost_units: float | None = None,
) -> ExtensionObservation:
    return ExtensionObservation(
        observation_id=observation_id,
        at=at or datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC),
        org_id=ORG,
        workspace_id=WORKSPACE,
        extension_id=extension_id,
        version=version,
        latency_ms=latency_ms,
        outcome=outcome,
        cost_units=cost_units,
        error=error,
    )


def _error(
    error_id: str,
    *,
    kind: ExtensionErrorKind = ExtensionErrorKind.DEPENDENCY,
    version: str = "1.4.0",
    extension_id: str = "acme.chart",
    dependency: str | None = "acme.provider",
    dependency_version: str | None = "2.0.0",
) -> ExtensionErrorRecord:
    return ExtensionErrorRecord(
        error_id=error_id,
        at=datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC),
        org_id=ORG,
        workspace_id=WORKSPACE,
        extension_id=extension_id,
        version=version,
        kind=kind,
        code="test_failure",
        message="recorded for the taxonomy suite",
        dependency=dependency,
        dependency_version=dependency_version if kind is ExtensionErrorKind.DEPENDENCY else None,
    )


def _quarantine(extension_id: str = "acme.chart") -> OperatorDecision:
    return OperatorDecision(
        decision_id="decision-1",
        at=datetime(2026, 10, 1, 13, 0, 0, tzinfo=UTC),
        org_id=ORG,
        workspace_id=WORKSPACE,
        extension_id=extension_id,
        action=ExtensionOperatorAction.QUARANTINE,
        state=ExtensionOperatorState.QUARANTINED,
        actor="security",
        reason="suspected misbehavior",
    )


# --------------------------------------------------------------------------
# Acceptance: installed-but-incompatible/unauthorized/unhealthy cannot be ready
# --------------------------------------------------------------------------


async def test_active_extension_with_healthy_evidence_is_ready() -> None:
    """The baseline the refusal paths are measured against: an ACTIVE record
    with clean recorded evidence projects ready and live."""
    store = InMemoryExtensionStore()
    await _install_active(store)
    health = InMemoryExtensionHealthStore()
    await health.append_observation(_observation("obs-1"))
    service = ExtensionHealthService(store, health)

    status = await service.status(SCOPE, "acme.chart")

    assert status is not None
    assert status.ready is True
    assert status.live is True
    assert status.summary is ExtensionOperationalState.READY
    assert status.healthy is ExtensionHealth.HEALTHY
    assert status.not_ready_reasons == ()


async def test_installed_but_incompatible_extension_cannot_report_ready() -> None:
    """Acceptance: incompatibility is re-derived *now*, not replayed from the
    install-day verdict. A platform API bump after activation must strip
    readiness from an installed extension."""
    store = InMemoryExtensionStore()
    await _install_active(store, api_version="1.0.0")
    health = InMemoryExtensionHealthStore()
    await health.append_observation(_observation("obs-1"))
    service = ExtensionHealthService(store, health, platform_api_version="2.0.0")

    status = await service.status(SCOPE, "acme.chart")

    assert status is not None
    assert status.ready is False
    assert status.compatible is False
    assert status.summary is ExtensionOperationalState.INCOMPATIBLE
    assert any("incompatible" in reason for reason in status.not_ready_reasons)
    assert status.incompatibility_failures


async def test_unauthorized_extension_cannot_report_ready() -> None:
    """Acceptance: a denied install never reports ready — terminal refusal
    states project UNAUTHORIZED with no liveness at all."""
    store = InMemoryExtensionStore()
    service = ExtensionInstallService(store, loader=_ActivatingLoader(), trust_policy=TRUST_POLICY)
    record = await service.inspect(
        actor="operator",
        scope=SCOPE,
        package=ExtensionPackage(manifest_bytes=_manifest_json().encode(), payload=PAYLOAD),
        trust_evidence=TrustClaim(
            publisher_id=PUBLISHER,
            signature_present=True,
            signer_key_id="key-1",
            package_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        ),
    )
    await service.authorize(
        record.install_id, actor="operator", scope=SCOPE, approve=False, reason="not approved"
    )
    health = InMemoryExtensionHealthStore()
    service = ExtensionHealthService(store, health)

    status = await service.status(SCOPE, "acme.chart")

    assert status is not None
    assert status.ready is False
    assert status.live is False
    assert status.summary is ExtensionOperationalState.UNAUTHORIZED


async def test_unhealthy_extension_cannot_report_ready() -> None:
    """Acceptance: an extension's own fault (non-dependency failure) recorded
    by the host strips readiness and reports UNHEALTHY, not DEGRADED."""
    store = InMemoryExtensionStore()
    await _install_active(store)
    health = InMemoryExtensionHealthStore()
    await health.append_observation(
        _observation(
            "obs-fault",
            outcome=ObservationOutcome.FAILURE,
            error=_error("err-fault", kind=ExtensionErrorKind.EXTENSION, dependency=None),
        )
    )
    service = ExtensionHealthService(store, health)

    status = await service.status(SCOPE, "acme.chart")

    assert status is not None
    assert status.ready is False
    assert status.healthy is ExtensionHealth.UNHEALTHY
    assert status.summary is ExtensionOperationalState.UNHEALTHY


async def test_unmeasured_extension_is_ready_but_reports_unmeasured() -> None:
    """Readiness gates on recorded evidence *of failure*, never on proof of
    success — but "no evidence" must stay visible as UNMEASURED, not be read
    as healthy (an unmeasured metric is absent, not zero)."""
    store = InMemoryExtensionStore()
    await _install_active(store)
    service = ExtensionHealthService(store, InMemoryExtensionHealthStore())

    status = await service.status(SCOPE, "acme.chart")

    assert status is not None
    assert status.ready is True
    assert status.healthy is ExtensionHealth.UNMEASURED
    assert status.summary is ExtensionOperationalState.READY


# --------------------------------------------------------------------------
# Acceptance: transient dependency failure is distinguishable from quarantine
# --------------------------------------------------------------------------


async def test_transient_dependency_failure_is_degraded_live_not_quarantined() -> None:
    """Acceptance: a dependency-kind failure projects DEGRADED — not ready,
    still live, and structurally distinct from the operator holds."""
    store = InMemoryExtensionStore()
    await _install_active(store)
    health = InMemoryExtensionHealthStore()
    await health.append_observation(
        _observation("obs-dep", outcome=ObservationOutcome.FAILURE, error=_error("err-dep"))
    )
    service = ExtensionHealthService(store, health)

    status = await service.status(SCOPE, "acme.chart")

    assert status is not None
    assert status.ready is False
    assert status.live is True
    assert status.healthy is ExtensionHealth.DEGRADED
    assert status.summary is ExtensionOperationalState.DEGRADED
    assert status.policy_state is ExtensionOperatorState.ENABLED


async def test_quarantine_and_disable_are_distinct_operator_holds() -> None:
    """Quarantine and disable are deliberate admission holds with their own
    summaries — never collapsed into "unhealthy" or into each other — and
    they hold even when every health signal is clean."""
    store = InMemoryExtensionStore()
    await _install_active(store)
    health = InMemoryExtensionHealthStore()
    await health.append_observation(_observation("obs-1"))
    service = ExtensionHealthService(store, health)

    quarantined = await service.status(SCOPE, "acme.chart")
    assert quarantined is not None
    await service.apply_decision(_quarantine())
    quarantined = await service.status(SCOPE, "acme.chart")
    assert quarantined is not None
    assert quarantined.ready is False
    assert quarantined.summary is ExtensionOperationalState.QUARANTINED
    assert quarantined.policy_state is ExtensionOperatorState.QUARANTINED

    await service.apply_decision(
        OperatorDecision(
            decision_id="decision-2",
            at=datetime(2026, 10, 1, 14, 0, 0, tzinfo=UTC),
            org_id=ORG,
            workspace_id=WORKSPACE,
            extension_id="acme.chart",
            action=ExtensionOperatorAction.DISABLE,
            state=ExtensionOperatorState.DISABLED,
            actor="operator",
            reason="maintenance window",
        )
    )
    disabled = await service.status(SCOPE, "acme.chart")
    assert disabled is not None
    assert disabled.ready is False
    assert disabled.summary is ExtensionOperationalState.DISABLED
    assert disabled.policy_state is ExtensionOperatorState.DISABLED


# --------------------------------------------------------------------------
# Acceptance: status derives from canonical evidence, not self-report
# --------------------------------------------------------------------------


async def test_projection_has_no_extension_supplied_health_input() -> None:
    """Acceptance: the projection's evidence inputs are the lifecycle record,
    fresh compatibility, dependency readiness, host-recorded observations,
    and durable operator decisions. There is no parameter — and no service
    method — by which an extension could assert its own health."""
    import inspect

    from maistro.extensions import health as health_module

    service_params = inspect.signature(ExtensionHealthService.record_observation).parameters
    # The only recording seam takes a host-constructed observation; no
    # method accepts a health assertion from the extension side.
    for name, member in inspect.getmembers(ExtensionHealthService, inspect.isfunction):
        if name.startswith("_") or name == "record_observation":
            continue
        assert "health_claim" not in inspect.signature(member).parameters, name
    assert "observation" in service_params

    projection_params = inspect.signature(health_module.project_operational_status).parameters
    assert "self_reported" not in projection_params
    assert "claimed_health" not in projection_params


async def test_observations_enter_only_through_the_host_seam() -> None:
    """The service records observations; the store keeps them attributable;
    an observation's failure always carries its classified taxonomy record
    (the invariant the projection's provenance guarantees rest on)."""
    health = InMemoryExtensionHealthStore()
    observation = _observation(
        "obs-dep", outcome=ObservationOutcome.FAILURE, error=_error("err-dep")
    )
    await health.append_observation(observation)

    stored = await health.observations(SCOPE, extension_id="acme.chart")
    assert stored == (observation,)
    errors = await health.errors(SCOPE, extension_id="acme.chart")
    assert len(errors) == 1
    assert errors[0].dependency == "acme.provider"
    assert errors[0].dependency_version == "2.0.0"

    with pytest.raises(ValueError, match="must carry its classified"):
        ExtensionObservation(
            observation_id="bad",
            at=datetime(2026, 10, 1, tzinfo=UTC),
            org_id=ORG,
            workspace_id=WORKSPACE,
            extension_id="acme.chart",
            version="1.4.0",
            latency_ms=1.0,
            outcome=ObservationOutcome.FAILURE,
            error=None,
        )
    with pytest.raises(ValueError, match="cannot carry an error"):
        _observation("bad-success", outcome=ObservationOutcome.SUCCESS, error=_error("err-x"))


async def test_failed_observation_rejects_mismatched_error_provenance() -> None:
    """An embedded error must belong to the exact org/workspace/extension/
    version the observation is about — otherwise the failure is counted
    against one identity while the cause is filed under another, leaving the
    affected extension's detail without its cause and another scope with a
    phantom error."""
    kwargs = {
        "observation_id": "obs-mismatch",
        "at": datetime(2026, 10, 1, tzinfo=UTC),
        "org_id": ORG,
        "workspace_id": WORKSPACE,
        "extension_id": "acme.chart",
        "version": "1.4.0",
        "latency_ms": 1.0,
        "outcome": ObservationOutcome.FAILURE,
    }
    mismatched: list[ExtensionErrorRecord] = [
        _error("err-other-workspace", extension_id="acme.chart"),
        _error("err-other-extension", extension_id="acme.notes"),
        _error("err-other-version", version="2.0.0"),
    ]
    for error in mismatched:
        error = replace(
            error,
            workspace_id="ws-other" if error is mismatched[0] else WORKSPACE,
            org_id="org-other" if error is mismatched[1] else ORG,
        )
        with pytest.raises(ValueError, match="does not match the observation's identity"):
            ExtensionObservation(error=error, **kwargs)

    # The exact identity match is accepted.
    ExtensionObservation(error=_error("err-match"), **kwargs)


def test_observation_metrics_must_be_finite_and_non_negative() -> None:
    """Rankings and aggregates read latency and cost as *measured*: a
    negative or non-finite value would fabricate rankings (NaN and infinity
    would also break the JSON telemetry response), so construction refuses
    them. Unmeasured cost stays None — absent, not zero."""
    for latency_ms in (-1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="latency_ms"):
            _observation("obs-bad", latency_ms=latency_ms)
    for cost_units in (-0.5, float("nan"), float("-inf")):
        with pytest.raises(ValueError, match="cost_units"):
            _observation("obs-bad", cost_units=cost_units)
    assert _observation("obs-unmeasured").cost_units is None
    zero = _observation("obs-zero", latency_ms=0.0, cost_units=0.0)
    assert zero.latency_ms == 0.0 and zero.cost_units == 0.0


# --------------------------------------------------------------------------
# Acceptance: errors preserve extension/version/dependency provenance
# --------------------------------------------------------------------------


async def test_error_records_preserve_full_provenance() -> None:
    """Acceptance: errors keep the exact extension id, the exact version that
    served, and — for dependency failures — the failing dependency and its
    version, even after the scope's active version has moved on."""
    store = InMemoryExtensionStore()
    await _install_active(store, version="1.4.0")
    await _install_active(store, version="1.5.0")
    health = InMemoryExtensionHealthStore()
    await health.append_observation(
        _observation(
            "obs-old",
            version="1.4.0",
            outcome=ObservationOutcome.FAILURE,
            error=_error("err-old", version="1.4.0"),
        )
    )
    service = ExtensionHealthService(store, health)

    errors = await service.recent_errors(SCOPE, "acme.chart")

    assert len(errors) == 1
    provenance = errors[0]
    assert provenance.extension_id == "acme.chart"
    assert provenance.version == "1.4.0"
    assert provenance.kind is ExtensionErrorKind.DEPENDENCY
    assert provenance.dependency == "acme.provider"
    assert provenance.dependency_version == "2.0.0"


def test_dependency_error_requires_dependency_provenance() -> None:
    """A dependency-kind failure without its dependency is not recordable:
    provenance is the record's purpose, so absence fails at construction."""
    with pytest.raises(ValueError, match="must name the dependency"):
        ExtensionErrorRecord(
            error_id="e",
            at=datetime(2026, 10, 1, tzinfo=UTC),
            org_id=ORG,
            workspace_id=WORKSPACE,
            extension_id="acme.chart",
            version="1.4.0",
            kind=ExtensionErrorKind.DEPENDENCY,
            code="x",
            message="m",
            dependency=None,
        )


def test_non_dependency_error_rejects_dependency_provenance() -> None:
    """The inverse invariant: an extension fault claiming a failing
    dependency would misroute the operator's attention."""
    with pytest.raises(ValueError, match="only dependency-kind errors"):
        _error("e", kind=ExtensionErrorKind.EXTENSION)


# --------------------------------------------------------------------------
# Acceptance: health survives restart; windowed evaluation
# --------------------------------------------------------------------------


def test_health_evaluation_dependency_only_failures_degrade() -> None:
    """Dependency failures in the window degrade health without condemning
    the extension — the evaluation the transient/transient distinction
    relies on."""
    observations = (
        _observation("obs-1"),
        _observation("obs-2", outcome=ObservationOutcome.FAILURE, error=_error("err-1")),
        _observation("obs-3"),
    )
    assert evaluate_health(observations) is ExtensionHealth.DEGRADED


def test_health_evaluation_non_dependency_failure_is_unhealthy() -> None:
    """One non-dependency failure anywhere in the window is UNHEALTHY, even
    with successes after it."""
    observations = (
        _observation("obs-1"),
        _observation(
            "obs-2",
            outcome=ObservationOutcome.FAILURE,
            error=_error("err-1", kind=ExtensionErrorKind.PLATFORM, dependency=None),
        ),
        _observation("obs-3"),
    )
    assert evaluate_health(observations) is ExtensionHealth.UNHEALTHY


def test_health_evaluation_window_is_bounded() -> None:
    """Failures older than the window do not condemn the extension: the
    window's recent record is the verdict, not all history ever."""
    failure = _observation(
        "obs-failure",
        outcome=ObservationOutcome.FAILURE,
        error=_error("err-1", kind=ExtensionErrorKind.EXTENSION, dependency=None),
        at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    clean = tuple(
        _observation(f"obs-clean-{index}", at=datetime(2026, 9, 1, index, tzinfo=UTC))
        for index in range(HEALTH_WINDOW)
    )
    assert evaluate_health((failure, *clean)) is ExtensionHealth.HEALTHY
    assert evaluate_health(()) is ExtensionHealth.UNMEASURED


async def test_projection_reads_only_the_health_window() -> None:
    """Status projections never stream the store's whole retained history:
    every health-evaluating read requests the newest HEALTH_WINDOW rows, so
    latency stays flat as recorded evidence grows without bound."""

    class _RecordingHealthStore(InMemoryExtensionHealthStore):
        def __init__(self) -> None:
            super().__init__()
            self.observation_limits: list[int | None] = []

        async def observations(
            self,
            scope: ExtensionScope,
            *,
            extension_id: str | None = None,
            version: str | None = None,
            limit: int | None = None,
        ) -> tuple[ExtensionObservation, ...]:
            self.observation_limits.append(limit)
            return await super().observations(
                scope, extension_id=extension_id, version=version, limit=limit
            )

    store = InMemoryExtensionStore()
    await _install_active(store)
    health = _RecordingHealthStore()
    for index in range(HEALTH_WINDOW * 3):
        await health.append_observation(_observation(f"obs-{index}"))
    service = ExtensionHealthService(store, health)

    status = await service.status(SCOPE, "acme.chart")

    assert status is not None
    assert status.healthy is ExtensionHealth.HEALTHY
    assert health.observation_limits
    assert all(limit == HEALTH_WINDOW for limit in health.observation_limits)


# --------------------------------------------------------------------------
# Acceptance: removed versions identifiable in telemetry, never active
# --------------------------------------------------------------------------


async def test_superseded_version_is_identifiable_and_never_active() -> None:
    """Acceptance: after an upgrade, the old version's status is SUPERSEDED —
    its telemetry stays attributable (active=False on the digest), and it
    reports neither installed nor ready."""
    store = InMemoryExtensionStore()
    await _install_active(store, version="1.4.0")
    await _install_active(store, version="1.5.0")
    health = InMemoryExtensionHealthStore()
    await health.append_observation(_observation("obs-old", version="1.4.0"))
    await health.append_observation(_observation("obs-new", version="1.5.0"))
    service = ExtensionHealthService(store, health)

    old = await service.version_status(SCOPE, "acme.chart", "1.4.0")
    assert old is not None
    assert old.summary is ExtensionOperationalState.SUPERSEDED
    assert old.ready is False
    assert old.live is False
    assert old.installed is False
    assert any("superseded by 1.5.0" in reason for reason in old.not_ready_reasons)

    digests = {digest.version: digest for digest in await service.usage_digests(SCOPE)}
    assert digests["1.4.0"].active is False
    assert digests["1.5.0"].active is True
    assert digests["1.4.0"].invocations == 1


async def test_telemetry_for_a_version_with_no_install_record_is_not_installed() -> None:
    """Acceptance: telemetry naming a version the registry never installed
    stays attributable but projects NOT_INSTALLED — never ready, never
    active. The service (not just the pure projector) must return that
    verdict for the detail, overview, and export views; only an identity
    with no recorded evidence at all answers None."""
    health = InMemoryExtensionHealthStore()
    await health.append_observation(_observation("obs-ghost"))
    store = InMemoryExtensionStore()
    service = ExtensionHealthService(store, health)

    status = project_operational_status(
        record=None,
        active_record=None,
        installed_versions={},
        platform_api_version="1.0.0",
        health=ExtensionHealth.HEALTHY,
        identity=("acme.chart", "1.4.0"),
    )
    assert status.summary is ExtensionOperationalState.NOT_INSTALLED
    assert status.ready is False

    # Detail views: the telemetry-backed identity surfaces NOT_INSTALLED
    # with its requested identity kept verbatim.
    for projection in (
        await service.status(SCOPE, "acme.chart"),
        await service.status(SCOPE, "acme.chart", version="1.4.0"),
        await service.version_status(SCOPE, "acme.chart", "1.4.0"),
    ):
        assert projection is not None
        assert projection.summary is ExtensionOperationalState.NOT_INSTALLED
        assert (projection.extension_id, projection.version) == ("acme.chart", "1.4.0")
        assert projection.installed is False
        assert projection.ready is False
        assert projection.live is False

    # Overview and export enumerate the telemetry-only identity too.
    overview = await service.statuses(SCOPE)
    assert [(p.extension_id, p.version) for p in overview] == [("acme.chart", "1.4.0")]
    assert overview[0].summary is ExtensionOperationalState.NOT_INSTALLED
    exported = await service.export_telemetry(SCOPE)
    assert [p.summary for p in exported.statuses] == [ExtensionOperationalState.NOT_INSTALLED]

    # An extension with neither records nor telemetry still has no status.
    assert await service.status(SCOPE, "acme.never") is None
    assert await service.version_status(SCOPE, "acme.never", "1.4.0") is None
    assert await service.statuses(SCOPE) == overview  # no fabricated rows


async def test_pre_install_records_project_not_installed_without_fabricating_readiness() -> None:
    """Records that hold a grant but have not activated (AUTHORIZED), and
    records still awaiting a decision (AWAITING_AUTHORIZATION), project
    NOT_INSTALLED — with the awaiting case explicitly unauthorized. Neither
    borrows readiness from the gate checks that have not run yet."""
    store = InMemoryExtensionStore()
    service = ExtensionInstallService(store, loader=_ActivatingLoader(), trust_policy=TRUST_POLICY)
    health = InMemoryExtensionHealthStore()
    view = ExtensionHealthService(store, health)

    awaiting = await service.inspect(
        actor="operator",
        scope=SCOPE,
        package=ExtensionPackage(manifest_bytes=_manifest_json().encode(), payload=PAYLOAD),
        trust_evidence=TrustClaim(
            publisher_id=PUBLISHER,
            signature_present=True,
            signer_key_id="key-1",
            package_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        ),
    )
    status = await view.status(SCOPE, "acme.chart")
    assert status is not None
    assert status.summary is ExtensionOperationalState.NOT_INSTALLED
    assert status.authorized is False
    assert status.ready is False
    assert any("awaiting_authorization" in reason for reason in status.not_ready_reasons)

    authorized = await service.authorize(
        awaiting.install_id, actor="operator", scope=SCOPE, approve=True, reason="granted"
    )
    status = await view.status(SCOPE, "acme.chart")
    assert status is not None
    assert status.summary is ExtensionOperationalState.NOT_INSTALLED
    assert status.authorized is True
    assert status.ready is False
    assert any("not active" in reason for reason in status.not_ready_reasons)
    assert authorized.state.value == "authorized"


async def test_failed_installation_reports_install_failing_and_stays_recoverable() -> None:
    """A recoverable FAILED activation reports INSTALL_FAILING — the truthful
    "install stands but cannot serve" state between NOT_INSTALLED and READY."""
    store = InMemoryExtensionStore()
    service = ExtensionInstallService(store, loader=_ActivatingLoader(), trust_policy=TRUST_POLICY)
    record = await service.inspect(
        actor="operator",
        scope=SCOPE,
        package=ExtensionPackage(manifest_bytes=_manifest_json().encode(), payload=PAYLOAD),
        trust_evidence=TrustClaim(
            publisher_id=PUBLISHER,
            signature_present=True,
            signer_key_id="key-1",
            package_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        ),
    )
    record = await service.authorize(
        record.install_id, actor="operator", scope=SCOPE, approve=True, reason="needed"
    )

    class _BrokenLoader(ExtensionCodeLoader):
        async def load(self, record: ExtensionInstallRecord, payload: bytes) -> LoadedExtension:
            raise RuntimeError("activation substrate missing")

    broken = ExtensionInstallService(store, loader=_BrokenLoader(), trust_policy=TRUST_POLICY)
    with pytest.raises(Exception, match="recorded FAILED"):
        await broken.install(record.install_id, actor="operator", scope=SCOPE, payload=PAYLOAD)

    view = ExtensionHealthService(store, InMemoryExtensionHealthStore())
    status = await view.status(SCOPE, "acme.chart")
    assert status is not None
    assert status.summary is ExtensionOperationalState.INSTALL_FAILING
    assert status.ready is False
    assert any("activation failed" in reason for reason in status.not_ready_reasons)


async def test_liveness_and_readiness_are_distinct_axes() -> None:
    """Liveness tracks activation only; readiness is gated by dependency,
    health, and admission evidence. A dependency upgraded past the declared
    range leaves the extension live but not ready — the ADR-038 distinction,
    per extension, derived from the scope's *current* active set."""
    store = InMemoryExtensionStore()
    await _install_active(store, extension_id="acme.provider", version="1.0.0")
    await _install_active(
        store,
        dependencies=({"extension_id": "acme.provider", "range_spec": "^1.0.0"},),
    )
    health = InMemoryExtensionHealthStore()
    await health.append_observation(_observation("obs-1"))
    service = ExtensionHealthService(store, health)
    ready = await service.status(SCOPE, "acme.chart")
    assert ready is not None
    assert ready.ready is True

    # The dependency's active pointer moves to an out-of-range version.
    await _install_active(store, extension_id="acme.provider", version="2.0.0")

    broken = await service.status(SCOPE, "acme.chart")

    assert broken is not None
    assert broken.live is True
    assert broken.ready is False
    assert broken.dependency_ready is False
    assert broken.summary is ExtensionOperationalState.DEGRADED
    assert any("does not satisfy ^1.0.0" in reason for reason in broken.not_ready_reasons)


# --------------------------------------------------------------------------
# Dependency readiness
# --------------------------------------------------------------------------


def test_dependency_readiness_reports_missing_conflict_and_failing() -> None:
    """Each dependency failure mode produces its own verbatim reason line:
    missing, range conflict, and externally-failing."""
    from maistro.extensions.manifest import inspect_manifest

    manifest = inspect_manifest(
        _manifest_json(
            dependencies=(
                {"extension_id": "acme.missing", "range_spec": "*"},
                {"extension_id": "acme.conflict", "range_spec": "^2.0.0"},
                {"extension_id": "acme.failing", "range_spec": "1.0.0"},
                {"extension_id": "acme.fine", "range_spec": "^1.0.0"},
            )
        ).encode()
    )
    readiness = dependency_readiness(
        manifest,
        {
            "acme.conflict": "1.9.0",
            "acme.failing": "1.0.0",
            "acme.fine": "1.2.0",
        },
        dependency_health={"acme.failing": ExtensionHealth.UNHEALTHY},
    )
    assert readiness.ready is False
    assert len(readiness.failures) == 3
    assert any(
        "acme.missing" in failure and "not active" in failure for failure in readiness.failures
    )
    assert any(
        "acme.conflict" in failure and "does not satisfy" in failure
        for failure in readiness.failures
    )
    assert any(
        "acme.failing" in failure and "unhealthy" in failure for failure in readiness.failures
    )


def test_dependency_readiness_range_grammar_matches_install_rules() -> None:
    """Runtime readiness reuses the install-time range grammar: caret bound
    to the same major, exact pin, and star — so install and runtime can
    never disagree about what satisfies a dependency."""
    from maistro.extensions.manifest import inspect_manifest

    def readiness_for(range_spec: str, installed: str) -> DependencyReadiness:
        manifest = inspect_manifest(
            _manifest_json(
                dependencies=({"extension_id": "acme.dep", "range_spec": range_spec},)
            ).encode()
        )
        return dependency_readiness(manifest, {"acme.dep": installed})

    assert readiness_for("^1.2.0", "1.9.0").ready is True
    assert readiness_for("^1.2.0", "2.0.0").ready is False
    assert readiness_for("1.2.3", "1.2.3").ready is True
    assert readiness_for("1.2.3", "1.2.4").ready is False
    assert readiness_for("*", "9.9.9").ready is True


async def test_service_gates_readiness_on_dependency_health() -> None:
    """Acceptance: the service derives each declared dependency's health from
    that dependency's own host-recorded evidence and passes it into the
    projection — a failing provider marks an otherwise-clean dependent not
    ready, even with a satisfying version range active."""
    store = InMemoryExtensionStore()
    await _install_active(store, extension_id="acme.provider", version="2.0.0")
    await _install_active(
        store,
        extension_id="acme.chart",
        dependencies=({"extension_id": "acme.provider", "range_spec": "^2.0.0"},),
    )
    health = InMemoryExtensionHealthStore()
    await health.append_observation(
        _observation(
            "obs-provider",
            outcome=ObservationOutcome.FAILURE,
            extension_id="acme.provider",
            version="2.0.0",
            error=_error(
                "err-provider",
                kind=ExtensionErrorKind.EXTENSION,
                extension_id="acme.provider",
                version="2.0.0",
                dependency=None,
            ),
        )
    )
    service = ExtensionHealthService(store, health)

    status = await service.status(SCOPE, "acme.chart")

    assert status is not None
    assert status.ready is False
    assert status.dependency_ready is False
    assert status.summary is ExtensionOperationalState.DEGRADED
    assert any(
        "acme.provider" in failure and "unhealthy" in failure
        for failure in status.dependency_failures
    )


async def test_service_dependency_health_reads_each_dependency_own_version() -> None:
    """The dependency's health is evaluated at the version actually active —
    a failure recorded against an older provider version does not condemn the
    upgraded one."""
    store = InMemoryExtensionStore()
    await _install_active(store, extension_id="acme.provider", version="2.0.0")
    await _install_active(
        store,
        extension_id="acme.chart",
        dependencies=({"extension_id": "acme.provider", "range_spec": "^2.0.0"},),
    )
    health = InMemoryExtensionHealthStore()
    await health.append_observation(
        _observation(
            "obs-old-provider",
            outcome=ObservationOutcome.FAILURE,
            extension_id="acme.provider",
            version="1.0.0",
            error=_error(
                "err-old-provider",
                kind=ExtensionErrorKind.EXTENSION,
                extension_id="acme.provider",
                version="1.0.0",
                dependency=None,
            ),
        )
    )
    service = ExtensionHealthService(store, health)

    status = await service.status(SCOPE, "acme.chart")

    assert status is not None
    assert status.dependency_ready is True
    assert status.ready is True


# --------------------------------------------------------------------------
# Operator decisions
# --------------------------------------------------------------------------


def test_operator_decision_records_the_state_its_action_yields() -> None:
    """A decision claiming an action/state pair the action cannot produce is
    refused at construction — the audit trail cannot drift from the truth."""
    with pytest.raises(ValueError, match="cannot produce state"):
        OperatorDecision(
            decision_id="d",
            at=datetime(2026, 10, 1, tzinfo=UTC),
            org_id=ORG,
            workspace_id=WORKSPACE,
            extension_id="acme.chart",
            action=ExtensionOperatorAction.QUARANTINE,
            state=ExtensionOperatorState.DISABLED,
            actor="operator",
            reason="mismatched",
        )
    assert state_for_action(ExtensionOperatorAction.RELEASE) is ExtensionOperatorState.ENABLED
    assert state_for_action(ExtensionOperatorAction.QUARANTINE) is (
        ExtensionOperatorState.QUARANTINED
    )


def test_operator_state_newest_decision_wins_and_default_is_enabled() -> None:
    """The newest decision is the state; no decision at all is enabled."""
    first = _quarantine()
    second = OperatorDecision(
        decision_id="decision-2",
        at=first.at + timedelta(hours=1),
        org_id=ORG,
        workspace_id=WORKSPACE,
        extension_id="acme.chart",
        action=ExtensionOperatorAction.RELEASE,
        state=ExtensionOperatorState.ENABLED,
        actor="security",
        reason="cleared",
    )
    decisions = (first, second)
    assert latest_decision(decisions, "acme.chart") is second
    assert operator_state_for(decisions, "acme.chart") is ExtensionOperatorState.ENABLED
    assert operator_state_for((first,), "acme.chart") is ExtensionOperatorState.QUARANTINED
    assert operator_state_for((), "acme.chart") is ExtensionOperatorState.ENABLED
    assert latest_decision(decisions, "other.extension") is None


# --------------------------------------------------------------------------
# Ranking, digests, and SLO inputs
# --------------------------------------------------------------------------


def _digest(
    extension_id: str,
    version: str,
    *,
    invocations: int = 0,
    failures: int = 0,
    latency_avg_ms: float | None = None,
    latency_max_ms: float | None = None,
    cost_units_total: float | None = None,
    active: bool = True,
) -> ExtensionUsageDigest:
    return ExtensionUsageDigest(
        org_id=ORG,
        workspace_id=WORKSPACE,
        extension_id=extension_id,
        version=version,
        invocations=invocations,
        failures=failures,
        error_rate=(failures / invocations) if invocations else None,
        latency_samples=invocations,
        latency_avg_ms=latency_avg_ms,
        latency_max_ms=latency_max_ms,
        cost_units_total=cost_units_total,
        active=active,
    )


def test_rank_by_each_metric() -> None:
    """Acceptance: operators can rank by usage, cost, failures, error rate,
    and latency — each ordering computed from measured data."""
    big = _digest(
        "acme.big",
        "1.0.0",
        invocations=100,
        failures=10,
        cost_units_total=9.0,
        latency_max_ms=400.0,
    )
    small = _digest(
        "acme.small",
        "1.0.0",
        invocations=10,
        failures=1,
        cost_units_total=1.0,
        latency_max_ms=100.0,
    )
    digests = (small, big)

    assert [d.extension_id for d in rank_digests(digests, RankingMetric.USAGE)] == [
        "acme.big",
        "acme.small",
    ]
    assert [d.extension_id for d in rank_digests(digests, RankingMetric.COST)] == [
        "acme.big",
        "acme.small",
    ]
    assert [d.extension_id for d in rank_digests(digests, RankingMetric.FAILURES)] == [
        "acme.big",
        "acme.small",
    ]
    assert [d.extension_id for d in rank_digests(digests, RankingMetric.ERROR_RATE)] == [
        "acme.big",
        "acme.small",
    ]
    assert [d.extension_id for d in rank_digests(digests, RankingMetric.LATENCY)] == [
        "acme.big",
        "acme.small",
    ]


def test_rank_unmeasured_sorts_last_never_as_zero() -> None:
    """Acceptance (with ADR-083026-a91e): an extension with unmeasured cost
    must not be read as free — absence sorts last, identically for latency."""
    measured = _digest("acme.measured", "1.0.0", cost_units_total=5.0, latency_max_ms=50.0)
    unmeasured = _digest("acme.unmeasured", "1.0.0")
    for metric in (RankingMetric.COST, RankingMetric.LATENCY):
        ranked = rank_digests((unmeasured, measured), metric)
        assert [d.extension_id for d in ranked] == ["acme.measured", "acme.unmeasured"]


def test_rank_is_deterministic_on_ties_and_honors_limit() -> None:
    """Identical inputs rank identically: ties break by extension id then
    version, and limit truncates after the ordering."""
    first = _digest("acme.a", "1.0.0", invocations=10)
    second = _digest("acme.a", "2.0.0", invocations=10)
    third = _digest("acme.b", "1.0.0", invocations=10)
    ranked = rank_digests((third, second, first), RankingMetric.USAGE, limit=2)
    assert [(d.extension_id, d.version) for d in ranked] == [
        ("acme.a", "1.0.0"),
        ("acme.a", "2.0.0"),
    ]


def test_slo_position_error_budget_math() -> None:
    """SLO inputs: remaining budget is the unspent fraction of the window's
    allowed failures; exhaustion is exact at the boundary."""
    position = slo_position(invocations=100, failures=3, slo_target=0.99)
    assert position.window_observations == 100
    assert position.observed_success_rate == pytest.approx(0.97)
    # allowed = 1% of 100 = 1 failure; 3 observed -> exhausted, zero left.
    assert position.error_budget_remaining == 0.0
    assert position.budget_exhausted is True

    healthy = slo_position(invocations=100, failures=0, slo_target=0.99)
    assert healthy.error_budget_remaining == pytest.approx(1.0)
    assert healthy.budget_exhausted is False

    boundary = slo_position(invocations=200, failures=2, slo_target=0.99)
    assert boundary.error_budget_remaining == pytest.approx(0.0)
    assert boundary.budget_exhausted is True


def test_slo_position_with_no_data_is_absent_and_never_alarms() -> None:
    """No observations: no SLO position can be claimed, and absence must not
    page anyone — budget_exhausted is False when unknown."""
    position = slo_position(invocations=0, failures=0)
    assert isinstance(position, SloPosition)
    assert position.window_observations == 0
    assert position.observed_success_rate is None
    assert position.error_budget_remaining is None
    assert position.budget_exhausted is False
    with pytest.raises(ValueError, match="strictly between"):
        slo_position(invocations=1, failures=0, slo_target=1.0)


def test_digest_absent_metrics_are_none_not_zero() -> None:
    """A version whose invocations carried no cost has no cost total —
    ``None``, not 0.0 — so cost ranking cannot be gamed by silence."""
    observation = _observation("obs-1", latency_ms=8.0)
    digest = digest_observations(
        scope=SCOPE,
        extension_id="acme.chart",
        version="1.4.0",
        observations=(observation,),
        active=True,
    )
    assert digest.invocations == 1
    assert digest.failures == 0
    assert digest.error_rate == pytest.approx(0.0)
    assert digest.latency_avg_ms == pytest.approx(8.0)
    assert digest.cost_units_total is None


# --------------------------------------------------------------------------
# Service views
# --------------------------------------------------------------------------


async def test_service_status_for_unknown_extension_is_none() -> None:
    """An extension the scope never recorded has no status — none is
    fabricated for it."""
    store = InMemoryExtensionStore()
    service = ExtensionHealthService(store, InMemoryExtensionHealthStore())
    assert await service.status(SCOPE, "acme.never") is None
    assert await service.statuses(SCOPE) == ()
    assert await service.usage_digests(SCOPE) == ()
    assert await service.slo(SCOPE, "acme.never") is None


async def test_service_statuses_surfaces_refused_candidates() -> None:
    """The scope view includes extensions whose only records were refused:
    the operator sees UNAUTHORIZED rather than a silent absence."""
    store = InMemoryExtensionStore()
    service = ExtensionInstallService(store, loader=_ActivatingLoader(), trust_policy=TRUST_POLICY)
    record = await service.inspect(
        actor="operator",
        scope=SCOPE,
        package=ExtensionPackage(manifest_bytes=_manifest_json().encode(), payload=PAYLOAD),
        trust_evidence=TrustClaim(
            publisher_id=PUBLISHER,
            signature_present=True,
            signer_key_id="key-1",
            package_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        ),
    )
    await service.authorize(
        record.install_id, actor="operator", scope=SCOPE, approve=False, reason="no"
    )
    view = ExtensionHealthService(store, InMemoryExtensionHealthStore())

    statuses = await view.statuses(SCOPE)

    assert len(statuses) == 1
    assert statuses[0].summary is ExtensionOperationalState.UNAUTHORIZED


async def test_export_telemetry_carries_the_same_objects_the_views_serve() -> None:
    """The export shares one code path with the operator views: the same
    statuses, digests, errors, and decisions, no divergence."""
    store = InMemoryExtensionStore()
    await _install_active(store)
    health = InMemoryExtensionHealthStore()
    await health.append_observation(
        _observation("obs-1", outcome=ObservationOutcome.FAILURE, error=_error("err-1"))
    )
    service = ExtensionHealthService(store, health)
    await service.apply_decision(_quarantine())

    exported = await service.export_telemetry(SCOPE)

    assert list(exported.statuses) == list(await service.statuses(SCOPE))
    assert list(exported.usage) == list(await service.usage_digests(SCOPE))
    assert list(exported.errors) == list(
        await service.recent_errors(SCOPE, "acme.chart", limit=100)
    )
    assert list(exported.operator_decisions) == [_quarantine()]


async def test_slo_view_is_none_without_recorded_evidence() -> None:
    """An active extension with no traffic has no SLO position: fabricating a
    perfect one would be exactly the success-shaped telemetry this issue
    removes."""
    store = InMemoryExtensionStore()
    await _install_active(store)
    service = ExtensionHealthService(store, InMemoryExtensionHealthStore())
    assert await service.slo(SCOPE, "acme.chart") is None
