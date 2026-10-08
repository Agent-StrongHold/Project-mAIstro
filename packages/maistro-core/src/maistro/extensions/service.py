"""The governed extension lifecycle: inspect → authorize → install (#953, M9-B2)
and the post-install lifecycle — pin, upgrade, rollback, disable, remove
(#954, M9-B3).

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
   Retries never duplicate install records and never widen the grant.
4. The post-install lifecycle (#954) operates on live records without ever
   re-granting authority by side door:

   - ``pin`` holds the active version in place; activation of any other
     version is refused until the pin is lifted, so no update moves a pinned
     extension silently.
   - ``resume`` returns a disabled record to service by re-running the loader
     with the same bound artifact — restored code crosses the code-execution
     seam, it does not resurrect by decree.
   - ``rollback`` returns a superseded version to service through the same
     loader seam, and only when its frozen grant declares no authority the
     current active grant does not hold and its manifest still evaluates
     compatible. Otherwise it refuses before touching the current state.
   - ``disable`` clears the active pointer immediately — new use stops
     structurally, because the resolution seam returns nothing — and keeps
     every record and transition queryable.
   - ``remove`` runs the host's owned-resource janitor *before* any
     transition (a janitor failure leaves the record untouched), then makes
     the record ``REMOVED`` — terminal for authority, preserved as evidence.

   A version displaced by a newer activation becomes ``SUPERSEDED``: out of
   service, but rollback-eligible with its original grant frozen.

Every transition is appended to the store's audit trail with actor, org /
workspace scope, extension id and version, and a reason. Pin and unpin do not
change state, but they are lifecycle decisions, so they land on the same
trail as state-shaped events.
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
    REMOVABLE_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    ArtifactMismatch,
    ExtensionInstallRecord,
    ExtensionLifecycleError,
    ExtensionManifest,
    ExtensionPackage,
    ExtensionPinned,
    ExtensionScope,
    ExtensionState,
    ExtensionTransition,
    InspectionConflict,
    InvalidTransition,
    RollbackRefused,
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


class OwnedResourceJanitor(Protocol):
    """Host-implemented cleanup policy for resources an extension owns (#954).

    Removal consults the janitor *before* the record leaves its live state:
    a janitor that raises aborts the removal with the record untouched, so a
    half-removed extension cannot exist. What the janitor cleaned is recorded
    on the removal transition; the install record itself — manifest snapshot,
    digest, grant, trust evidence, transition trail — is never deleted.
    """

    async def purge(self, record: ExtensionInstallRecord) -> tuple[str, ...]:
        """Purge the record's owned resources; return their identifiers."""
        ...


class RetainAllJanitor:
    """The default cleanup policy: preserve everything.

    The epic requires removal to preserve historical evidence, so retaining
    every owned resource is the policy until a deployment explicitly opts
    into purging something.
    """

    async def purge(self, record: ExtensionInstallRecord) -> tuple[str, ...]:
        return ()


#: The live states each activation entry point accepts, keyed by the verb the
#: audit reasons use. ``installed`` covers first install and the FAILED retry
#: recovery path; ``resumed`` brings a disabled record back; ``rolled back``
#: restores a superseded one. Each return path re-crosses the loader seam.
_ACTIVATION_SOURCES: dict[str, frozenset[ExtensionState]] = {
    "installed": frozenset({ExtensionState.AUTHORIZED, ExtensionState.FAILED}),
    "resumed": frozenset({ExtensionState.DISABLED}),
    "rolled back": frozenset({ExtensionState.SUPERSEDED}),
}


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
        janitor: OwnedResourceJanitor | None = None,
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
        self._janitor = janitor or RetainAllJanitor()
        self._clock = clock
        self._install_id_factory = install_id_factory or (lambda: uuid.uuid4().hex)
        self._locks: dict[str, asyncio.Lock] = {}
        self._extension_locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    # -- reads ------------------------------------------------------------

    async def get(self, install_id: str, *, scope: ExtensionScope) -> ExtensionInstallRecord:
        """Return one install record, refusing ids outside ``scope``."""
        return await self._require(install_id, scope)

    async def active(
        self, scope: ExtensionScope, extension_id: str
    ) -> ExtensionInstallRecord | None:
        """The currently active record for an extension in the scope, if any.

        This is the new-use resolution seam: only a record in ``ACTIVE``
        state is served. Disable removes the pointer outright and every
        other lifecycle state leaves the pointer unset or replaced, so a
        suspended or uninstalled extension cannot be resolved for use even
        if a stale pointer raced a lifecycle operation.
        """
        record = await self._store.active_record(scope, extension_id)
        if record is None or record.state is not ExtensionState.ACTIVE:
            return None
        return record

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
        that fails the digest check never happened to the machine. When the
        scope already had a different active version, that record is retired
        to ``SUPERSEDED`` — rollback-eligible, grant frozen — as part of the
        same locked swap. Activation of a different version while the
        extension is pinned raises ``ExtensionPinned``.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        record = await self._require(install_id, scope)
        # Lock ordering: extension lock first, install-id lock second.
        async with self._extension_lock(scope, record.extension_id), self._lock(install_id):
            return await self._activate(
                install_id, actor=actor, scope=scope, payload=payload, why="installed"
            )

    async def _active_retry_guard(
        self, record: ExtensionInstallRecord, payload_digest: str, install_id: str
    ) -> ExtensionInstallRecord | None:
        """Resolve activation of a record that is already ``ACTIVE``.

        Returns the record untouched when the presented payload is its bound
        artifact (idempotent retry: no duplicate record, no new activation,
        no authority change) and raises :class:`ArtifactMismatch` otherwise —
        a live version is never silently swapped for different bytes.
        Returns ``None`` for any other state so the caller proceeds.
        """
        if record.state is not ExtensionState.ACTIVE:
            return None
        if record.artifact_sha256 == payload_digest:
            return record
        raise ArtifactMismatch(
            f"install {install_id} is ACTIVE with artifact "
            f"{record.artifact_sha256}; refusing to swap in {payload_digest}"
        )

    async def _activate(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        payload: bytes,
        why: str,
    ) -> ExtensionInstallRecord:
        """Run one activation under the caller's extension lock.

        ``why`` names the lifecycle verb (installed / resumed / rolled back)
        for the audit reasons and selects the source states the entry point
        accepts. Shared by install, resume and rollback: every path back to
        running code digests the payload, re-crosses the loader, and swaps
        the active pointer under the same discipline.
        """
        record = await self._require(install_id, scope)
        now = self._clock()
        payload_digest = sha256_hex(payload)

        retry = await self._active_retry_guard(record, payload_digest, install_id)
        if retry is not None:
            return retry

        sources = _ACTIVATION_SOURCES[why]
        if record.state not in sources:
            raise InvalidTransition(
                f"{why} {install_id} refused: record is {record.state}; this "
                f"entry point accepts {' or '.join(sorted(s.name for s in sources))}"
            )

        pinned = await self.pinned_record(scope, record.extension_id)
        if pinned is not None and pinned.install_id != record.install_id:
            raise ExtensionPinned(
                f"{record.extension_id} is pinned to {pinned.version} (install "
                f"{pinned.install_id}); lift the pin before activating "
                f"{record.version} — a pinned version does not move silently"
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
            reason=f"{why} artifact {payload_digest}",
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
                f"{why} {install_id} failed during activation and is recorded FAILED"
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
                f"{why} {install_id} failed: loader identity mismatch; recorded FAILED"
            )

        record = await self._transition(
            record,
            ExtensionState.ACTIVE,
            actor=actor,
            reason=f"activated {record.extension_id} {record.version} ({why})",
            now=self._clock(),
        )
        await self._retire_displaced_active(record, actor=actor, scope=scope, why=why)
        await self._store.set_active(record)
        return record

    async def _retire_displaced_active(
        self,
        activated: ExtensionInstallRecord,
        *,
        actor: str,
        scope: ExtensionScope,
        why: str,
    ) -> None:
        """Mark a previously active version SUPERSEDED after a new activation.

        Called before the pointer swap so the scope never has two ACTIVE
        records for one extension: the displaced version keeps its frozen
        grant and manifest snapshot, rollback-eligible, with the retirement
        reason on the trail. A displaced record that is no longer ACTIVE (a
        concurrent disable won the race) is left as it is — its pointer slot
        is being replaced either way.
        """
        previous = await self._store.active_record(scope, activated.extension_id)
        if previous is None or previous.install_id == activated.install_id:
            return
        if previous.state is not ExtensionState.ACTIVE:
            return
        await self._transition(
            previous,
            ExtensionState.SUPERSEDED,
            actor=actor,
            reason=(
                f"superseded by {activated.extension_id} {activated.version} "
                f"(install {activated.install_id}, {why})"
            ),
            now=self._clock(),
        )

    # -- post-install lifecycle (#954, M9-B3) ------------------------------

    async def pinned_record(
        self, scope: ExtensionScope, extension_id: str
    ) -> ExtensionInstallRecord | None:
        """The pinned record for an extension in the scope, if one exists.

        The pin lives on the record it holds in place, so "which version is
        pinned" is readable from the durable records themselves — no second
        authority to drift. Removal clears the flag with the record, so a
        removed version can never keep a ghost pin alive.
        """
        records = await self._store.records_for_extension(scope, extension_id)
        for record in records:
            if record.pinned and record.state is not ExtensionState.REMOVED:
                return record
        return None

    async def pin(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        reason: str,
    ) -> ExtensionInstallRecord:
        """Pin the active version so no other version can be activated silently.

        Pinning is a lifecycle decision even though it is not a state change:
        the audit trail carries who pinned, when, and why. Re-pinning the
        already-pinned record is an idempotent no-op. Only the ACTIVE record
        can be pinned — a pin names the version currently in service.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError("reason is required: a pin without a recorded reason is not auditable")
        record = await self._require(install_id, scope)
        async with self._extension_lock(scope, record.extension_id):
            record = await self._require(install_id, scope)
            if record.state is not ExtensionState.ACTIVE:
                raise InvalidTransition(
                    f"install {install_id} is {record.state}; a pin holds the "
                    f"{ExtensionState.ACTIVE} version in place"
                )
            if record.pinned:
                return record
            existing = await self.pinned_record(scope, record.extension_id)
            if existing is not None:
                raise ExtensionPinned(
                    f"{record.extension_id} is already pinned to {existing.version} "
                    f"(install {existing.install_id}); a scope holds at most one pin"
                )
            await self._audit_mutation(
                record,
                actor=actor,
                reason=(
                    f"pinned {record.extension_id} {record.version} to install "
                    f"{record.install_id}: {reason}"
                ),
                now=self._clock(),
                mutate=lambda r: replace(r, pinned=True, pinned_by=actor, pinned_at=self._clock()),
            )
        return await self._require(install_id, scope)

    async def unpin(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        reason: str,
    ) -> ExtensionInstallRecord:
        """Lift the pin so version changes become possible again.

        Unpinning an unpinned record is an idempotent no-op; the lift is
        audited so a following upgrade never looks like it moved a pinned
        version by itself.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: an unpin without a recorded reason is not auditable"
            )
        record = await self._require(install_id, scope)
        async with self._extension_lock(scope, record.extension_id):
            record = await self._require(install_id, scope)
            if not record.pinned:
                return record
            await self._audit_mutation(
                record,
                actor=actor,
                reason=(
                    f"unpinned {record.extension_id} {record.version} (install "
                    f"{record.install_id}): {reason}"
                ),
                now=self._clock(),
                mutate=lambda r: replace(r, pinned=False, pinned_by=None, pinned_at=None),
            )
        return await self._require(install_id, scope)

    async def disable(
        self,
        scope: ExtensionScope,
        extension_id: str,
        *,
        actor: str,
        reason: str,
    ) -> ExtensionInstallRecord:
        """Suspend an extension: new use stops immediately, history is kept.

        The active pointer is cleared as part of the transition, so resolution
        through :meth:`active` returns nothing from that point on — stopping
        use is structural, not a convention callers must remember. The record
        keeps its grant, manifest snapshot and trail; resume brings it back
        through the loader seam with the same bound artifact.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: a disable without a recorded reason is not auditable"
            )
        async with self._extension_lock(scope, extension_id):
            record = await self._store.active_record(scope, extension_id)
            if record is None:
                suspended = await self._suspended_record(scope, extension_id)
                if suspended is not None:
                    return suspended
                raise UnknownInstall(
                    f"no active or suspended install for {extension_id!r} in {scope.describe}"
                )
            if record.state is ExtensionState.DISABLED:
                return record
            if record.state is not ExtensionState.ACTIVE:
                raise InvalidTransition(
                    f"extension {extension_id!r} resolves to a record in "
                    f"{record.state}; only an ACTIVE extension can be disabled"
                )
            updated = await self._transition(
                record,
                ExtensionState.DISABLED,
                actor=actor,
                reason=f"disabled: {reason}",
                now=self._clock(),
            )
            await self._store.clear_active(scope, extension_id)
            return updated

    async def resume(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        payload: bytes,
        reason: str,
    ) -> ExtensionInstallRecord:
        """Return a disabled record to service by re-crossing the loader seam.

        The same bound artifact must be presented and digests again; the
        loader — the only code-execution seam — runs once more, and the
        pointer is re-set only after the identity check passes. The grant is
        not re-decided: it was frozen at authorization and resume is a
        governed return of exactly that authorization.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: a resume without a recorded reason is not auditable"
            )
        record = await self._require(install_id, scope)
        async with self._extension_lock(scope, record.extension_id):
            return await self._activate(
                install_id, actor=actor, scope=scope, payload=payload, why="resumed"
            )

    async def _rollback_to_current(
        self,
        current: ExtensionInstallRecord,
        *,
        to_install_id: str | None,
        payload: bytes,
    ) -> ExtensionInstallRecord | None:
        """Resolve a rollback whose named target is the current active record.

        Retrying the rollback that already happened is an idempotent no-op
        when the payload is the active artifact's bytes; presenting different
        bytes for a live version is refused. Returns ``None`` when the target
        is a different record so the caller proceeds with the superseded one.
        """
        if to_install_id is None or to_install_id != current.install_id:
            return None
        if current.artifact_sha256 == sha256_hex(payload):
            return current
        raise ArtifactMismatch(
            f"rollback target {to_install_id} is already ACTIVE; the "
            "presented payload does not match its bound artifact"
        )

    async def rollback(
        self,
        scope: ExtensionScope,
        extension_id: str,
        *,
        actor: str,
        payload: bytes,
        reason: str,
        to_install_id: str | None = None,
    ) -> ExtensionInstallRecord:
        """Restore a superseded version through the loader seam.

        The target's frozen grant must declare no authority the current
        active grant does not hold, and its manifest must still evaluate
        compatible with this platform; otherwise the rollback is refused
        before the current state is touched — a broader authority needs a
        fresh inspect → authorize pass, never a rollback side door. The
        target's artifact bytes must be presented and digest-verified, like
        every activation. Retrying a completed rollback with the same bytes
        is an idempotent no-op.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: a rollback without a recorded reason is not auditable"
            )
        async with self._extension_lock(scope, extension_id):
            current = await self._store.active_record(scope, extension_id)
            if current is None or current.state is not ExtensionState.ACTIVE:
                raise InvalidTransition(
                    f"extension {extension_id!r} has no ACTIVE record in "
                    f"{scope.describe}; rollback restores a superseded version "
                    "and there is nothing active to roll back from"
                )
            retry = await self._rollback_to_current(
                current, to_install_id=to_install_id, payload=payload
            )
            if retry is not None:
                return retry
            if current.pinned:
                raise ExtensionPinned(
                    f"{extension_id} is pinned to {current.version}; lift the pin "
                    "before rolling back — a pinned version does not move silently"
                )
            target = await self._rollback_target(scope, extension_id, to_install_id)
            broadened = sorted(set(target.granted_permissions) - set(current.granted_permissions))
            if broadened:
                raise RollbackRefused(
                    f"rollback to {target.extension_id} {target.version} refused: its "
                    f"frozen grant declares authority the active grant does not hold "
                    f"({', '.join(broadened)}); broadened authority requires a fresh "
                    "inspect and explicit re-authorization"
                )
            compatibility = evaluate_compatibility(
                target.manifest,
                CompatibilityPolicy(
                    platform_api_version=self._platform_api_version,
                    installed_versions=await self._store.installed_versions(scope),
                ),
            )
            if not compatibility.compatible:
                raise RollbackRefused(
                    f"rollback to {target.extension_id} {target.version} refused: "
                    + "; ".join(compatibility.failures)
                )
            return await self._activate(
                target.install_id, actor=actor, scope=scope, payload=payload, why="rolled back"
            )

    async def _rollback_target(
        self,
        scope: ExtensionScope,
        extension_id: str,
        to_install_id: str | None,
    ) -> ExtensionInstallRecord:
        """Resolve the rollback target: the named record, or newest superseded."""
        if to_install_id is None:
            superseded = [
                record
                for record in await self._store.records_for_extension(scope, extension_id)
                if record.state is ExtensionState.SUPERSEDED
            ]
            if not superseded:
                raise InvalidTransition(
                    f"extension {extension_id!r} has no SUPERSEDED record to roll back "
                    f"to in {scope.describe}; name to_install_id or install a version "
                    "through the governed flow first"
                )
            return superseded[-1]
        target = await self._require(to_install_id, scope)
        if target.extension_id != extension_id:
            raise UnknownInstall(f"install {to_install_id} is not a record of {extension_id!r}")
        if target.state is not ExtensionState.SUPERSEDED:
            raise InvalidTransition(
                f"rollback target {to_install_id} is {target.state}; only a "
                f"{ExtensionState.SUPERSEDED} record can be rolled back to"
            )
        return target

    async def remove(
        self,
        install_id: str,
        *,
        actor: str,
        scope: ExtensionScope,
        reason: str,
        janitor: OwnedResourceJanitor | None = None,
    ) -> ExtensionInstallRecord:
        """Uninstall one record: terminal for authority, preserved as evidence.

        The janitor runs before any transition — a purge failure aborts the
        removal with the record untouched — and what it cleaned is recorded
        on the trail. The record itself, its manifest snapshot, digest,
        frozen grant, trust evidence and full transition history remain
        queryable: removal never deletes canonical historical evidence. The
        active pointer and any pin die with the record. Removing an already
        removed record is an idempotent no-op.
        """
        if not actor.strip():
            raise ValueError("actor is required: every transition needs an accountable actor")
        if not reason.strip():
            raise ValueError(
                "reason is required: a removal without a recorded reason is not auditable"
            )
        record = await self._require(install_id, scope)
        async with self._extension_lock(scope, record.extension_id):
            record = await self._require(install_id, scope)
            if record.state is ExtensionState.REMOVED:
                return record
            if record.state not in REMOVABLE_STATES:
                raise InvalidTransition(
                    f"install {install_id} is {record.state}; records in "
                    "pre-decision or in-flight states are denied, abandoned or "
                    "completed through their own paths, not removed"
                )
            cleaner = janitor or self._janitor
            purged = await cleaner.purge(record)
            detail = ", ".join(purged) if purged else "owned resources retained (default policy)"
            updated = await self._transition(
                record,
                ExtensionState.REMOVED,
                actor=actor,
                reason=f"removed: {reason}; owned resources: {detail}",
                now=self._clock(),
                mutate=lambda r: replace(r, pinned=False, pinned_by=None, pinned_at=None),
            )
            pointed = await self._store.active_record(scope, record.extension_id)
            if pointed is not None and pointed.install_id == record.install_id:
                await self._store.clear_active(scope, record.extension_id)
            return updated

    async def _suspended_record(
        self, scope: ExtensionScope, extension_id: str
    ) -> ExtensionInstallRecord | None:
        """The disabled record for an extension, if one exists."""
        for record in await self._store.records_for_extension(scope, extension_id):
            if record.state is ExtensionState.DISABLED:
                return record
        return None

    async def _audit_mutation(
        self,
        record: ExtensionInstallRecord,
        *,
        actor: str,
        reason: str,
        now: datetime,
        mutate: Callable[[ExtensionInstallRecord], ExtensionInstallRecord],
    ) -> None:
        """Persist a record mutation and its audit event without a state edge.

        Pin and unpin are lifecycle decisions that change no state, so they
        bypass the transition table but land on the same trail: same actor,
        scope, version and reason discipline as every state-shaped event.
        """
        updated = mutate(record)
        updated = replace(updated, updated_at=now)
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
                from_state=updated.state,
                to_state=updated.state,
                reason=reason,
            )
        )

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
        """Serialize lifecycle operations per (scope, extension).

        Activation, disable, rollback, removal and pin changes for one
        extension must not interleave: each one reads the active pointer and
        the record states, and a concurrent writer between the read and the
        write would retire or resurrect a record twice. Lock ordering is
        always extension lock first, install-id lock second.
        """
        key = (scope.org_id, scope.workspace_id, extension_id)
        lock = self._extension_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._extension_locks[key] = lock
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
