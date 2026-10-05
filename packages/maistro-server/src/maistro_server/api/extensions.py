"""Governed extension install lifecycle over HTTP (#953, M9-B2).

These routes are the operator surface of the inspect → authorize → install
state machine; they execute nothing themselves. Every write attributes the
authenticated principal as the actor, every decision requires a reason, and
the permissions shown back are read from the install record's immutable
manifest snapshot — never re-derived from a request body.

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
    ArtifactMismatch,
    ExtensionInstallRecord,
    ExtensionInstallService,
    ExtensionLifecycleError,
    ExtensionPackage,
    ExtensionScope,
    ExtensionTransition,
    InspectionConflict,
    InvalidTransition,
    ManifestRejected,
    PinConflict,
    PinRecord,
    PreflightError,
    PreflightReport,
    RemovalNote,
    UnknownInstall,
)
from maistro.extensions.types import TrustEvidence
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
    status_reason: str | None = None
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
        status_reason=record.status_reason,
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
    if isinstance(exc, (PinConflict, PreflightError)):
        # A refused preflight changed nothing; 409 with the named checks.
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
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
            trust_evidence=TrustEvidence(
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
# Post-install lifecycle (#954, M9-B3): pin, upgrade, rollback, disable,
# resume, remove, resolution and reconciliation. Same discipline as above:
# routes execute nothing themselves, every write attributes the
# authenticated principal, every decision carries a reason, and scope
# authority is checked before the service is touched.
# ---------------------------------------------------------------------------


class ExtensionRefBody(ScopeBody):
    """Names one extension inside a scope (shared by pin routes)."""

    model_config = ConfigDict(extra="forbid")

    extension_id: str = Field(min_length=1)


class PinBody(ExtensionRefBody):
    model_config = ConfigDict(extra="forbid")

    version: str | None = None
    reason: str = Field(min_length=1)


class UnpinBody(ExtensionRefBody):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class UpgradeBody(ScopeBody):
    model_config = ConfigDict(extra="forbid")

    manifest_text: str = Field(min_length=1)
    payload_b64: str = Field(min_length=1)
    trust: TrustEvidenceBody


class RollbackBody(ScopeBody):
    model_config = ConfigDict(extra="forbid")

    payload_b64: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    allow_broadened: bool = False


class DisableBody(ScopeBody):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class ResumeBody(ScopeBody):
    model_config = ConfigDict(extra="forbid")

    payload_b64: str = Field(min_length=1)


class RemoveBody(ScopeBody):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class ReconcileBody(ExtensionRefBody):
    model_config = ConfigDict(extra="forbid")


class PinView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_id: str
    workspace_id: str
    extension_id: str
    version: str
    pinned_by: str
    reason: str
    pinned_at: str | None


class PinEventView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int
    at: str
    action: str
    version: str | None
    actor: str
    reason: str


class PinStatusView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: PinView | None
    events: tuple[PinEventView, ...]


class PreflightCheckView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    detail: str


class AuthorityDeltaView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new: tuple[str, ...]
    retained: tuple[str, ...]
    dropped: tuple[str, ...]


class PreflightView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str
    extension_id: str
    from_version: str | None
    to_version: str
    checks: tuple[PreflightCheckView, ...]
    authority: AuthorityDeltaView
    allowed: bool
    broadens_authority: bool


class UpgradeView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: InstallRecordView
    preflight: PreflightView


class RemovalNoteView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int
    at: str
    install_id: str
    extension_id: str
    version: str
    actor: str
    purged: tuple[str, ...]
    failed: tuple[str, ...]


def _pin_view(pin: PinRecord) -> PinView:
    return PinView(
        org_id=pin.org_id,
        workspace_id=pin.workspace_id,
        extension_id=pin.extension_id,
        version=pin.version,
        pinned_by=pin.pinned_by,
        reason=pin.reason,
        pinned_at=_iso(pin.pinned_at),
    )


def _preflight_view(report: PreflightReport) -> PreflightView:
    return PreflightView(
        operation=report.operation,
        extension_id=report.extension_id,
        from_version=report.from_version,
        to_version=report.to_version,
        checks=tuple(
            PreflightCheckView(name=check.name, passed=check.passed, detail=check.detail)
            for check in report.checks
        ),
        authority=AuthorityDeltaView(
            new=report.authority.new,
            retained=report.authority.retained,
            dropped=report.authority.dropped,
        ),
        allowed=report.allowed,
        broadens_authority=report.broadens_authority,
    )


def _removal_note_view(note: RemovalNote) -> RemovalNoteView:
    return RemovalNoteView(
        seq=note.seq,
        at=note.at.isoformat(),
        install_id=note.install_id,
        extension_id=note.extension_id,
        version=note.version,
        actor=note.actor,
        purged=note.purged,
        failed=note.failed,
    )


@router.post("/pins", response_model=PinView, status_code=201)
async def pin_extension(
    body: PinBody,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
) -> PinView:
    """Hold the extension at its active version against version changes."""
    scope = ExtensionScope(org_id=body.org_id, workspace_id=body.workspace_id)
    await _require_scope_authority(scope, auth)
    try:
        pin = await service.pin(
            scope,
            body.extension_id,
            actor=_actor(auth),
            version=body.version,
            reason=body.reason,
        )
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    return _pin_view(pin)


@router.post("/pins/release", response_model=PinStatusView)
async def release_extension_pin(
    body: UnpinBody,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
) -> PinStatusView:
    """Release the version pin. Idempotent; the release is audited."""
    scope = ExtensionScope(org_id=body.org_id, workspace_id=body.workspace_id)
    await _require_scope_authority(scope, auth)
    try:
        await service.unpin(scope, body.extension_id, actor=_actor(auth), reason=body.reason)
        pin, events = await service.pin_status(scope, body.extension_id)
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    return PinStatusView(
        pin=_pin_view(pin) if pin is not None else None,
        events=tuple(
            PinEventView(
                seq=event.seq,
                at=event.at.isoformat(),
                action=event.action,
                version=event.version,
                actor=event.actor,
                reason=event.reason,
            )
            for event in events
        ),
    )


@router.get("/pins", response_model=PinStatusView)
async def get_extension_pin(
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
    org_id: Annotated[str, Query(min_length=1)],
    extension_id: Annotated[str, Query(min_length=1)],
    workspace_id: Annotated[str, Query()] = "",
) -> PinStatusView:
    """The scope's current pin and its audited event trail."""
    scope = ExtensionScope(org_id=org_id, workspace_id=workspace_id)
    pin, events = await service.pin_status(scope, extension_id)
    return PinStatusView(
        pin=_pin_view(pin) if pin is not None else None,
        events=tuple(
            PinEventView(
                seq=event.seq,
                at=event.at.isoformat(),
                action=event.action,
                version=event.version,
                actor=event.actor,
                reason=event.reason,
            )
            for event in events
        ),
    )


