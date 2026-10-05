"""The inspect → authorize → install activation state machine (#953, M9-B2)
and the post-install lifecycle it hands over to (#954, M9-B3).

One service owns every transition. The contract, in order:

1. ``inspect`` parses the manifest bytes, verifies the payload against the
   manifest's own artifact claim, resolves compatibility and trust, computes
   the authority delta, and parks the candidate in
   ``AWAITING_AUTHORIZATION``. No extension code is imported or executed at
   any point — the loader is structurally unreachable from this phase.
2. ``authorize`` applies an explicit operator/organization decision. Denial
   (or expiry) is terminal and leaves nothing active; approval freezes the
   granted permission set to exactly what the immutable snapshot declares.
3. ``install`` re-verifies the presented payload against the digest bound at
   inspection, runs the host loader — the only code-execution seam, reachable
   only after authorization — and swaps the scope's active pointer once, after
   every check has passed. Failure is recorded truthfully (``FAILED`` with the
   reason) and the same bound artifact can be presented again to recover.
   Retries never duplicate install records and never widen the grant.

B3 (#954) finishes the lifecycle after activation, on the same machine and
through the same audited transitions:

- ``pin`` / ``unpin`` hold a version against version changes; contradicting
  operations fail closed until the pin is explicitly released.
- ``upgrade`` runs the version-change preflight and re-enters the SAME
  inspect → authorize path — an authority delta beyond the active grant is
  named and must be explicitly re-authorized before the new version can
  activate; ``activate_upgrade`` then swaps the pointer once and supersedes
  the old version, retaining it (and its frozen grant) as rollback material.
- ``rollback`` restores a SUPERSEDED version after proving compatibility and
  digest integrity, before anything changes; restoring authority the scope
  no longer grants requires the explicit broadening acknowledgment.
- ``disable`` / ``resume`` suspend and restore invocation resolution without
  touching historical evidence or the frozen grant.
- ``remove`` uninstalls: authority and the active pointer go, canonical
  evidence (records, transitions) is never deleted, and a host-supplied
  janitor may purge owned operational resources — with the purge reported.
- ``reconcile`` repairs the pointer/state invariants a crash can leave
  behind, so every retry lands on a truthful state.

Every transition is appended to the store's audit trail with actor, org /
workspace scope, extension id and version, and a reason.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from maistro.extensions.authority import AuthorityBaseline, compute_authority_delta
from maistro.extensions.compatibility import CompatibilityPolicy, evaluate_compatibility
from maistro.extensions.manifest import (
    assert_snapshot_intact,
    inspect_manifest,
    sha256_hex,
    verify_package_payload,
)
from maistro.extensions.preflight import PreflightReport, rollback_preflight, upgrade_preflight
from maistro.extensions.store import ExtensionStore
from maistro.extensions.trust import TrustPolicy, evaluate_trust
from maistro.extensions.types import (
    INSPECT_SKIP_STATES,
    REMOVABLE_STATES,
    TRANSITIONS,
    ArtifactMismatch,
    ExtensionInstallRecord,
    ExtensionLifecycleError,
    ExtensionPackage,
    ExtensionScope,
    ExtensionState,
    ExtensionTransition,
    InspectionConflict,
    InvalidTransition,
    PinConflict,
    PinEvent,
    PinRecord,
    PreflightError,
    RemovalNote,
    TrustEvidence,
    UnknownInstall,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _mark_superseded(detail: str) -> Callable[[ExtensionInstallRecord], ExtensionInstallRecord]:
    """A transition mutate carrying the supersede reason on the record."""

    def mark(record: ExtensionInstallRecord) -> ExtensionInstallRecord:
        return replace(record, status_reason=detail)

    return mark


#: States whose records must carry the reason on the record itself, so the
#: durable answer to "why is this not active" survives next to the state.
_FAILURE_STATES = frozenset(
    {
        ExtensionState.REJECTED,
        ExtensionState.DENIED,
        ExtensionState.ABANDONED,
        ExtensionState.FAILED,
    }
)


class LoadedExtension:
    """What a host loader produced for an activated install.

    A plain class rather than a frozen dataclass on purpose: hosts subclass or
    replace it with richer runtime handles; the service only reads the
    identity fields to verify the loader loaded *this* extension.
    """

    def __init__(self, extension_id: str, version: str) -> None:
        self.extension_id = extension_id
        self.version = version


class ExtensionCodeLoader(Protocol):
    """Host-implemented seam for the only code-execution step.

    The service calls :meth:`load` in exactly one place — the install phase,
    after authorization — and never during inspection or authorization.
    """

    async def load(self, record: ExtensionInstallRecord, payload: bytes) -> LoadedExtension: ...


class UnwiredExtensionLoader(ExtensionCodeLoader):
    """Fail-closed default loader for deployments without an activation substrate.

    Installing through it always fails, after the record has truthfully moved
    to ``FAILED``: a platform that cannot activate extensions must say so at
    the activation step, not improvise an import at authorization time.
    """

    async def load(self, record: ExtensionInstallRecord, payload: bytes) -> LoadedExtension:
        raise NotImplementedError(
            f"no activation loader is wired for {record.extension_id} "
            f"{record.version}; extension code cannot run without one"
        )


class OwnedResourceJanitor(Protocol):
    """Host-implemented cleanup seam for removal (#954).

    Removal revokes authority and drops the active pointer itself; what it
    may *also* delete is the extension's owned operational resources — the
    data, caches and side channels the host let it create. The janitor names
    what it purged so the cleanup is auditable; it is called strictly after
    the REMOVED transition is durable, so a crashing janitor can delay
    cleanup but never preserve authority, and its failures are recorded, not
    raised. Janitors must be idempotent: ``remove`` retries re-run them.
    """

    async def purge(self, record: ExtensionInstallRecord) -> tuple[str, ...]: ...


class RetainAllJanitor:
    """The default cleanup policy: purge nothing, retain all history.

    Canonical historical evidence is never extension-owned, so the safe
    default deletes nothing. Deployments with real owned resources wire a
    janitor that enumerates exactly what it removes.
    """

    async def purge(self, record: ExtensionInstallRecord) -> tuple[str, ...]:
        del record
        return ()


class ExtensionInstallService:
    """Governed extension installation: inspect → authorize → install."""

    def __init__(
        self,
        store: ExtensionStore,
        *,
        loader: ExtensionCodeLoader,
        trust_policy: TrustPolicy | None = None,
        platform_api_version: str = "1.0.0",
        pre_approved_permissions: frozenset[str] = frozenset(),
        authorization_ttl: timedelta = timedelta(minutes=15),
        clock: Callable[[], datetime] = _utc_now,
        install_id_factory: Callable[[], str] | None = None,
        owned_resource_janitor: OwnedResourceJanitor | None = None,
    ) -> None:
        self._store = store
        self._loader = loader
        self._trust_policy = trust_policy or TrustPolicy()
        self._platform_api_version = platform_api_version
        self._pre_approved = pre_approved_permissions
        self._ttl = authorization_ttl
        self._clock = clock
        self._install_id_factory = install_id_factory or (lambda: uuid.uuid4().hex)
        self._janitor = owned_resource_janitor
        self._locks: dict[str, asyncio.Lock] = {}
        self._extension_locks: dict[str, asyncio.Lock] = {}

    # -- reads ------------------------------------------------------------

    async def get(self, install_id: str, *, scope: ExtensionScope) -> ExtensionInstallRecord:
        """Return one install record, refusing ids outside ``scope``."""
        return await self._require(install_id, scope)

    async def active(
        self, scope: ExtensionScope, extension_id: str
    ) -> ExtensionInstallRecord | None:
        """The currently active record for an extension in the scope, if any."""
        return await self._store.active_record(scope, extension_id)

    async def transitions(
        self, install_id: str, *, scope: ExtensionScope
    ) -> tuple[ExtensionTransition, ...]:
        """The audited transition trail for one install (scope-checked)."""
        await self._require(install_id, scope)
        return await self._store.transitions_for(install_id)

    async def permissions_in_snapshot(self, record: ExtensionInstallRecord) -> tuple[str, ...]:
        """Display the requested permissions from the immutable snapshot.

        The snapshot's bytes are re-verified against the digest anchored at
        inspection before anything is shown: a corrupted or swapped snapshot
        fails loudly instead of displaying permissions nobody approved.
        """
        assert_snapshot_intact(record.manifest)
        return record.requested_permissions

    # -- phase 1: inspect ---------------------------------------------------

    async def inspect(
        self,
        *,
        actor: str,
        scope: ExtensionScope,
        package: ExtensionPackage,
        trust_evidence: TrustEvidence,
    ) -> ExtensionInstallRecord:
        """Inspect a candidate and park it for explicit authorization.

        Parsing the manifest is pure byte handling. Compat, trust and
        authority are pure evaluations. Nothing here can import or execute
        extension code — the loader is not reachable from this method.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")

        manifest = inspect_manifest(package.manifest_bytes)
        existing = await self._store.latest_record(scope, manifest.extension_id, manifest.version)
        if existing is not None and existing.state not in INSPECT_SKIP_STATES:
            same_manifest = existing.manifest.source_sha256 == manifest.source_sha256
            same_artifact = existing.artifact_sha256 == manifest.artifact_sha256
            if same_manifest and same_artifact:
                # Idempotent re-inspection: one authorization track per
                # (scope, extension, version), never a fork.
                return existing
            raise InspectionConflict(
                f"an install record for {manifest.extension_id} {manifest.version} "
                f"is already {existing.state} in {scope.describe} with different bytes; "
                "a candidate may not change under an open authorization request"
            )

        now = self._clock()
        record = ExtensionInstallRecord(
            install_id=self._install_id_factory(),
            org_id=scope.org_id,
            workspace_id=scope.workspace_id,
            extension_id=manifest.extension_id,
            version=manifest.version,
            manifest=manifest,
            state=ExtensionState.INSPECTING,
            requested_permissions=manifest.permissions,
            artifact_sha256=manifest.artifact_sha256,
            requested_by=actor,
            created_at=now,
            updated_at=now,
        )

        try:
            verify_package_payload(manifest, package.payload)
        except ExtensionLifecycleError as exc:
            return await self._transition(
                record,
                ExtensionState.REJECTED,
                actor=actor,
                reason=f"rejected at inspection: {exc}",
                now=now,
            )

        compatibility = evaluate_compatibility(
            manifest,
            CompatibilityPolicy(
                platform_api_version=self._platform_api_version,
                installed_versions=await self._store.installed_versions(scope),
            ),
        )
        trust = evaluate_trust(manifest, trust_evidence, self._trust_policy)
        failures = (*compatibility.failures, *trust.failures)
        if not (compatibility.compatible and trust.trusted):
            return await self._transition(
                record,
                ExtensionState.REJECTED,
                actor=actor,
                reason="rejected at inspection: " + "; ".join(failures),
                now=now,
            )

        active = await self._store.active_record(scope, manifest.extension_id)
        baseline = AuthorityBaseline(
            previously_granted=frozenset(active.granted_permissions) if active else frozenset(),
            pre_approved=self._pre_approved,
        )
        delta = compute_authority_delta(manifest.permissions, baseline)
        record = replace(record, authority_delta=delta.new)

        return await self._transition(
            record,
            ExtensionState.AWAITING_AUTHORIZATION,
            actor=actor,
            reason=(
                f"inspection passed for {manifest.extension_id} {manifest.version}; "
                f"authority delta: {len(delta.new)} new permission(s), "
                f"{len(delta.retained)} retained; "
                + (
                    "delta requests authority beyond the baseline"
                    if delta.requires_authorization
                    else "delta adds nothing beyond the baseline; explicit decision still required"
                )
            ),
            now=now,
            mutate=lambda r: replace(r, expires_at=now + self._ttl),
        )

    # -- phase 2: authorize -------------------------------------------------

    async def authorize(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        approve: bool,
        reason: str,
    ) -> ExtensionInstallRecord:
        """Apply an explicit operator/organization authorization decision.

        Only a record sitting in ``AWAITING_AUTHORIZATION`` can be decided. An
        expired request becomes ``ABANDONED`` instead — a late approval is not
        an approval. Denial is terminal and leaves no active extension.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: an authorization decision without a "
                "recorded reason is not auditable evidence"
            )

        record = await self._require(install_id, scope)
        now = self._clock()

        if record.state is ExtensionState.AWAITING_AUTHORIZATION:
            expires_at = record.expires_at
            if expires_at is not None and now >= expires_at:
                await self._transition(
                    record,
                    ExtensionState.ABANDONED,
                    actor=actor,
                    reason=f"authorization window elapsed at {expires_at.isoformat()}; "
                    "late decision not applied",
                    now=now,
                )
                raise InvalidTransition(
                    f"authorization request {install_id} expired; record is ABANDONED"
                )

        if record.state is not ExtensionState.AWAITING_AUTHORIZATION:
            raise InvalidTransition(
                f"install {install_id} is {record.state}; only "
                f"{ExtensionState.AWAITING_AUTHORIZATION} records can be decided"
            )

        if not approve:
            return await self._transition(
                record,
                ExtensionState.DENIED,
                actor=actor,
                reason=f"denied: {reason}",
                now=now,
            )

        # The grant is frozen from the immutable snapshot, never from a
        # mutable copy: verify the bytes still hash to the inspected digest.
        assert_snapshot_intact(record.manifest)
        return await self._transition(
            record,
            ExtensionState.AUTHORIZED,
            actor=actor,
            reason=f"authorized: {reason}",
            now=now,
            mutate=lambda r: replace(
                r,
                granted_permissions=r.requested_permissions,
                authorized_by=actor,
            ),
        )

    # -- phase 3: install + activate -----------------------------------------

    async def install(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        payload: bytes,
    ) -> ExtensionInstallRecord:
        """Install the authorized artifact and activate it.

        Returns only truthful terminal answers: ``ACTIVE`` (activated, active
        pointer swapped once) or ``FAILED`` (recorded with the reason; nothing
        active). Raises ``ArtifactMismatch`` without recording a transition
        when the presented payload is not the inspected artifact — a payload
        that fails the digest check never happened to the machine.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        async with self._lock(install_id):
            return await self._install_locked(install_id, actor=actor, scope=scope, payload=payload)

    async def _install_locked(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        payload: bytes,
    ) -> ExtensionInstallRecord:
        record = await self._require(install_id, scope)
        payload_digest = sha256_hex(payload)

        if record.state is ExtensionState.ACTIVE:
            if record.artifact_sha256 == payload_digest:
                # Idempotent retry: the install already happened. No duplicate
                # record, no new activation, no authority change.
                return record
            raise ArtifactMismatch(
                f"install {install_id} is ACTIVE with artifact "
                f"{record.artifact_sha256}; refusing to swap in {payload_digest}"
            )

        if record.state not in (ExtensionState.AUTHORIZED, ExtensionState.FAILED):
            raise InvalidTransition(
                f"install {install_id} is {record.state}; only "
                f"{ExtensionState.AUTHORIZED} or recoverable {ExtensionState.FAILED} "
                "records can be installed"
            )

        if record.artifact_sha256 != payload_digest:
            raise ArtifactMismatch(
                f"payload digest {payload_digest} does not match the artifact bound at "
                f"inspection ({record.artifact_sha256}); authorization does not transfer"
            )

        return await self._activate_locked(
            record,
            actor=actor,
            payload=payload,
            purpose=f"installing authorized artifact {payload_digest}",
        )

    async def _activate_locked(
        self,
        record: ExtensionInstallRecord,
        *,
        actor: str,
        payload: bytes,
        purpose: str,
    ) -> ExtensionInstallRecord:
        """The shared checked-activation path: INSTALLING → loader → ACTIVE.

        Every way code starts running — first install (#953), upgrade
        activation, rollback re-activation, resume after disable (#954) —
        funnels through here, so the loader seam, the attempt counter, the
        identity check and the truthful FAILED recording have exactly one
        implementation. Callers validate the pre-state and the payload
        digest; this method owns the rest.
        """
        record = await self._transition(
            record,
            ExtensionState.INSTALLING,
            actor=actor,
            reason=purpose,
            now=self._clock(),
            mutate=lambda r: replace(
                r, install_attempts=r.install_attempts + 1, installed_by=actor
            ),
        )

        try:
            loaded = await self._loader.load(record, payload)
        except Exception as exc:
            await self._transition(
                record,
                ExtensionState.FAILED,
                actor=actor,
                reason=f"activation failed: {exc}",
                now=self._clock(),
            )
            raise ExtensionLifecycleError(
                f"install {record.install_id} failed during activation and is recorded FAILED"
            ) from exc

        if loaded.extension_id != record.extension_id or loaded.version != record.version:
            await self._transition(
                record,
                ExtensionState.FAILED,
                actor=actor,
                reason=(
                    f"activation failed: loader returned {loaded.extension_id} "
                    f"{loaded.version} instead of {record.extension_id} {record.version}"
                ),
                now=self._clock(),
            )
            raise ExtensionLifecycleError(
                f"install {record.install_id} failed: loader identity mismatch; recorded FAILED"
            )

        record = await self._transition(
            record,
            ExtensionState.ACTIVE,
            actor=actor,
            reason=f"activated {record.extension_id} {record.version}",
            now=self._clock(),
        )
        await self._store.set_active(record)
        return record

    # -- B3: post-install lifecycle (#954) -----------------------------------

    async def resolve(
        self, scope: ExtensionScope, extension_id: str
    ) -> ExtensionInstallRecord | None:
        """The record an invocation of this extension would load, if any.

        This is the seam invocation paths must consult: it returns the
        scope's pointed-at record only while that record is ``ACTIVE``. A
        disabled, superseded or removed extension resolves to ``None``
        immediately — the pointer is dropped in the same operation that
        changes the state, and the state check here is defense in depth for
        a crash between the two.
        """
        record = await self._store.active_record(scope, extension_id)
        if record is None or record.state is not ExtensionState.ACTIVE:
            return None
        return record

    async def pin(
        self,
        scope: ExtensionScope,
        extension_id: str,
        *,
        actor: str,
        version: str | None = None,
        reason: str,
    ) -> PinRecord:
        """Hold the extension at a version against version changes.

        Pins the extension's currently-ACTIVE version (``version`` may name
        it explicitly; naming anything else is refused). Re-pinning the
        pinned version refreshes the pin (actor/reason/time); pinning a
        different version requires :meth:`unpin` first — a pin that a second
        call could silently move would hold nothing. Every pin operation is
        audited in the store's pin-event trail.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError("reason is required: a pin without a recorded reason is not auditable")
        async with self._extension_lock(scope, extension_id):
            active = await self._store.active_record(scope, extension_id)
            if active is None or active.state is not ExtensionState.ACTIVE:
                raise PreflightError(
                    f"no ACTIVE install of {extension_id} in {scope.describe}; "
                    "only an active version can be pinned"
                )
            target = version if version is not None else active.version
            if target != active.version:
                raise PreflightError(
                    f"cannot pin {extension_id} at {target}: the active version is "
                    f"{active.version}; activate that version first"
                )
            existing = await self._store.get_pin(scope, extension_id)
            if existing is not None and existing.version != target:
                raise PinConflict(
                    f"{extension_id} is pinned at {existing.version} in {scope.describe}; "
                    f"unpin before pinning {target}"
                )
            now = self._clock()
            pin = PinRecord(
                org_id=scope.org_id,
                workspace_id=scope.workspace_id,
                extension_id=extension_id,
                version=target,
                pinned_by=actor,
                reason=reason,
                pinned_at=now,
            )
            await self._store.set_pin(pin)
            await self._store.append_pin_event(
                PinEvent(
                    seq=await self._store.next_seq(),
                    at=now,
                    org_id=scope.org_id,
                    workspace_id=scope.workspace_id,
                    extension_id=extension_id,
                    action="refresh" if existing is not None else "pin",
                    version=target,
                    actor=actor,
                    reason=reason,
                )
            )
            return pin

    async def unpin(
        self,
        scope: ExtensionScope,
        extension_id: str,
        *,
        actor: str,
        reason: str,
    ) -> bool:
        """Release the version pin. Idempotent: unpinning an unpinned
        extension is a no-op returning ``False``. The release is audited."""
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: releasing a pin without a recorded reason is not auditable"
            )
        async with self._extension_lock(scope, extension_id):
            existed = await self._store.clear_pin(scope, extension_id)
            if existed:
                await self._store.append_pin_event(
                    PinEvent(
                        seq=await self._store.next_seq(),
                        at=self._clock(),
                        org_id=scope.org_id,
                        workspace_id=scope.workspace_id,
                        extension_id=extension_id,
                        action="unpin",
                        version=None,
                        actor=actor,
                        reason=reason,
                    )
                )
            return existed

    async def pin_status(
        self, scope: ExtensionScope, extension_id: str
    ) -> tuple[PinRecord | None, tuple[PinEvent, ...]]:
        """The scope's current pin and its audited event trail."""
        return (
            await self._store.get_pin(scope, extension_id),
            await self._store.pin_events(scope, extension_id),
        )

    async def upgrade(
        self,
        *,
        actor: str,
        scope: ExtensionScope,
        package: ExtensionPackage,
        trust_evidence: TrustEvidence,
    ) -> tuple[ExtensionInstallRecord, PreflightReport]:
        """Begin a version upgrade: preflight, then the governed inspect.

        Returns ``(record, report)`` where ``record`` is the candidate's
        install record in ``AWAITING_AUTHORIZATION`` — the operator's
        explicit :meth:`authorize` decision is required before anything
        activates, and the record's ``authority_delta`` names exactly which
        permissions are new against the active grant. A byte-identical
        re-request of the active version returns the active record untouched
        (idempotent). A refused preflight raises before any state changes.

        The loader is not reachable from this method; activation happens in
        :meth:`activate_upgrade` after authorization.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        manifest = inspect_manifest(package.manifest_bytes)
        async with self._extension_lock(scope, manifest.extension_id):
            await self.reconcile(scope=scope, extension_id=manifest.extension_id)
            active = await self._store.active_record(scope, manifest.extension_id)
            if active is None or active.state is not ExtensionState.ACTIVE:
                raise PreflightError(
                    f"no ACTIVE install of {manifest.extension_id} in {scope.describe}; "
                    "upgrades replace an active version — use the install flow for "
                    "a first install"
                )
            pin = await self._store.get_pin(scope, manifest.extension_id)
            installed = await self._store.installed_versions(scope)
            report = upgrade_preflight(
                active=active,
                candidate_version=manifest.version,
                candidate_source_sha256=manifest.source_sha256,
                candidate_permissions=manifest.permissions,
                pin=pin,
                installed_versions=installed,
                platform_api_version=self._platform_api_version,
                pre_approved=self._pre_approved,
            )
            if not report.allowed:
                pin_failed = any(
                    check.name == "pin" and not check.passed for check in report.checks
                )
                if pin_failed:
                    raise PinConflict("; ".join(report.failures))
                raise PreflightError("upgrade preflight refused: " + "; ".join(report.failures))
            if active.version == manifest.version:
                # Byte-identical re-request of the active version.
                return active, report
            record = await self.inspect(
                actor=actor,
                scope=scope,
                package=package,
                trust_evidence=trust_evidence,
            )
            return record, report

    async def activate_upgrade(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        payload: bytes,
    ) -> ExtensionInstallRecord:
        """Activate an authorized upgrade and retire the previous version.

        The authorized record installs through the shared activation path
        (digest re-check, loader, identity check); once the new version is
        ACTIVE and the pointer has swapped, every other ACTIVE record of the
        same extension is superseded — retained verbatim, rollback-eligible.
        A crash between the swap and the supersede leaves the old record
        ACTIVE-but-unpointed, which :meth:`reconcile` repairs; no window
        serves two versions.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        record = await self._require(install_id, scope)
        async with self._extension_lock(scope, record.extension_id):
            await self.reconcile(scope=scope, extension_id=record.extension_id)
            record = await self._require(install_id, scope)
            payload_digest = sha256_hex(payload)

            if record.state is ExtensionState.ACTIVE:
                if record.artifact_sha256 == payload_digest:
                    # Idempotent retry of a completed upgrade.
                    await self._supersede_others(record, actor=actor)
                    return record
                raise ArtifactMismatch(
                    f"upgrade {install_id} is ACTIVE with artifact "
                    f"{record.artifact_sha256}; refusing to swap in {payload_digest}"
                )
            if record.state not in (ExtensionState.AUTHORIZED, ExtensionState.FAILED):
                raise InvalidTransition(
                    f"upgrade {install_id} is {record.state}; only an "
                    f"{ExtensionState.AUTHORIZED} (or recoverable {ExtensionState.FAILED}) "
                    "upgrade record can be activated"
                )
            if record.artifact_sha256 != payload_digest:
                raise ArtifactMismatch(
                    f"payload digest {payload_digest} does not match the artifact bound at "
                    f"inspection ({record.artifact_sha256}); authorization does not transfer"
                )

            record = await self._activate_locked(
                record,
                actor=actor,
                payload=payload,
                purpose=f"upgrade activation of {record.extension_id} {record.version}",
            )
            await self._supersede_others(
                record,
                actor=actor,
                reason=f"superseded by upgrade to {record.version}",
            )
            return record

    async def rollback(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        payload: bytes,
        reason: str,
        allow_broadened: bool = False,
    ) -> ExtensionInstallRecord:
        """Restore a superseded version as the active one.

        The preflight must prove the move safe before anything changes: the
        target is SUPERSEDED and carries its frozen grant, the pin (if any)
        names the target version, compatibility holds against the scope as
        the rollback leaves it, and the presented payload is exactly the
        artifact the record binds. Restoring permissions the current version
        had already dropped is a genuine authority change and is refused
        unless ``allow_broadened`` acknowledges it explicitly — a rollback
        never silently resurrects authority. Every refusal happens before the
        first state change, so a failed rollback cannot corrupt the current
        state.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: a rollback without a recorded reason is not auditable"
            )
        record = await self._require(install_id, scope)
        async with self._extension_lock(scope, record.extension_id):
            await self.reconcile(scope=scope, extension_id=record.extension_id)
            record = await self._require(install_id, scope)
            current = await self._store.active_record(scope, record.extension_id)
            if current is not None and current.install_id == record.install_id:
                # Already the active version; rollback is done (idempotent).
                return record

            pin = await self._store.get_pin(scope, record.extension_id)
            installed = await self._store.installed_versions(scope)
            report = rollback_preflight(
                target=record,
                current=current,
                pin=pin,
                installed_versions=installed,
                platform_api_version=self._platform_api_version,
                pre_approved=self._pre_approved,
            )
            if not report.allowed:
                pin_failed = any(
                    check.name == "pin" and not check.passed for check in report.checks
                )
                if pin_failed:
                    raise PinConflict("; ".join(report.failures))
                raise PreflightError("rollback preflight refused: " + "; ".join(report.failures))
            if report.broadens_authority and not allow_broadened:
                raise PreflightError(
                    "rollback would restore permissions not currently granted ("
                    + ", ".join(report.authority.new)
                    + "); pass allow_broadened to accept the restored authority explicitly"
                )
            payload_digest = sha256_hex(payload)
            if record.artifact_sha256 != payload_digest:
                raise ArtifactMismatch(
                    f"payload digest {payload_digest} does not match the artifact bound for "
                    f"{record.version} ({record.artifact_sha256}); rollback refuses "
                    "substituted bytes"
                )

            restored = ", ".join(record.granted_permissions) or "none"
            record = await self._activate_locked(
                record,
                actor=actor,
                payload=payload,
                purpose=(
                    f"rollback from {report.from_version} to {record.version} "
                    f"(restored grant: {restored})"
                ),
            )
            if current is not None and current.state is ExtensionState.ACTIVE:
                await self._transition(
                    current,
                    ExtensionState.SUPERSEDED,
                    actor=actor,
                    reason=f"rolled back to {record.version}: {reason}",
                    now=self._clock(),
                    mutate=lambda r: replace(
                        r, status_reason=f"rolled back to {record.version}: {reason}"
                    ),
                )
            return record

    async def disable(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        reason: str,
    ) -> ExtensionInstallRecord:
        """Suspend the active extension: invocation resolution stops now.

        The record moves to ``DISABLED`` and the scope's active pointer is
        dropped in the same operation, so :meth:`resolve` returns ``None``
        from this point on. The record, its frozen grant and its audit trail
        are retained verbatim; :meth:`resume` re-activates the same bound
        artifact without a new authorization (the grant never lapsed).
        Idempotent: disabling a DISABLED record returns it unchanged.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: a disable without a recorded reason is not auditable"
            )
        record = await self._require(install_id, scope)
        async with self._extension_lock(scope, record.extension_id):
            record = await self._require(install_id, scope)
            if record.state is ExtensionState.DISABLED:
                return record
            if record.state is not ExtensionState.ACTIVE:
                raise InvalidTransition(
                    f"disable {install_id} is {record.state}; only an "
                    f"{ExtensionState.ACTIVE} record can be disabled"
                )
            updated = await self._transition(
                record,
                ExtensionState.DISABLED,
                actor=actor,
                reason=f"disabled: {reason}",
                now=self._clock(),
                mutate=lambda r: replace(r, status_reason=reason),
            )
            pointer = await self._store.active_record(scope, updated.extension_id)
            if pointer is not None and pointer.install_id == updated.install_id:
                await self._store.clear_active(scope, updated.extension_id)
            return updated

    async def resume(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        payload: bytes,
    ) -> ExtensionInstallRecord:
        """Re-activate a disabled extension from its bound artifact.

        The frozen grant stands — disable suspended resolution, it never
        revoked authorization — so no new decision is required; the payload
        must still be the exact bound artifact, and activation goes through
        the shared loader path. Idempotent for an already-ACTIVE record
        carrying the same artifact.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        record = await self._require(install_id, scope)
        async with self._extension_lock(scope, record.extension_id):
            record = await self._require(install_id, scope)
            payload_digest = sha256_hex(payload)
            if record.state is ExtensionState.ACTIVE:
                if record.artifact_sha256 == payload_digest:
                    return record
                raise ArtifactMismatch(
                    f"resume {install_id} is ACTIVE with artifact "
                    f"{record.artifact_sha256}; refusing to swap in {payload_digest}"
                )
            if record.state is not ExtensionState.DISABLED:
                raise InvalidTransition(
                    f"resume {install_id} is {record.state}; only a "
                    f"{ExtensionState.DISABLED} record can be resumed"
                )
            if record.artifact_sha256 != payload_digest:
                raise ArtifactMismatch(
                    f"payload digest {payload_digest} does not match the artifact bound for "
                    f"{record.version} ({record.artifact_sha256}); the grant stands only "
                    "for the authorized bytes"
                )
            return await self._activate_locked(
                record,
                actor=actor,
                payload=payload,
                purpose=f"resume of {record.extension_id} {record.version} (grant unchanged)",
            )

    async def remove(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        reason: str,
        janitor: OwnedResourceJanitor | None = None,
    ) -> ExtensionInstallRecord:
        """Uninstall: authority ends, canonical evidence is retained.

        The record moves to terminal ``REMOVED`` and, if it was the active
        one, the scope's pointer is dropped. The record and its transition
        trail are never deleted — they are the historical evidence that the
        extension ran here. Owned *operational* resources go through the
        janitor (the service's default or a per-call override), strictly
        after the transition is durable, with the purge reported as an
        audited :class:`RemovalNote`; janitor failures are recorded, never
        raised, and never resurrect authority. Idempotent: removing a
        REMOVED record re-runs a provided janitor (the retry path for a
        crashed cleanup) and returns the record.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: a removal without a recorded reason is not auditable"
            )
        chosen_janitor = janitor if janitor is not None else self._janitor
        record = await self._require(install_id, scope)
        async with self._extension_lock(scope, record.extension_id):
            record = await self._require(install_id, scope)
            if record.state is ExtensionState.REMOVED:
                await self._purge_and_note(record, actor=actor, janitor=chosen_janitor)
                return record
            if record.state not in REMOVABLE_STATES:
                raise InvalidTransition(
                    f"remove {install_id} is {record.state}; records in "
                    f"{sorted(state.value for state in REMOVABLE_STATES)} can be removed"
                )
            updated = await self._transition(
                record,
                ExtensionState.REMOVED,
                actor=actor,
                reason=f"removed: {reason}",
                now=self._clock(),
                mutate=lambda r: replace(r, status_reason=reason),
            )
            pointer = await self._store.active_record(scope, updated.extension_id)
            if pointer is not None and pointer.install_id == updated.install_id:
                await self._store.clear_active(scope, updated.extension_id)
            await self._purge_and_note(updated, actor=actor, janitor=chosen_janitor)
            return updated

    async def removal_history(
        self, install_id: str, *, scope: ExtensionScope
    ) -> tuple[RemovalNote, ...]:
        """The audited cleanup reports for one removal (scope-checked)."""
        await self._require(install_id, scope)
        return await self._store.removal_notes_for(install_id)

    async def reconcile(
        self, *, scope: ExtensionScope, extension_id: str
    ) -> tuple[ExtensionInstallRecord, ...]:
        """Repair the pointer/state invariants a crash can leave behind.

        Two windows exist by construction — the pointer swap and the state
        transitions of an upgrade/rollback are separate durable steps:

        - a record ACTIVE without the scope's pointer (crash between
          activation and supersede) is superseded — it must never be
          servable again, because the pointer names its replacement;
        - a pointer to a record that is no longer ACTIVE (crash between a
          disable/remove transition and the pointer drop) is cleared.

        Both repairs are themselves audited transitions, so the trail shows
        the machine healing. Every lifecycle operation runs this first, and
        the maintenance sweep exposes it to operators.
        """
        repaired: list[ExtensionInstallRecord] = []
        pointer = await self._store.active_record(scope, extension_id)
        if pointer is not None and pointer.state is not ExtensionState.ACTIVE:
            await self._store.clear_active(scope, extension_id)
            repaired.append(pointer)
        for record in await self._store.records_in_state(ExtensionState.ACTIVE):
            if (
                record.org_id != scope.org_id
                or record.workspace_id != scope.workspace_id
                or record.extension_id != extension_id
            ):
                continue
            if pointer is not None and record.install_id == pointer.install_id:
                continue
            updated = await self._transition(
                record,
                ExtensionState.SUPERSEDED,
                actor="system:reconciliation",
                reason="reconciled: ACTIVE without the scope pointer (crash recovery)",
                now=self._clock(),
                mutate=lambda r: replace(r, status_reason="superseded by crash reconciliation"),
            )
            repaired.append(updated)
        return tuple(repaired)

    # -- maintenance ---------------------------------------------------------

    async def expire_abandoned(self, *, now: datetime | None = None) -> int:
        """Move every expired authorization request to ``ABANDONED``.

        The lazy check in :meth:`authorize` is defense in depth; this sweep is
        the durable guarantee that abandoned requests do not linger
        authorized-adjacent. Denied or abandoned records never reach ACTIVE.
        """
        moment = now or self._clock()
        expired = 0
        for record in await self._store.records_in_state(ExtensionState.AWAITING_AUTHORIZATION):
            if record.expires_at is not None and moment >= record.expires_at:
                await self._transition(
                    record,
                    ExtensionState.ABANDONED,
                    actor="system:expiry-sweep",
                    reason=f"authorization window elapsed at {record.expires_at.isoformat()}",
                    now=moment,
                )
                expired += 1
        return expired

    # -- internals -----------------------------------------------------------

    def _lock(self, install_id: str) -> asyncio.Lock:
        # No await between the check and the set, so lazy creation is safe
        # under a single event loop.
        lock = self._locks.get(install_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[install_id] = lock
        return lock

    def _extension_lock(self, scope: ExtensionScope, extension_id: str) -> asyncio.Lock:
        """Serialize lifecycle operations on one (scope, extension).

        Upgrades and rollbacks move several records under one pointer; a
        second operator's operation interleaving mid-swap would observe
        half-finished invariants. Lazy creation is safe under a single event
        loop (no await between check and set).
        """
        key = f"{scope.org_id}/{scope.workspace_id}/{extension_id}"
        lock = self._extension_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._extension_locks[key] = lock
        return lock

    async def _supersede_others(
        self,
        activated: ExtensionInstallRecord,
        *,
        actor: str,
        reason: str | None = None,
    ) -> tuple[ExtensionInstallRecord, ...]:
        """Retire every other ACTIVE record of this (scope, extension).

        After an upgrade activation the pointer names the new version; any
        still-ACTIVE predecessor is superseded (retained, rollback-eligible).
        Crash-window leftovers are also healed here, mirroring reconcile.
        """
        superseded: list[ExtensionInstallRecord] = []
        for record in await self._store.records_in_state(ExtensionState.ACTIVE):
            if (
                record.org_id != activated.org_id
                or record.workspace_id != activated.workspace_id
                or record.extension_id != activated.extension_id
                or record.install_id == activated.install_id
            ):
                continue
            detail = reason or f"superseded by {activated.version}"
            superseded.append(
                await self._transition(
                    record,
                    ExtensionState.SUPERSEDED,
                    actor=actor,
                    reason=detail,
                    now=self._clock(),
                    mutate=_mark_superseded(detail),
                )
            )
        return tuple(superseded)

    async def _purge_and_note(
        self,
        record: ExtensionInstallRecord,
        *,
        actor: str,
        janitor: OwnedResourceJanitor | None,
    ) -> RemovalNote | None:
        """Run the cleanup policy and append its audited report.

        Contained by construction: the REMOVED transition is already durable,
        so a janitor crash delays cleanup but cannot preserve authority, and
        the failure lands in the note rather than the caller's face. No
        janitor (the retain-everything default) yields no note.
        """
        if janitor is None:
            return None
        purged: tuple[str, ...] = ()
        failed: tuple[str, ...] = ()
        try:
            purged = await janitor.purge(record)
        except Exception as exc:
            failed = (f"cleanup failed: {exc}",)
        note = RemovalNote(
            seq=await self._store.next_seq(),
            at=self._clock(),
            install_id=record.install_id,
            org_id=record.org_id,
            workspace_id=record.workspace_id,
            extension_id=record.extension_id,
            version=record.version,
            actor=actor,
            purged=purged,
            failed=failed,
        )
        await self._store.append_removal_note(note)
        return note

    async def _require(self, install_id: str, scope: ExtensionScope) -> ExtensionInstallRecord:
        record = await self._store.get_record(install_id)
        if (
            record is None
            or record.org_id != scope.org_id
            or record.workspace_id != scope.workspace_id
        ):
            raise UnknownInstall(f"no install record {install_id!r} in {scope.describe}")
        return record

    async def _transition(
        self,
        record: ExtensionInstallRecord,
        to_state: ExtensionState,
        *,
        actor: str,
        reason: str,
        now: datetime,
        mutate: Callable[[ExtensionInstallRecord], ExtensionInstallRecord] | None = None,
    ) -> ExtensionInstallRecord:
        if to_state not in TRANSITIONS[record.state]:
            raise InvalidTransition(
                f"illegal transition {record.state} -> {to_state} for "
                f"{record.extension_id} {record.version}"
            )
        updated = (mutate or (lambda r: r))(record)
        # Failure-shaped states carry their reason on the record itself, so
        # the durable answer to "why is this not active" survives next to the
        # state, not only in the audit trail.
        failure_reason = reason if to_state in _FAILURE_STATES else record.failure_reason
        updated = replace(updated, state=to_state, updated_at=now, failure_reason=failure_reason)
        await self._store.save_record(updated)
        await self._store.append_transition(
            ExtensionTransition(
                seq=await self._store.next_seq(),
                at=now,
                install_id=updated.install_id,
                org_id=updated.org_id,
                workspace_id=updated.workspace_id,
                extension_id=updated.extension_id,
                version=updated.version,
                actor=actor,
                from_state=record.state,
                to_state=to_state,
                reason=reason,
            )
        )
        return updated
