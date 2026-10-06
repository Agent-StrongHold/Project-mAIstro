"""Governed extension install lifecycle over HTTP (#953, M9-B2).

These routes are the operator surface of the inspect → authorize → install
state machine; they execute nothing themselves. Every route is authenticated
— reads included, because an install record's granted permissions and its
audit trail are exactly what a credentialless caller must not enumerate.
Every write attributes the authenticated principal as the actor, every
decision requires a reason, and the permissions shown back are read from the
install record's immutable manifest snapshot — never re-derived from a
request body.

Authorization mapping: a Workspace-scoped install requires canonical
Workspace ADMINISTER membership for every phase (inspection creates durable
records and requests authority; deciding and installing exercise it).
Org-only scopes (no workspace) are authenticated-principal-only until the
B1/Stronghold tenancy substrate provides an org authority to check against —
that limitation is deliberate and stated, not silent.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from maistro.extensions import (
    ArtifactMismatch,
    ExtensionErrorRecord,
    ExtensionHealthService,
    ExtensionInstallRecord,
    ExtensionInstallService,
    ExtensionLifecycleError,
    ExtensionOperationalStatus,
    ExtensionOperatorAction,
    ExtensionPackage,
    ExtensionScope,
    ExtensionTransition,
    ExtensionUsageDigest,
    InspectionConflict,
    InvalidTransition,
    ManifestRejected,
    OperatorDecision,
    RankingMetric,
    SloPosition,
    UnknownInstall,
    state_for_action,
)
from maistro.extensions.types import TrustClaim
from maistro_server.api.auth import RequireAuth
from maistro_server.api.workspace_access import (
    get_workspace_store,
    require_workspace_owner,
    user_id,
)

router = APIRouter(prefix="/extensions", tags=["extensions"])


def get_extension_service(request: Request) -> ExtensionInstallService:
    """Return the install-lifecycle service wired by the process Container."""
    container = getattr(request.app.state, "container", None)
    if container is None or not hasattr(container, "ensure_extension_install_service"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No extension install service is configured",
        )
    return cast(ExtensionInstallService, container.ensure_extension_install_service())


def _actor(auth: RequireAuth) -> str:
    """The authenticated principal is the recorded actor for every transition."""
    return user_id(auth)


async def _require_scope_authority(scope: ExtensionScope, auth: RequireAuth) -> None:
    """ADMINISTER membership is the operator authority for Workspace scopes.

    The Workspace store resolves lazily, so org-only scopes do not require a
    Workspace backend to be configured.
    """
    if not scope.workspace_id:
        return
    await require_workspace_owner(get_workspace_store(), scope.workspace_id, _actor(auth))


def _decode_payload(encoded: str) -> bytes:
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="payload_b64 is not valid base64",
        ) from exc


class TrustEvidenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publisher_id: str = Field(min_length=1)
    signature_present: bool = False
    signer_key_id: str | None = None
    package_sha256: str = ""


class ScopeBody(BaseModel):
    """org/workspace scope, shared by every install-lifecycle request."""

    model_config = ConfigDict(extra="forbid")

    org_id: str = Field(min_length=1)
    workspace_id: str = ""


class InspectBody(ScopeBody):
    model_config = ConfigDict(extra="forbid")

    manifest_text: str = Field(min_length=1)
    payload_b64: str = Field(min_length=1)
    trust: TrustEvidenceBody


class AuthorizeBody(ScopeBody):
    model_config = ConfigDict(extra="forbid")

    approve: bool
    reason: str = Field(min_length=1)


class InstallBody(ScopeBody):
    model_config = ConfigDict(extra="forbid")

    payload_b64: str = Field(min_length=1)


class ManifestView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: int
    extension_id: str
    name: str
    version: str
    publisher: str
    api_version: str
    permissions: tuple[str, ...]
    entry_points: tuple[dict[str, str], ...]
    dependencies: tuple[dict[str, str], ...]
    artifact_sha256: str
    artifact_size: int
    source_sha256: str


class InstallRecordView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    install_id: str
    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    state: str
    requested_permissions: tuple[str, ...]
    granted_permissions: tuple[str, ...]
    authority_delta: tuple[str, ...]
    artifact_sha256: str | None
    failure_reason: str | None
    requested_by: str
    authorized_by: str | None
    installed_by: str | None
    install_attempts: int
    created_at: str | None
    updated_at: str | None
    expires_at: str | None
    manifest: ManifestView


class TransitionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int
    at: str
    install_id: str
    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    actor: str
    from_state: str
    to_state: str
    reason: str


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def _record_view(
    record: ExtensionInstallRecord, requested_permissions: tuple[str, ...] | None = None
) -> InstallRecordView:
    manifest = record.manifest
    return InstallRecordView(
        install_id=record.install_id,
        org_id=record.org_id,
        workspace_id=record.workspace_id,
        extension_id=record.extension_id,
        version=record.version,
        state=str(record.state),
        requested_permissions=(
            record.requested_permissions if requested_permissions is None else requested_permissions
        ),
        granted_permissions=record.granted_permissions,
        authority_delta=record.authority_delta,
        artifact_sha256=record.artifact_sha256,
        failure_reason=record.failure_reason,
        requested_by=record.requested_by,
        authorized_by=record.authorized_by,
        installed_by=record.installed_by,
        install_attempts=record.install_attempts,
        created_at=_iso(record.created_at),
        updated_at=_iso(record.updated_at),
        expires_at=_iso(record.expires_at),
        manifest=ManifestView(
            manifest_version=manifest.manifest_version,
            extension_id=manifest.extension_id,
            name=manifest.name,
            version=manifest.version,
            publisher=manifest.publisher,
            api_version=manifest.api_version,
            permissions=manifest.permissions,
            entry_points=[
                {"name": point.name, "module": point.module, "attribute": point.attribute}
                for point in manifest.entry_points
            ],
            dependencies=[
                {"extension_id": dep.extension_id, "range_spec": dep.range_spec}
                for dep in manifest.dependencies
            ],
            artifact_sha256=manifest.artifact_sha256,
            artifact_size=manifest.artifact_size,
            source_sha256=manifest.source_sha256,
        ),
    )


def _transition_view(transition: ExtensionTransition) -> TransitionView:
    return TransitionView(
        seq=transition.seq,
        at=transition.at.isoformat(),
        install_id=transition.install_id,
        org_id=transition.org_id,
        workspace_id=transition.workspace_id,
        extension_id=transition.extension_id,
        version=transition.version,
        actor=transition.actor,
        from_state=str(transition.from_state),
        to_state=str(transition.to_state),
        reason=transition.reason,
    )


def _http_error(exc: Exception) -> HTTPException:
    """Map lifecycle errors to statuses that do not leak other scopes."""
    if isinstance(exc, UnknownInstall):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (InspectionConflict, InvalidTransition, ArtifactMismatch)):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, ManifestRejected):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail=f"{exc}; the install record carries the truthful state and reason",
    )


@router.post("/inspections", response_model=InstallRecordView, status_code=201)
async def inspect_extension(
    body: InspectBody,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
) -> InstallRecordView:
    """Inspect a candidate extension and park it for explicit authorization.

    The response is a durable install record. A ``rejected`` state with its
    failure reason is a normal 201: the inspection happened, the machine
    recorded why the candidate cannot proceed. No extension code is imported
    or executed by this route.
    """
    scope = ExtensionScope(org_id=body.org_id, workspace_id=body.workspace_id)
    await _require_scope_authority(scope, auth)
    try:
        record = await service.inspect(
            actor=_actor(auth),
            scope=scope,
            package=ExtensionPackage(
                manifest_bytes=body.manifest_text.encode("utf-8"),
                payload=_decode_payload(body.payload_b64),
            ),
            trust_evidence=TrustClaim(
                publisher_id=body.trust.publisher_id,
                signature_present=body.trust.signature_present,
                signer_key_id=body.trust.signer_key_id,
                package_sha256=body.trust.package_sha256,
            ),
        )
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    return _record_view(record)


@router.post(
    "/installations/{install_id}/authorization",
    response_model=InstallRecordView,
)
async def decide_extension_authorization(
    install_id: str,
    body: AuthorizeBody,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
) -> InstallRecordView:
    """Apply an explicit operator/organization authorization decision."""
    scope = ExtensionScope(org_id=body.org_id, workspace_id=body.workspace_id)
    await _require_scope_authority(scope, auth)
    try:
        record = await service.authorize(
            install_id,
            actor=_actor(auth),
            scope=scope,
            approve=body.approve,
            reason=body.reason,
        )
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    return _record_view(record)


@router.post(
    "/installations/{install_id}/installation",
    response_model=InstallRecordView,
)
async def install_extension(
    install_id: str,
    body: InstallBody,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
) -> InstallRecordView:
    """Install the authorized artifact and activate it if every check passes.

    A failed activation answers 409 with the record's truthful FAILED state;
    the same bound payload can be presented again to recover.
    """
    scope = ExtensionScope(org_id=body.org_id, workspace_id=body.workspace_id)
    await _require_scope_authority(scope, auth)
    try:
        record = await service.install(
            install_id,
            actor=_actor(auth),
            scope=scope,
            payload=_decode_payload(body.payload_b64),
        )
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    return _record_view(record)


@router.get("/installations/{install_id}", response_model=InstallRecordView)
async def get_extension_installation(
    install_id: str,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
    org_id: Annotated[str, Query(min_length=1)],
    workspace_id: Annotated[str, Query()] = "",
) -> InstallRecordView:
    """Read one install record.

    The displayed permissions are read through the snapshot integrity check —
    a corrupted snapshot fails loudly instead of displaying permissions nobody
    approved.
    """
    try:
        record = await service.get(
            install_id, scope=ExtensionScope(org_id=org_id, workspace_id=workspace_id)
        )
        displayed = await service.permissions_in_snapshot(record)
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    return _record_view(record, requested_permissions=displayed)


@router.get(
    "/installations/{install_id}/transitions",
    response_model=list[TransitionView],
)
async def get_extension_installation_transitions(
    install_id: str,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
    org_id: Annotated[str, Query(min_length=1)],
    workspace_id: Annotated[str, Query()] = "",
) -> list[TransitionView]:
    """The audited transition trail: actor, scope, version and reason per step."""
    try:
        transitions = await service.transitions(
            install_id, scope=ExtensionScope(org_id=org_id, workspace_id=workspace_id)
        )
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    return [_transition_view(transition) for transition in transitions]


@router.post("/expired-authorizations")
async def sweep_expired_authorizations(
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
    auth: RequireAuth,
) -> dict[str, int]:
    """Operator maintenance: abandon every expired authorization request.

    The decision-time check is defense in depth; this sweep is the durable
    guarantee that abandoned requests do not linger authorized-adjacent.
    Abandoned records can never reach ACTIVE.
    """
    return {"abandoned": await service.expire_abandoned()}


@router.get("/active", response_model=InstallRecordView)
async def get_active_extension(
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
    org_id: Annotated[str, Query(min_length=1)],
    extension_id: Annotated[str, Query(min_length=1)],
    workspace_id: Annotated[str, Query()] = "",
) -> InstallRecordView:
    """The active record for an extension in a scope, or 404 when none."""
    record = await service.active(
        ExtensionScope(org_id=org_id, workspace_id=workspace_id), extension_id
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no active extension {extension_id!r} in this scope",
        )
    return _record_view(record)


# ---------------------------------------------------------------------------
# M9-I3 (#978): truthful operational views.
#
# Every view below is a projection over canonical evidence: the install
# lifecycle store, re-derived compatibility, dependency readiness, host-
# recorded observations, and the durable operator decisions. There is
# deliberately no route by which an extension could report its own health —
# observations enter through the host's invocation seam only, so nothing on
# these endpoints is self-report.
# ---------------------------------------------------------------------------


def get_health_service(request: Request) -> ExtensionHealthService:
    """Return the operational-view facade wired by the process Container."""
    container = getattr(request.app.state, "container", None)
    if container is None or not hasattr(container, "ensure_extension_health_service"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No extension health service is configured",
        )
    return cast(ExtensionHealthService, container.ensure_extension_health_service())


class OperationalStatusView(BaseModel):
    """The truthful operational projection of one extension version.

    ``healthy`` is a state (healthy/degraded/unhealthy/unmeasured), not a
    boolean: "no evidence" must be distinguishable from "evidence of
    health". ``ready`` is false whenever any gate fails, and
    ``not_ready_reasons`` says exactly which.
    """

    model_config = ConfigDict(extra="forbid")

    extension_id: str
    version: str
    installed: bool
    authorized: bool
    compatible: bool
    dependency_ready: bool
    healthy: str
    policy_state: str
    ready: bool
    live: bool
    summary: str
    not_ready_reasons: tuple[str, ...]
    incompatibility_failures: tuple[str, ...]
    dependency_failures: tuple[str, ...]


class ErrorRecordView(BaseModel):
    """One classified failure with its extension/version/dependency provenance."""

    model_config = ConfigDict(extra="forbid")

    error_id: str
    at: str
    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    kind: str
    code: str
    message: str
    dependency: str | None = None
    dependency_version: str | None = None


class UsageDigestView(BaseModel):
    """Aggregated usage facts for one (extension, version) pair.

    Unmeasured metrics are ``null`` — absent, never zero — so a rank by cost
    or latency cannot be gamed by silence.
    """

    model_config = ConfigDict(extra="forbid")

    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    invocations: int
    failures: int
    error_rate: float | None = None
    latency_samples: int
    latency_avg_ms: float | None = None
    latency_max_ms: float | None = None
    cost_units_total: float | None = None
    active: bool


class SloPositionView(BaseModel):
    """SLO/alert inputs for one extension version (ADR-038 shape)."""

    model_config = ConfigDict(extra="forbid")

    slo_target: float
    window_observations: int
    observed_success_rate: float | None = None
    error_budget_remaining: float | None = None
    budget_exhausted: bool


class OperatorDecisionView(BaseModel):
    """One audited operator decision over an extension's runtime admission."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    at: str
    org_id: str
    workspace_id: str
    extension_id: str
    action: str
    state: str
    actor: str
    reason: str