@router.post("/upgrades", response_model=UpgradeView, status_code=201)
async def upgrade_extension(
    body: UpgradeBody,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
) -> UpgradeView:
    """Begin a version upgrade: preflight, then the governed inspection.

    The response carries the preflight report (with the authority delta an
    operator is deciding on) and the candidate's install record in
    ``awaiting_authorization``. Activation is a separate, explicit call —
    and only after the authorization decision.
    """
    scope = ExtensionScope(org_id=body.org_id, workspace_id=body.workspace_id)
    await _require_scope_authority(scope, auth)
    try:
        record, report = await service.upgrade(
            actor=_actor(auth),
            scope=scope,
            package=ExtensionPackage(
                manifest_bytes=body.manifest_text.encode("utf-8"),
                payload=_decode_payload(body.payload_b64),
            ),
            trust_evidence=TrustEvidence(
                publisher_id=body.trust.publisher_id,
                signature_present=body.trust.signature_present,
                signer_key_id=body.trust.signer_key_id,
                package_sha256=body.trust.package_sha256,
            ),
        )
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    return UpgradeView(record=_record_view(record), preflight=_preflight_view(report))


@router.post(
    "/installations/{install_id}/upgrade-activation",
    response_model=InstallRecordView,
)
async def activate_extension_upgrade(
    install_id: str,
    body: InstallBody,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
) -> InstallRecordView:
    """Activate an authorized upgrade: the pointer swaps once and the
    previous version is retained as superseded rollback material."""
    scope = ExtensionScope(org_id=body.org_id, workspace_id=body.workspace_id)
    await _require_scope_authority(scope, auth)
    try:
        record = await service.activate_upgrade(
            install_id,
            actor=_actor(auth),
            scope=scope,
            payload=_decode_payload(body.payload_b64),
        )
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    return _record_view(record)


