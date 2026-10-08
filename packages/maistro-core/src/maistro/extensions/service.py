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
   When the deployment supplies :class:`ExtensionAuthorityInputs` (#969),
   the freeze is instead the effective authority — the intersection of
   manifest, publisher trust, host policy, caller delegation and Workspace
   policy — and an empty intersection denies despite operator approval.
3. ``install`` re-verifies the presented payload against the digest bound at
   inspection, runs the host loader — the only code-execution seam, reachable
   only after authorization — and swaps the scope's active pointer once, after
   every check has passed. Failure is recorded truthfully (``FAILED`` with the
   reason) and the same bound artifact can be presented again to recover.
   Retries never duplicate install records and never widen the grant. A
   previously active version is marked ``SUPERSEDED`` after the pointer has
   moved, so exactly one record per (scope, extension) is ``ACTIVE``.
4. Post-install lifecycle (#954): ``disable`` stops new use while preserving
   the record, its frozen grant and its audit trail; ``enable`` re-serves a
   disabled version (no code execution — the artifact was already activated
   under its authorization); ``rollback`` moves the active version back to a
   previously authorized version; ``remove`` is terminal and preserves
   history; ``set_pinned`` holds the active version so upgrades and rollbacks
   cannot move it without an explicit unpin decision. None of these ever
   re-run the loader or widen a grant.

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
from maistro.extensions.effective_authority import (
    ExtensionAuthorityInputs,
    compute_effective_authority,
    resolve_publisher_trust,
)
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
    VersionPinned,
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
        authority_inputs: ExtensionAuthorityInputs | None = None,
        clock: Callable[[], datetime] = _utc_now,
        install_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._loader = loader
        self._trust_policy = trust_policy or TrustPolicy()
        self._platform_api_version = platform_api_version
        self._pre_approved = pre_approved_permissions
        self._ttl = authorization_ttl
        self._authority_inputs = authority_inputs
        self._clock = clock
        self._install_id_factory = install_id_factory or (lambda: uuid.uuid4().hex)
        self._locks: dict[str, asyncio.Lock] = {}
        self._activation_locks: dict[str, asyncio.Lock] = {}

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
            trust_evidence=trust_evidence,
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

        # #969: when the deployment supplies authority inputs, the grant is
        # frozen to the effective authority — the intersection of manifest,
        # publisher trust, host policy, caller delegation and Workspace
        # policy — never to the request alone.
        if self._authority_inputs is not None:
            return await self._authorize_with_effective_authority(
                record, actor=actor, reason=reason, now=now
            )

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

    async def _authorize_with_effective_authority(
        self,
        record: ExtensionInstallRecord,
        *,
        actor: str,
        reason: str,
        now: datetime,
    ) -> ExtensionInstallRecord:
        """Freeze the grant to the #969 effective-authority intersection.

        Operator approval cannot create authority the ceilings disallow: an
        empty intersection is a denial, and a partial one grants only the
        admitted subset, with every refusal explained on the transition
        trail alongside the decision digest.
        """
        inputs = self._authority_inputs
        assert inputs is not None  # the only caller checks this
        # The Workspace layer is only applicable to its own scope. A service
        # may hold records from several orgs/Workspaces; applying one scope's
        # enablement and ceiling to another's record would authorize an
        # extension in a scope whose policy never admitted it. A policy that
        # does not cover the record's scope is not an applicable ceiling, so
        # the request is denied before any authority is computed.
        record_scope = ExtensionScope(org_id=record.org_id, workspace_id=record.workspace_id)
        if inputs.workspace.scope != record_scope:
            return await self._transition(
                record,
                ExtensionState.DENIED,
                actor=actor,
                reason="denied: no Workspace extension policy covers "
                f"{record_scope.describe}; the wired policy is scoped to "
                f"{inputs.workspace.scope.describe} and a mismatched policy "
                "cannot authorize this record",
                now=now,
            )
        # Authorization re-evaluates trust against the evidence that admitted
        # *this* record at inspection, not the service-wide claim: when the
        # service handles packages from several publishers, each install must
        # stand on its own evidence. Records created before evidence was
        # persisted fall back to the deployment-wide claim.
        evidence = (
            record.trust_evidence if record.trust_evidence is not None else inputs.trust_claim
        )
        publisher_trust = resolve_publisher_trust(
            record.manifest,
            evidence,
            self._trust_policy,
            tier_of=inputs.tier_of,
            default_tier=inputs.default_tier,
        )
        authority = compute_effective_authority(
            record.manifest,
            trust=publisher_trust,
            host=inputs.host,
            caller=inputs.caller,
            workspace=inputs.workspace,
        )
        detail = (
            f"manifest {authority.manifest_sha256[:12]}…; decision "
            f"{authority.decision_digest[:12]}…"
        )
        # A package-level blocker (untrusted publisher; not enabled in the
        # Workspace) denies outright — including the degenerate manifest that
        # requests no permissions at all, where there are no per-permission
        # denials to explain but the extension still must not be authorized.
        if authority.granted_none:
            # Blockers alone cannot explain a trusted, enabled package that a
            # host/caller ceiling empties out: surface the per-permission
            # denials too, so the trail always says why authorization failed.
            denial_summary = "; ".join(
                f"{denial.permission} ({'; '.join(denial.reasons)})" for denial in authority.denials
            )
            return await self._transition(
                record,
                ExtensionState.DENIED,
                actor=actor,
                reason="denied: effective authority is empty; operator approval cannot "
                f"create authority policy disallows ({detail}; blockers: "
                f"{'; '.join(authority.blockers)}; denials: {denial_summary})",
                now=now,
                mutate=lambda r: replace(r, decision_digest=authority.decision_digest),
            )
        outcome = (
            "authorized with effective authority: granted "
            f"{len(authority.effective)} of {len(authority.requested)} requested "
            f"permission(s), reason: {reason} ({detail})"
        )
        if not authority.granted_all:
            denial_summary = "; ".join(
                f"{denial.permission} ({'; '.join(denial.reasons)})" for denial in authority.denials
            )
            outcome += f"; denied: {denial_summary}"
        return await self._transition(
            record,
            ExtensionState.AUTHORIZED,
            actor=actor,
            reason=outcome,
            now=now,
            mutate=lambda r: replace(
                r,
                granted_permissions=authority.effective,
                authorized_by=actor,
                decision_digest=authority.decision_digest,
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

        # Serialize the pin fence, the pointer swap and the supersede against
        # any other activation of the same (scope, extension): distinct
        # install-id record locks do not contend, so without this lock two
        # concurrent installs could each observe the same prior record, both
        # take the pointer, and each supersede only that shared prior —
        # leaving the loser ACTIVE under a pointer naming the winner.
        async with self._activation_lock(scope, record.extension_id):
            # #954: a pin on the currently active version fences moving the active
            # version to this candidate. The fence sits here — after the state and
            # digest checks, before any code runs — so a pinned scope is only
            # ever movable by an explicit unpin decision, never by presenting an
            # authorized payload out of band.
            pinned = await self._store.active_record(scope, record.extension_id)
            if pinned is not None and pinned.install_id != install_id and pinned.pinned:
                raise VersionPinned(
                    f"{record.extension_id} {pinned.version} is pinned in "
                    f"{scope.describe}; activating {record.version} is fenced "
                    "until the pin is lifted with an explicit unpin decision"
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
            prior = await self._store.active_record(scope, record.extension_id)
            await self._store.set_active(record)
            if (
                prior is not None
                and prior.install_id != record.install_id
                and prior.state is ExtensionState.ACTIVE
            ):
                # Pointer first (the atomic "what runs" swap), supersede second:
                # a crash between the two leaves the pointer naming the new
                # version with the old record still ACTIVE — the pre-#954
                # behavior — never a pointer naming a non-ACTIVE record.
                await self._transition(
                    prior,
                    ExtensionState.SUPERSEDED,
                    actor=actor,
                    reason=(
                        f"superseded by activation of {record.extension_id} "
                        f"{record.version} (install {record.install_id})"
                    ),
                    now=self._clock(),
                )
        return record

    # -- phase 4: post-install lifecycle (#954) ------------------------------

    async def disable(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        reason: str,
    ) -> ExtensionInstallRecord:
        """Stop an active extension's new use while preserving everything.

        The record keeps its frozen grant, its immutable manifest snapshot
        and its full audit trail; the scope's active pointer is dropped (iff
        it still names this record), so the extension stops being served
        immediately. Deactivation is not deletion: history stays queryable.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: a disable decision without a "
                "recorded reason is not auditable evidence"
            )
        async with self._lock(install_id):
            record = await self._require(install_id, scope)
            if record.state is not ExtensionState.ACTIVE:
                raise InvalidTransition(
                    f"install {install_id} is {record.state}; only an "
                    f"{ExtensionState.ACTIVE} record can be disabled"
                )
            updated = await self._transition(
                record,
                ExtensionState.DISABLED,
                actor=actor,
                reason=f"disabled: {reason}",
                now=self._clock(),
            )
            await self._store.clear_active(updated)
            return updated

    async def enable(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        reason: str,
    ) -> ExtensionInstallRecord:
        """Re-serve a disabled version under its existing frozen grant.

        No code executes: the artifact was already activated under this
        record's authorization, and re-enabling changes nothing about what is
        authorized. Refuses when a *different* version currently holds the
        active pointer — re-enabling over a live version is a version move,
        and version moves are rollback decisions, not silent pointer swaps.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: an enable decision without a "
                "recorded reason is not auditable evidence"
            )
        async with self._lock(install_id):
            record = await self._require(install_id, scope)
            if record.state is not ExtensionState.DISABLED:
                raise InvalidTransition(
                    f"install {install_id} is {record.state}; only a "
                    f"{ExtensionState.DISABLED} record can be re-enabled"
                )
            # A version move decision: serialize it against concurrent
            # activations of the same (scope, extension).
            async with self._activation_lock(scope, record.extension_id):
                current = await self._store.active_record(scope, record.extension_id)
                if (
                    current is not None
                    and current.install_id != install_id
                    and current.state is ExtensionState.ACTIVE
                ):
                    raise InvalidTransition(
                        f"{record.extension_id} {current.version} is the active version in "
                        f"{scope.describe}; re-enabling {record.version} over it is a "
                        "version move — use rollback for an explicit, audited decision"
                    )
                updated = await self._transition(
                    record,
                    ExtensionState.ACTIVE,
                    actor=actor,
                    reason=f"re-enabled: {reason}",
                    now=self._clock(),
                )
                await self._store.set_active(updated)
                return updated

    async def remove(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        reason: str,
    ) -> ExtensionInstallRecord:
        """Remove a served version; the record becomes terminal.

        ``REMOVED`` never reactivates: a fresh install of the same version is
        a new inspection, a new authorization decision, a new record. The
        removed record's identity, snapshot, grant and transition trail stay
        exactly where they were — the stores are append-only, so historical
        evidence outlives removal by construction.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: a removal without a recorded reason is not auditable evidence"
            )
        async with self._lock(install_id):
            record = await self._require(install_id, scope)
            served = (
                ExtensionState.ACTIVE,
                ExtensionState.DISABLED,
                ExtensionState.SUPERSEDED,
            )
            if record.state not in served:
                raise InvalidTransition(
                    f"install {install_id} is {record.state}; only a served record "
                    f"({', '.join(state.value for state in served)}) can be removed"
                )
            updated = await self._transition(
                record,
                ExtensionState.REMOVED,
                actor=actor,
                reason=f"removed: {reason}",
                now=self._clock(),
            )
            await self._store.clear_active(updated)
            return updated

    async def rollback(
        self,
        *,
        actor: str,
        scope: ExtensionScope,
        extension_id: str,
        to_version: str,
        reason: str,
    ) -> ExtensionInstallRecord:
        """Move the active version back to a previously authorized version.

        The target must be a prior version of the same extension in the same
        scope whose record is ``SUPERSEDED`` or ``DISABLED`` — its grant was
        frozen by an earlier explicit authorization, so a rollback restores
        authority that already exists; it never grants anything new and never
        executes code. A pinned active version fences the move (lift the pin
        first); between retiring the current version and restoring the target
        the scope truthfully has no active version, and every step lands on
        the audit trail.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: a rollback without a recorded reason is not auditable evidence"
            )
        current = await self._store.active_record(scope, extension_id)
        if current is None or current.state is not ExtensionState.ACTIVE:
            raise InvalidTransition(
                f"no active install of {extension_id} in {scope.describe} to roll back"
            )
        if current.pinned:
            raise VersionPinned(
                f"{extension_id} {current.version} is pinned in {scope.describe}; "
                "rolling back to another version is fenced until the pin is "
                "lifted with an explicit unpin decision"
            )
        target = await self._store.latest_record(scope, extension_id, to_version)
        if target is None:
            raise UnknownInstall(
                f"no install record for {extension_id} {to_version} in {scope.describe}"
            )
        if target.install_id == current.install_id:
            raise InvalidTransition(
                f"rollback target {to_version} is the active version; nothing to roll back to"
            )
        restorable = (ExtensionState.SUPERSEDED, ExtensionState.DISABLED)
        if target.state not in restorable:
            raise InvalidTransition(
                f"rollback target {extension_id} {to_version} is {target.state}; "
                "only a superseded or disabled prior version can be restored"
            )
        # Acquire both record locks in sorted order, so a concurrent rollback
        # in the opposite direction cannot deadlock this one. The activation
        # lock is taken innermost (after the record locks, like every other
        # version move) to keep the lock order acyclic.
        first, second = sorted((current.install_id, target.install_id))
        async with (
            self._lock(first),
            self._lock(second),
            self._activation_lock(scope, extension_id),
        ):
            # Both records may have moved while these locks were waited on.
            current = await self._require(current.install_id, scope)
            target = await self._require(target.install_id, scope)
            if current.state is not ExtensionState.ACTIVE or target.state not in restorable:
                raise InvalidTransition(
                    f"rollback precondition lost: {extension_id} is "
                    f"{current.state}, target {target.version} is {target.state}"
                )
            if current.pinned:
                raise VersionPinned(
                    f"{extension_id} {current.version} was pinned while the "
                    "rollback locks were awaited; lift the pin first"
                )
            await self._transition(
                current,
                ExtensionState.DISABLED,
                actor=actor,
                reason=(f"rolled back to {extension_id} {to_version}: {reason}"),
                now=self._clock(),
            )
            await self._store.clear_active(current)
            restored = await self._transition(
                target,
                ExtensionState.ACTIVE,
                actor=actor,
                reason=(f"restored by rollback from {current.version}: {reason}"),
                now=self._clock(),
            )
            await self._store.set_active(restored)
            return restored

    async def set_pinned(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        pinned: bool,
        reason: str,
    ) -> ExtensionInstallRecord:
        """Hold (or release) a served version with an explicit decision.

        A pin is a flag on the record, not a state: the record keeps its
        state and grant. The decision is still audited — as a same-state
        transition row, so the trail carries who, when and why without
        reading as a state change. While the active version is pinned,
        activating another version of the same extension and rolling back
        away from it are both fenced (:class:`VersionPinned`); disabling and
        removal are deliberately never fenced, so incident response is never
        blocked by a pin. Pinning an already-(un)pinned record is an
        idempotent no-op that re-records nothing.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: a pin decision without a recorded "
                "reason is not auditable evidence"
            )
        async with self._lock(install_id):
            record = await self._require(install_id, scope)
            served = (
                ExtensionState.ACTIVE,
                ExtensionState.DISABLED,
                ExtensionState.SUPERSEDED,
            )
            if record.state not in served:
                raise InvalidTransition(
                    f"install {install_id} is {record.state}; only a served record "
                    f"({', '.join(state.value for state in served)}) can be "
                    "pinned or unpinned"
                )
            if record.pinned == pinned:
                return record
            updated = await self._transition(
                replace(record, pinned=pinned),
                record.state,
                actor=actor,
                reason=f"{'pin' if pinned else 'unpin'}: {reason}",
                now=self._clock(),
                same_state_evidence=True,
            )
            return updated

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

    def _activation_lock(self, scope: ExtensionScope, extension_id: str) -> asyncio.Lock:
        """Serialize version moves for one (scope, extension).

        The per-record ``_lock`` cannot do this: two separately authorized
        installs of the same extension carry different install ids, so their
        record locks never contend. Every read-modify-write of the scope's
        active pointer (activation, supersede, re-enable, rollback) happens
        under this lock, keeping exactly one record ``ACTIVE`` per
        (scope, extension) even when installs race. Always acquired after
        the record lock(s), never before, so lock ordering stays acyclic.
        """
        # No await between the check and the set, so lazy creation is safe
        # under a single event loop.
        key = f"{scope.org_id}|{scope.workspace_id}|{extension_id}"
        lock = self._activation_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._activation_locks[key] = lock
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
        same_state_evidence: bool = False,
    ) -> ExtensionInstallRecord:
        if not same_state_evidence and to_state not in TRANSITIONS[record.state]:
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