class HealthDetailView(BaseModel):
    """One extension's status, its newest failures, and its SLO position."""

    model_config = ConfigDict(extra="forbid")

    status: OperationalStatusView
    recent_errors: list[ErrorRecordView]
    slo: SloPositionView | None = None


class TelemetryExportView(BaseModel):
    """Exportable telemetry for a scope: the same objects the views serve."""

    model_config = ConfigDict(extra="forbid")

    statuses: list[OperationalStatusView]
    usage: list[UsageDigestView]
    errors: list[ErrorRecordView]
    operator_decisions: list[OperatorDecisionView]


class OperatorActionBody(ScopeBody):
    model_config = ConfigDict(extra="forbid")

    action: ExtensionOperatorAction
    reason: str = Field(min_length=1)


def _status_view(projection: ExtensionOperationalStatus) -> OperationalStatusView:
    return OperationalStatusView(
        extension_id=projection.extension_id,
        version=projection.version,
        installed=projection.installed,
        authorized=projection.authorized,
        compatible=projection.compatible,
        dependency_ready=projection.dependency_ready,
        healthy=str(projection.healthy),
        policy_state=str(projection.policy_state),
        ready=projection.ready,
        live=projection.live,
        summary=str(projection.summary),
        not_ready_reasons=projection.not_ready_reasons,
        incompatibility_failures=projection.incompatibility_failures,
        dependency_failures=projection.dependency_failures,
    )


