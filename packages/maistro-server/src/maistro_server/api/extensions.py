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
from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from maistro.extensions import (
    INHERITANCE_SEMANTICS,
    ArtifactMismatch,
    ExtensionCandidate,
    ExtensionInstallRecord,
    ExtensionInstallService,
    ExtensionLifecycleError,
    ExtensionPackage,
    ExtensionPin,
    ExtensionPolicyEngine,
    ExtensionPolicyViolation,
    ExtensionScope,
    ExtensionTransition,
    InspectionConflict,
    InvalidTransition,
    ManifestRejected,
    OrgExtensionPolicy,
    PolicyAuditEvent,
    PolicyConfigurationError,
    PolicyDecision,
    UnknownInstall,
    WorkspaceExtensionPolicy,
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


def get_extension_policy_engine(request: Request) -> ExtensionPolicyEngine:
    """Return the organization/Workspace policy engine wired by the Container."""
    container = getattr(request.app.state, "container", None)
    if container is None or not hasattr(container, "ensure_extension_policy_engine"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No extension policy engine is configured",
        )
    return cast(ExtensionPolicyEngine, container.ensure_extension_policy_engine())


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


class ExtensionPinBody(BaseModel):
    """One organization pin: the approved publisher, optionally the exact version."""

    model_config = ConfigDict(extra="forbid")

    publisher_id: str = Field(min_length=1)
    version: str | None = None


class OrgPolicyBody(BaseModel):
    """The organization layer, set wholesale (#971).

    ``allowed_extensions``/``approved_publishers`` of ``None`` mean "no
    restriction"; an empty list means "deny/publish nothing" — both are
    deliberate, expressible states, never conflated with each other.
    """

    model_config = ConfigDict(extra="forbid")

    allowed_extensions: list[str] | None = None
    denied_extensions: list[str] = Field(default_factory=list)
    approved_publishers: list[str] | None = None
    pins: dict[str, ExtensionPinBody] = Field(default_factory=dict)


class WorkspacePolicyBody(BaseModel):
    """One Workspace's narrowing layer, set wholesale (#971)."""

    model_config = ConfigDict(extra="forbid")

    enabled_extensions: list[str] = Field(default_factory=list)
    denied_extensions: list[str] = Field(default_factory=list)
    permission_ceilings: dict[str, list[str]] = Field(default_factory=dict)


class PolicyExplainBody(BaseModel):
    """A dry-run candidate for the deterministic policy explanation.

    The scope is the request path, not the body: one candidate, one scope,
    stated once.
    """

    model_config = ConfigDict(extra="forbid")

    extension_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    permissions: list[str] = Field(default_factory=list)


class ExtensionConfigBody(ScopeBody):
    """One tenant-scoped extension configuration value (#971)."""

    model_config = ConfigDict(extra="forbid")

    extension_id: str = Field(min_length=1)
    key: str = Field(min_length=1)
    value: str


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


class PinView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publisher_id: str
    version: str | None


class OrgPolicyView(BaseModel):
    """The organization layer as configured (admin inspection, #971)."""

    model_config = ConfigDict(extra="forbid")

    org_id: str
    allowed_extensions: list[str] | None
    denied_extensions: list[str]
    approved_publishers: list[str] | None
    pins: dict[str, PinView]


class WorkspacePolicyView(BaseModel):
    """One Workspace's narrowing layer as configured (admin inspection)."""

    model_config = ConfigDict(extra="forbid")

    org_id: str
    workspace_id: str
    enabled_extensions: list[str]
    denied_extensions: list[str]
    permission_ceilings: dict[str, list[str]]


class PolicyRuleOutcomeView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer: str
    rule: str
    denied: bool
    detail: str


class PolicyDecisionView(BaseModel):
    """A policy decision with its full rule-by-rule trace (#971)."""

    model_config = ConfigDict(extra="forbid")

    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    publisher: str
    requested_permissions: list[str]
    verdict: str
    allowed: bool
    explanation: str
    trace: list[PolicyRuleOutcomeView]


class PolicyAuditEventView(BaseModel):
    """One row of the policy audit trail (admin inspection, #971)."""

    model_config = ConfigDict(extra="forbid")

    seq: int
    at: str
    actor: str
    kind: str
    org_id: str
    workspace_id: str
    extension_id: str
    detail: str


class ExtensionConfigView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_id: str
    workspace_id: str
    extension_id: str
    key: str
    value: str


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
    if isinstance(exc, ExtensionPolicyViolation):
        return HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
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


# -- organization/Workspace policy, pinning, audit (#971, M9-G3) -------------


def _org_view(policy: OrgExtensionPolicy) -> OrgPolicyView:
    return OrgPolicyView(
        org_id=policy.org_id,
        allowed_extensions=(
            sorted(policy.allowed_extensions) if policy.allowed_extensions is not None else None
        ),
        denied_extensions=sorted(policy.denied_extensions),
        approved_publishers=(
            sorted(policy.approved_publishers) if policy.approved_publishers is not None else None
        ),
        pins={
            extension_id: PinView(publisher_id=pin.publisher_id, version=pin.version)
            for extension_id, pin in sorted(policy.pins.items())
        },
    )


def _workspace_view(policy: WorkspaceExtensionPolicy) -> WorkspacePolicyView:
    return WorkspacePolicyView(
        org_id=policy.org_id,
        workspace_id=policy.workspace_id,
        enabled_extensions=sorted(policy.enabled_extensions),
        denied_extensions=sorted(policy.denied_extensions),
        permission_ceilings={
            extension_id: sorted(ceiling)
            for extension_id, ceiling in sorted(policy.permission_ceilings.items())
        },
    )


def _decision_view(decision: PolicyDecision) -> PolicyDecisionView:
    return PolicyDecisionView(
        org_id=decision.org_id,
        workspace_id=decision.workspace_id,
        extension_id=decision.extension_id,
        version=decision.version,
        publisher=decision.publisher,
        requested_permissions=list(decision.requested_permissions),
        verdict=str(decision.verdict),
        allowed=decision.allowed,
        explanation=decision.explanation,
        trace=[
            PolicyRuleOutcomeView(
                layer=str(outcome.layer),
                rule=outcome.rule,
                denied=outcome.denied,
                detail=outcome.detail,
            )
            for outcome in decision.trace
        ],
    )


def _audit_view(event: PolicyAuditEvent) -> PolicyAuditEventView:
    return PolicyAuditEventView(
        seq=event.seq,
        at=event.at.isoformat(),
        actor=event.actor,
        kind=event.kind,
        org_id=event.org_id,
        workspace_id=event.workspace_id,
        extension_id=event.extension_id,
        detail=event.detail,
    )


@router.put("/policy/orgs/{org_id}", response_model=OrgPolicyView)
async def set_organization_extension_policy(
    org_id: str,
    body: OrgPolicyBody,
    auth: RequireAuth,
    engine: Annotated[ExtensionPolicyEngine, Depends(get_extension_policy_engine)],
) -> OrgPolicyView:
    """Set the organization layer wholesale (allow/deny, publishers, pins).

    Org-only scopes are authenticated-principal-only until the B1/Stronghold
    tenancy substrate provides an org authority to check against — the same
    stated limitation as the org-only install-lifecycle routes.
    """
    policy = OrgExtensionPolicy(
        org_id=org_id,
        allowed_extensions=(
            frozenset(body.allowed_extensions) if body.allowed_extensions is not None else None
        ),
        denied_extensions=frozenset(body.denied_extensions),
        approved_publishers=(
            frozenset(body.approved_publishers) if body.approved_publishers is not None else None
        ),
        pins={
            extension_id: ExtensionPin(
                publisher_id=pin.publisher_id,
                version=pin.version,
            )
            for extension_id, pin in body.pins.items()
        },
    )
    try:
        await engine.set_org_policy(policy, actor=_actor(auth))
    except PolicyConfigurationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _org_view(policy)


@router.get("/policy/orgs/{org_id}")
async def inspect_organization_extension_policy(
    org_id: str,
    auth: RequireAuth,
    engine: Annotated[ExtensionPolicyEngine, Depends(get_extension_policy_engine)],
) -> dict[str, object]:
    """Admin inspection of an organization's extension policy layer."""
    del auth  # authenticated-principal presence is the requirement
    policy = engine.org_policy(org_id)
    return {
        "org": _org_view(policy).model_dump() if policy is not None else None,
        "workspace": None,
        "inheritance": list(INHERITANCE_SEMANTICS),
    }


@router.put("/policy/orgs/{org_id}/workspaces/{workspace_id}", response_model=WorkspacePolicyView)
async def set_workspace_extension_policy(
    org_id: str,
    workspace_id: str,
    body: WorkspacePolicyBody,
    auth: RequireAuth,
    engine: Annotated[ExtensionPolicyEngine, Depends(get_extension_policy_engine)],
) -> WorkspacePolicyView:
    """Set one Workspace's narrowing layer (enablement, ceilings, denials).

    Workspace ADMINISTER membership is the operator authority, as for every
    other Workspace-scoped extension write.
    """
    scope = ExtensionScope(org_id=org_id, workspace_id=workspace_id)
    await _require_scope_authority(scope, auth)
    policy = WorkspaceExtensionPolicy(
        org_id=org_id,
        workspace_id=workspace_id,
        enabled_extensions=frozenset(body.enabled_extensions),
        denied_extensions=frozenset(body.denied_extensions),
        permission_ceilings={
            extension_id: frozenset(ceiling)
            for extension_id, ceiling in body.permission_ceilings.items()
        },
    )
    try:
        await engine.set_workspace_policy(policy, actor=_actor(auth))
    except PolicyConfigurationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _workspace_view(policy)


@router.get("/policy/orgs/{org_id}/workspaces/{workspace_id}")
async def inspect_workspace_extension_policy(
    org_id: str,
    workspace_id: str,
    auth: RequireAuth,
    engine: Annotated[ExtensionPolicyEngine, Depends(get_extension_policy_engine)],
) -> dict[str, object]:
    """Admin inspection of the effective policy for one Workspace scope."""
    scope = ExtensionScope(org_id=org_id, workspace_id=workspace_id)
    await _require_scope_authority(scope, auth)
    org = engine.org_policy(org_id)
    workspace = engine.workspace_policy(org_id, workspace_id)
    return {
        "org": _org_view(org).model_dump() if org is not None else None,
        "workspace": (_workspace_view(workspace).model_dump() if workspace is not None else None),
        "inheritance": list(INHERITANCE_SEMANTICS),
    }


@router.post(
    "/policy/orgs/{org_id}/workspaces/{workspace_id}/decisions",
    response_model=PolicyDecisionView,
)
async def explain_extension_policy_decision(
    org_id: str,
    workspace_id: str,
    body: PolicyExplainBody,
    auth: RequireAuth,
    engine: Annotated[ExtensionPolicyEngine, Depends(get_extension_policy_engine)],
) -> PolicyDecisionView:
    """Dry-run a candidate against the current policy and explain the result.

    Deterministic and side-effect-free: no record, no audit row — the same
    rule order the enforcement path applies, surfaced for inspection.
    """
    scope = ExtensionScope(org_id=org_id, workspace_id=workspace_id)
    await _require_scope_authority(scope, auth)
    decision = engine.explain(
        ExtensionCandidate(
            extension_id=body.extension_id,
            version=body.version,
            publisher=body.publisher,
            permissions=tuple(body.permissions),
        ),
        scope,
    )
    return _decision_view(decision)


@router.get("/policy/orgs/{org_id}/audit", response_model=list[PolicyAuditEventView])
async def get_extension_policy_audit(
    org_id: str,
    auth: RequireAuth,
    engine: Annotated[ExtensionPolicyEngine, Depends(get_extension_policy_engine)],
    workspace_id: Annotated[str, Query()] = "",
    kind: Annotated[str, Query()] = "",
) -> list[PolicyAuditEventView]:
    """The policy audit trail: policy changes and enforcement decisions."""
    del auth  # authenticated-principal presence is the requirement
    events = engine.audit_events(
        org_id,
        workspace_id=workspace_id or None,
        kind=kind or None,
    )
    return [_audit_view(event) for event in events]


@router.get("/state", response_model=ExtensionConfigView)
async def get_extension_configuration(
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
    org_id: Annotated[str, Query(min_length=1)],
    workspace_id: Annotated[str, Query()],
    extension_id: Annotated[str, Query(min_length=1)],
    key: Annotated[str, Query(min_length=1)],
) -> ExtensionConfigView:
    """Read one tenant-scoped extension configuration value.

    Workspace ownership is required, so Workspace B's principals cannot
    observe configuration Workspace A set even when they can name the scope
    (#971 acceptance: observation is tenant-scoped, not just the store).
    Only this scope's own values are reachable: a Workspace asking for a key
    another Workspace set observes 404, never the value.
    """
    scope = ExtensionScope(org_id=org_id, workspace_id=workspace_id)
    await _require_scope_authority(scope, auth)
    try:
        state = await service.extension_state(scope, extension_id)
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    value = state.get_config(key)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no such configuration key in this scope",
        )
    return ExtensionConfigView(
        org_id=org_id,
        workspace_id=workspace_id,
        extension_id=extension_id,
        key=key,
        value=value,
    )