@router.post(
    "/installations/{install_id}/rollback",
    response_model=InstallRecordView,
)
async def rollback_extension(
    install_id: str,
    body: RollbackBody,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
) -> InstallRecordView:
    """Restore a superseded version after the preflight proves it safe.

    A refused rollback answers 409 with the failed checks named; the current
    state is untouched. Restoring permissions the current version had
    dropped requires ``allow_broadened`` — an explicit acknowledgment, not a
    default.
    """
    scope = ExtensionScope(org_id=body.org_id, workspace_id=body.workspace_id)
    await _require_scope_authority(scope, auth)
    try:
        record = await service.rollback(
            install_id,
            actor=_actor(auth),
            scope=scope,
            payload=_decode_payload(body.payload_b64),
            reason=body.reason,
            allow_broadened=body.allow_broadened,
        )
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    return _record_view(record)


@router.post(
    "/installations/{install_id}/disable",
    response_model=InstallRecordView,
)
async def disable_extension(
    install_id: str,
    body: DisableBody,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
) -> InstallRecordView:
    """Suspend the extension: invocation resolution stops immediately."""
    scope = ExtensionScope(org_id=body.org_id, workspace_id=body.workspace_id)
    await _require_scope_authority(scope, auth)
    try:
        record = await service.disable(
            install_id, actor=_actor(auth), scope=scope, reason=body.reason
        )
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    return _record_view(record)


@router.post(
    "/installations/{install_id}/resume",
    response_model=InstallRecordView,
)
async def resume_extension(
    install_id: str,
    body: ResumeBody,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
) -> InstallRecordView:
    """Re-activate a disabled extension from its bound artifact; the frozen
    grant stands, so no new authorization is required."""
    scope = ExtensionScope(org_id=body.org_id, workspace_id=body.workspace_id)
    await _require_scope_authority(scope, auth)
    try:
        record = await service.resume(
            install_id,
            actor=_actor(auth),
            scope=scope,
            payload=_decode_payload(body.payload_b64),
        )
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    return _record_view(record)


@router.post(
    "/installations/{install_id}/removal",
    response_model=InstallRecordView,
)
async def remove_extension(
    install_id: str,
    body: RemoveBody,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
) -> InstallRecordView:
    """Uninstall: authority ends, canonical evidence is retained, and the
    owned-resource cleanup policy runs with its purge reported."""
    scope = ExtensionScope(org_id=body.org_id, workspace_id=body.workspace_id)
    await _require_scope_authority(scope, auth)
    try:
        record = await service.remove(
            install_id, actor=_actor(auth), scope=scope, reason=body.reason
        )
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    return _record_view(record)


@router.get(
    "/installations/{install_id}/removal-notes",
    response_model=list[RemovalNoteView],
)
async def get_extension_removal_notes(
    install_id: str,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
    org_id: Annotated[str, Query(min_length=1)],
    workspace_id: Annotated[str, Query()] = "",
) -> list[RemovalNoteView]:
    """The audited owned-resource cleanup reports for one removal."""
    try:
        notes = await service.removal_history(
            install_id, scope=ExtensionScope(org_id=org_id, workspace_id=workspace_id)
        )
    except ExtensionLifecycleError as exc:
        raise _http_error(exc) from exc
    return [_removal_note_view(note) for note in notes]


@router.get("/resolution", response_model=InstallRecordView)
async def resolve_extension(
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
    org_id: Annotated[str, Query(min_length=1)],
    extension_id: Annotated[str, Query(min_length=1)],
    workspace_id: Annotated[str, Query()] = "",
) -> InstallRecordView:
    """What an invocation of this extension would load right now.

    This is the invocation-resolution seam made observable: a disabled,
    superseded or removed extension answers 404 — nothing is servable.
    """
    record = await service.resolve(
        ExtensionScope(org_id=org_id, workspace_id=workspace_id), extension_id
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"extension {extension_id!r} is not currently resolvable in this scope",
        )
    return _record_view(record)


@router.post("/reconciliation")
async def reconcile_extension(
    body: ReconcileBody,
    auth: RequireAuth,
    service: Annotated[ExtensionInstallService, Depends(get_extension_service)],
) -> dict[str, int]:
    """Operator maintenance: repair the pointer/state invariants a crash can
    leave behind. Every repair is itself an audited transition."""
    scope = ExtensionScope(org_id=body.org_id, workspace_id=body.workspace_id)
    await _require_scope_authority(scope, auth)
    repaired = await service.reconcile(scope=scope, extension_id=body.extension_id)
    return {"repaired": len(repaired)}