def _error_view(error: ExtensionErrorRecord) -> ErrorRecordView:
    return ErrorRecordView(
        error_id=error.error_id,
        at=error.at.isoformat(),
        org_id=error.org_id,
        workspace_id=error.workspace_id,
        extension_id=error.extension_id,
        version=error.version,
        kind=str(error.kind),
        code=error.code,
        message=error.message,
        dependency=error.dependency,
        dependency_version=error.dependency_version,
    )


def _digest_view(digest: ExtensionUsageDigest) -> UsageDigestView:
    return UsageDigestView(
        org_id=digest.org_id,
        workspace_id=digest.workspace_id,
        extension_id=digest.extension_id,
        version=digest.version,
        invocations=digest.invocations,
        failures=digest.failures,
        error_rate=digest.error_rate,
        latency_samples=digest.latency_samples,
        latency_avg_ms=digest.latency_avg_ms,
        latency_max_ms=digest.latency_max_ms,
        cost_units_total=digest.cost_units_total,
        active=digest.active,
    )


def _slo_view(position: SloPosition) -> SloPositionView:
    return SloPositionView(
        slo_target=position.slo_target,
        window_observations=position.window_observations,
        observed_success_rate=position.observed_success_rate,
        error_budget_remaining=position.error_budget_remaining,
        budget_exhausted=position.budget_exhausted,
    )