@router.put("/state", response_model=ExtensionConfigView)
async def set_extension_configuration(
    body: ExtensionConfigBody,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
) -> ExtensionConfigView:
    """Set one tenant-scoped extension configuration value.

    Workspace ADMINISTER membership is required, and the value is stored
    under the full tenant triple: extension configuration never spans scopes.
    """
    scope = ExtensionScope(org_id=body.org_id, workspace_id=body.workspace_id)
    await _require_scope_authority(scope, auth)
    try:
        state = await service.extension_state(scope, body.extension_id)
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    state.set_config(body.key, body.value)
    return ExtensionConfigView(
        org_id=body.org_id,
        workspace_id=body.workspace_id,
        extension_id=body.extension_id,
        key=body.key,
        value=body.value,
    )


# The handlers are this module's public surface: FastAPI registers them from
# the decorators, which static import scanning cannot see. Declaring them here
# is the same statement a2a.py's __all__ makes (see the comment there), and is
# what keeps this module's route handlers out of the fastapi-route-handler
# Vulture ledger: a new handler must join this list (the drift is caught by
# test_all_covers_every_route_handler), not silently re-enter the dead-code
# ratchet as unbanked debt.
__all__ = [
    "decide_extension_authorization",
    "explain_extension_policy_decision",
    "get_active_extension",
    "get_extension_configuration",
    "get_extension_installation",
    "get_extension_installation_transitions",
    "get_extension_policy_audit",
    "get_extension_policy_engine",
    "get_extension_service",
    "inspect_extension",
    "inspect_organization_extension_policy",
    "inspect_workspace_extension_policy",
    "install_extension",
    "router",
    "set_extension_configuration",
    "set_organization_extension_policy",
    "set_workspace_extension_policy",
    "sweep_expired_authorizations",
]
