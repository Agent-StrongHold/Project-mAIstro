"""The inspect → authorize → install activation state machine (#953, M9-B2).

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
from maistro.extensions.store import ExtensionStore
from maistro.extensions.trust import TrustPolicy, evaluate_trust
from maistro.extensions.types import (
    TERMINAL_STATES,
    TRANSITIONS,
    ArtifactMismatch,
    ExtensionInstallRecord,
    ExtensionLifecycleError,
    ExtensionManifest,
    ExtensionPackage,
    ExtensionScope,
    ExtensionState,
    ExtensionTransition,
    InspectionConflict,
    InvalidTransition,
    TrustClaim,
    UnknownInstall,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


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
    ) -> None:
        self._store = store
        self._loader = loader
        self._trust_policy = trust_policy or TrustPolicy()
        self._platform_api_version = platform_api_version
        self._pre_approved = pre_approved_permissions
        self._ttl = authorization_ttl
        self._clock = clock
        self._install_id_factory = install_id_factory or (lambda: uuid.uuid4().hex)
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def store(self) -> ExtensionStore:
        """The canonical lifecycle store this service was built over.

        Read-only by design: composition roots that need to share the store
        (e.g. the health projection facade) must take it from the service,
        never hold a second reference that could drift from it.
        """
        return self._store

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

    async def _reinspection_outcome(
        self,
        scope: ExtensionScope,
        manifest: ExtensionManifest,
        existing: ExtensionInstallRecord | None,
    ) -> ExtensionInstallRecord | None:
        """Reconcile a re-inspection against an open record, if any.

        Returns the existing record when the candidate bytes are identical
        (idempotent re-inspection), raises ``InspectionConflict`` when the
        candidate changed under an open authorization request, and returns
        ``None`` when there is nothing to reconcile (no record, or a terminal
        one that no longer gates a new request).
        """
        if existing is None or existing.state in TERMINAL_STATES:
            return None
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

    async def inspect(
        self,
        *,
        actor: str,
        scope: ExtensionScope,
        package: ExtensionPackage,
        trust_evidence: TrustClaim,
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
        reinspection = await self._reinspection_outcome(scope, manifest, existing)
        if reinspection is not None:
            return reinspection

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
        now = self._clock()
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

        record = await self._transition(
            record,
            ExtensionState.INSTALLING,
            actor=actor,
            reason=f"installing authorized artifact {payload_digest}",
            now=now,
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
                f"install {install_id} failed during activation and is recorded FAILED"
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
                f"install {install_id} failed: loader identity mismatch; recorded FAILED"
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