def _decision_view(decision: OperatorDecision) -> OperatorDecisionView:
    return OperatorDecisionView(
        decision_id=decision.decision_id,
        at=decision.at.isoformat(),
        org_id=decision.org_id,
        workspace_id=decision.workspace_id,
        extension_id=decision.extension_id,
        action=str(decision.action),
        state=str(decision.state),
        actor=decision.actor,
        reason=decision.reason,
    )


@router.get("/health", response_model=list[OperationalStatusView])
async def get_extension_health_overview(
    auth: RequireAuth,
    health: Annotated[ExtensionHealthService, Depends(get_health_service)],
    org_id: Annotated[str, Query(min_length=1)],
    workspace_id: Annotated[str, Query()] = "",
) -> list[OperationalStatusView]:
    """Operational status of every extension recorded in the scope.

    Readiness here is earned, not claimed: a projection is ready only when
    the canonical lifecycle, a fresh compatibility evaluation, dependency
    readiness, recorded health, and the operator state all allow it.
    """
    scope = ExtensionScope(org_id=org_id, workspace_id=workspace_id)
    projections = await health.statuses(scope)
    return [_status_view(projection) for projection in projections]


@router.get("/health/{extension_id}", response_model=HealthDetailView)
async def get_extension_health_detail(
    extension_id: str,
    auth: RequireAuth,
    health: Annotated[ExtensionHealthService, Depends(get_health_service)],
    org_id: Annotated[str, Query(min_length=1)],
    version: Annotated[str | None, Query()] = None,
    workspace_id: Annotated[str, Query()] = "",
    slo_target: Annotated[float, Query(gt=0.0, lt=1.0)] = 0.99,
    error_limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> HealthDetailView:
    """One extension's status (``version`` selects a historical one), its
    newest classified failures, and its SLO error-budget position.

    A historical version projects with its own evidence and the scope's
    current active pointer, so a superseded or removed version stays
    identifiable and never reports active.
    """
    scope = ExtensionScope(org_id=org_id, workspace_id=workspace_id)
    projection = (
        await health.version_status(scope, extension_id, version)
        if version is not None
        else await health.status(scope, extension_id)
    )
    if projection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no install record for {extension_id!r} in this scope",
        )
    slo = await health.slo(scope, extension_id, slo_target=slo_target)
    errors = await health.recent_errors(scope, extension_id, limit=error_limit)
    return HealthDetailView(
        status=_status_view(projection),
        recent_errors=[_error_view(error) for error in errors],
        slo=_slo_view(slo) if slo is not None else None,
    )


@router.get("/usage", response_model=list[UsageDigestView])
async def get_extension_usage_ranking(
    auth: RequireAuth,
    health: Annotated[ExtensionHealthService, Depends(get_health_service)],
    org_id: Annotated[str, Query(min_length=1)],
    by: RankingMetric = RankingMetric.USAGE,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    workspace_id: Annotated[str, Query()] = "",
) -> list[UsageDigestView]:
    """Rank extension versions by usage, cost, failures, error rate, or latency.

    Unmeasured metrics sort last rather than reading as zero, and every row
    keeps its exact version with an explicit ``active`` flag, so historical
    traffic stays attributable without reporting removed versions active.
    """
    scope = ExtensionScope(org_id=org_id, workspace_id=workspace_id)
    ranked = await health.rank(scope, by, limit=limit)
    return [_digest_view(digest) for digest in ranked]


@router.get("/telemetry/export", response_model=TelemetryExportView)
async def export_extension_telemetry(
    auth: RequireAuth,
    health: Annotated[ExtensionHealthService, Depends(get_health_service)],
    org_id: Annotated[str, Query(min_length=1)],
    workspace_id: Annotated[str, Query()] = "",
) -> TelemetryExportView:
    """Exportable telemetry for one scope.

    Shares one code path with the operator views, so the export can never
    disagree with what the dashboards serve.
    """
    scope = ExtensionScope(org_id=org_id, workspace_id=workspace_id)
    exported = await health.export_telemetry(scope)
    return TelemetryExportView(
        statuses=[_status_view(item) for item in exported.statuses],
        usage=[_digest_view(item) for item in exported.usage],
        errors=[_error_view(item) for item in exported.errors],
        operator_decisions=[_decision_view(item) for item in exported.operator_decisions],
    )


@router.post(
    "/health/{extension_id}/operator",
    response_model=OperatorDecisionView,
    status_code=200,
)
async def decide_extension_operator_state(
    extension_id: str,
    body: OperatorActionBody,
    auth: RequireAuth,
    health: Annotated[ExtensionHealthService, Depends(get_health_service)],
) -> OperatorDecisionView:
    """Apply a durable operator decision: enable, disable, quarantine, release.

    The decision is append-only evidence with the authenticated principal as
    the actor and the required reason; the newest decision is the durable
    state that survives restarts. This is an admission hold, not a health
    judgement — the projection keeps the two distinct.
    """
    scope = ExtensionScope(org_id=body.org_id, workspace_id=body.workspace_id)
    await _require_scope_authority(scope, auth)
    decision = await health.apply_decision(
        OperatorDecision(
            decision_id=uuid.uuid4().hex,
            at=datetime.now(UTC),
            org_id=scope.org_id,
            workspace_id=scope.workspace_id,
            extension_id=extension_id,
            action=body.action,
            state=state_for_action(body.action),
            actor=_actor(auth),
            reason=body.reason,
        )
    )
    return _decision_view(decision)


# The handlers are this module's public surface: FastAPI registers them from
# the decorators, which static import scanning cannot see. Declaring them here
# is the same statement a2a.py's __all__ makes (see the comment there), and is
# what keeps this module's route handlers out of the fastapi-route-handler
# Vulture ledger: a new handler must join this list (the drift is caught by
# test_all_covers_every_route_handler), not silently re-enter the dead-code
# ratchet as unbanked debt.
__all__ = [
    "decide_extension_authorization",
    "decide_extension_operator_state",
    "export_extension_telemetry",
    "get_active_extension",
    "get_extension_health_detail",
    "get_extension_health_overview",
    "get_extension_installation",
    "get_extension_installation_transitions",
    "get_extension_service",
    "get_extension_usage_ranking",
    "get_health_service",
    "inspect_extension",
    "install_extension",
    "router",
    "sweep_expired_authorizations",
]
