"""The governed Workspace pack lifecycle service (M9-F3, #968).

One service owns every lifecycle operation over one global `PackRegistry` and
one `PackLifecycleStore`. The registry is global package identity and is
*read-only* here — the service never mutates a pack — while all Workspace
state lives in activation records behind the store's single atomic `commit`.

The operations, and the acceptance criterion each one exists for:

- `enable_pack` / `disable_pack` — per-Workspace activation, so the same
  pack can be enabled in Workspace A and disabled in Workspace B (#968 AC-1);
- `configure_pack` — Workspace overrides over pack-declared defaults,
  validated against the *activated snapshot* so overrides can only narrow
  (#968 AC-2: configuration never mutates global package identity);
- `preflight_upgrade` / `upgrade_pack` — a registry release moves an
  activation forward only after dependency (backend authority) and
  configuration re-evaluation, and never touches already-instantiated
  Graph/Rubric revisions, which carry their own provenance (#968 AC-3, AC-5);
- `remove_pack` — tombstones the activation after owned-asset cleanup; the
  record and its manifest snapshot survive for historical interpretation
  (#968 AC-4);
- `require_enabled` / `materialize_template` / `instantiate_catalog` — the
  new-use gates: every governed path to "run this pack's loop" refuses
  unless the pack is ENABLED in that Workspace, and materializes from the
  activated snapshot, so historical objects stay on the release that made
  them and new use is blocked the moment a pack is disabled or removed.

Authority is fail-closed by construction: the caller names the Workspace's
authorized backends at each authority-checked operation, and every pack
declares at least one backend, so no pack activates, upgrades, or re-enables
without an explicit grant — an absent grant authorizes nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from maistro.graph.definitions import GraphTemplate
from maistro_design.packs.graphs import pack_graph_template
from maistro_design.packs.lifecycle import (
    InvalidLifecycleOperation,
    PackActivationRecord,
    PackConfigurationInvalid,
    PackIdentityConflict,
    PackLifecycleError,
    PackLifecycleState,
    PackLifecycleStore,
    PackNotEnabled,
    PackRegistryUpgradeUnavailable,
    PackTransition,
    PackTransitionKind,
    PackUpgradeBlocked,
    PackUpgradePreflight,
    WorkspacePackConfiguration,
    pack_from_snapshot,
    parse_pack_version,
    require_non_blank,
    snapshot_pack,
)
from maistro_design.packs.registry import PackRegistry, UnknownPackError
from maistro_design.packs.rubric import GoalRubricCatalog
from maistro_design.packs.types import DomainPack, ExecuteBackend, PackId, RubricDimension

__all__ = ["AuthorizedBackends", "PackLifecycleService", "PackRemovalCleanup"]

#: Backends authorized for a Workspace, evaluated at each authority-checked
#: operation. A missing or empty grant authorizes nothing — fail closed.
AuthorizedBackends = Iterable[ExecuteBackend]

#: Invoked with the record being removed, before the removal persists. May
#: retire assets the pack caused the Workspace to materialize (e.g.
#: template-store rows); it must never touch canonical history.
PackRemovalCleanup = Callable[[PackActivationRecord], None]


class PackLifecycleService:
    """Every governed pack lifecycle operation for one deployment.

    Constructed over the global registry (read-only), the activation store
    (the durability seam) and a clock. Stateless between calls: all durable
    state lives in the store, so restart-safety is a store property, not a
    service property.
    """

    def __init__(
        self,
        *,
        registry: PackRegistry,
        store: PackLifecycleStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._registry = registry
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    # -- reads ------------------------------------------------------------

    async def record(self, workspace_id: str, pack_id: PackId) -> PackActivationRecord | None:
        """The Workspace's activation record for `pack_id`, or `None` (AVAILABLE)."""
        require_non_blank(workspace_id, "workspace_id")
        return await self._store.get_record(workspace_id, pack_id)

    async def workspace_records(self, workspace_id: str) -> list[PackActivationRecord]:
        """Every activation record in one Workspace, ordered by pack id."""
        require_non_blank(workspace_id, "workspace_id")
        return await self._store.records_for_workspace(workspace_id)

    async def transitions(self, workspace_id: str, pack_id: PackId) -> tuple[PackTransition, ...]:
        """The pack's full audit trail in one Workspace, oldest first."""
        require_non_blank(workspace_id, "workspace_id")
        return await self._store.transitions_for(workspace_id, pack_id)

    # -- lifecycle operations ---------------------------------------------

    async def enable_pack(
        self,
        workspace_id: str,
        pack_id: PackId,
        *,
        actor: str,
        reason: str,
        configuration: WorkspacePackConfiguration | None = None,
        authorized_backends: AuthorizedBackends = frozenset(),
    ) -> PackActivationRecord:
        """Activate a pack in one Workspace, at the registry's current release.

        Fresh activations and post-removal re-activations snapshot the
        registry's current release; re-enabling a *disabled* pack resumes the
        previously activated release unchanged — moving versions is upgrade's
        job, never enable's side effect.
        """
        require_non_blank(workspace_id, "workspace_id")
        actor = require_non_blank(actor, "actor")
        reason = require_non_blank(reason, "reason")
        pack = self._registry_pack(pack_id)
        now = self._clock()

        record = await self._store.get_record(workspace_id, pack_id)
        if record is not None and record.state is PackLifecycleState.ENABLED:
            raise PackLifecycleError(
                f"pack {pack_id.value!r} is already enabled in workspace "
                f"{workspace_id!r} at {record.version}; use upgrade or configure"
            )
        if record is None or record.state is PackLifecycleState.REMOVED:
            self._require_backends_authorized(pack, authorized_backends)
            config = self._validate_configuration(pack, configuration)
            new_record = PackActivationRecord(
                workspace_id=workspace_id,
                pack_id=pack_id,
                state=PackLifecycleState.ENABLED,
                version=pack.version,
                manifest=snapshot_pack(pack),
                configuration=config,
                enabled_by=actor,
                activated_at=now,
                updated_at=now,
            )
            from_state = PackLifecycleState.AVAILABLE if record is None else record.state
            from_version = "" if record is None else record.version
            await self._commit(
                new_record,
                expected=record,
                kind=PackTransitionKind.ENABLE,
                actor=actor,
                reason=reason,
                from_state=from_state,
                from_version=from_version,
                to_version=pack.version,
            )
            return new_record

        # DISABLED -> ENABLED: resume exactly what was activated before.
        # Authority is still re-evaluated: the Workspace may have revoked a
        # backend while the pack was paused, and a resume must not silently
        # reactivate a dependency it no longer holds.
        resumed_pack = pack_from_snapshot(record.manifest, pack_id)
        self._require_backends_authorized(resumed_pack, authorized_backends)
        resumed = PackActivationRecord(
            workspace_id=record.workspace_id,
            pack_id=record.pack_id,
            state=PackLifecycleState.ENABLED,
            version=record.version,
            manifest=record.manifest,
            configuration=record.configuration,
            enabled_by=record.enabled_by,
            activated_at=record.activated_at,
            updated_at=now,
        )
        await self._commit(
            resumed,
            expected=record,
            kind=PackTransitionKind.ENABLE,
            actor=actor,
            reason=reason,
            from_state=PackLifecycleState.DISABLED,
            from_version=record.version,
            to_version=record.version,
        )
        return resumed

    async def disable_pack(
        self, workspace_id: str, pack_id: PackId, *, actor: str, reason: str
    ) -> PackActivationRecord:
        """Pause new use in one Workspace, keeping the record for re-enable."""
        require_non_blank(workspace_id, "workspace_id")
        actor = require_non_blank(actor, "actor")
        reason = require_non_blank(reason, "reason")
        record = await self._require_state(workspace_id, pack_id, "disable")
        disabled = PackActivationRecord(
            workspace_id=record.workspace_id,
            pack_id=record.pack_id,
            state=PackLifecycleState.DISABLED,
            version=record.version,
            manifest=record.manifest,
            configuration=record.configuration,
            enabled_by=record.enabled_by,
            activated_at=record.activated_at,
            updated_at=self._clock(),
        )
        await self._commit(
            disabled,
            expected=record,
            kind=PackTransitionKind.DISABLE,
            actor=actor,
            reason=reason,
            from_state=PackLifecycleState.ENABLED,
            from_version=record.version,
            to_version=record.version,
        )
        return disabled

    async def remove_pack(
        self,
        workspace_id: str,
        pack_id: PackId,
        *,
        actor: str,
        reason: str,
        owned_asset_cleanup: PackRemovalCleanup | None = None,
    ) -> PackActivationRecord:
        """Tombstone the activation after owned-asset cleanup.

        `owned_asset_cleanup` runs *before* the removal persists and receives
        the record being removed; if it raises, nothing is persisted and the
        operation never happened. Cleanup may retire assets the pack caused
        the Workspace to materialize (e.g. template-store rows) — never
        canonical history: Goals, Runs, NodeRuns, Attempts and Rubric catalog
        instances are canonical identity the pack never owned, so removal
        cannot and does not touch them.
        """
        require_non_blank(workspace_id, "workspace_id")
        actor = require_non_blank(actor, "actor")
        reason = require_non_blank(reason, "reason")
        record = await self._store.get_record(workspace_id, pack_id)
        if record is None:
            raise PackRegistryUpgradeUnavailable(
                f"pack {pack_id.value!r} has no activation in workspace {workspace_id!r}"
            )
        if record.state is PackLifecycleState.REMOVED:
            raise InvalidLifecycleOperation(
                f"pack {pack_id.value!r} is already removed from workspace {workspace_id!r}"
            )
        if owned_asset_cleanup is not None:
            owned_asset_cleanup(record)
        removed = PackActivationRecord(
            workspace_id=record.workspace_id,
            pack_id=record.pack_id,
            state=PackLifecycleState.REMOVED,
            version=record.version,
            manifest=record.manifest,
            configuration=record.configuration,
            enabled_by=record.enabled_by,
            activated_at=record.activated_at,
            updated_at=self._clock(),
        )
        await self._commit(
            removed,
            expected=record,
            kind=PackTransitionKind.REMOVE,
            actor=actor,
            reason=reason,
            from_state=record.state,
            from_version=record.version,
            to_version=record.version,
        )
        return removed

    async def configure_pack(
        self,
        workspace_id: str,
        pack_id: PackId,
        configuration: WorkspacePackConfiguration,
        *,
        actor: str,
        reason: str,
    ) -> PackActivationRecord:
        """Replace the Workspace's overrides, validated against the activated
        snapshot. Version and manifest snapshot are untouched."""
        require_non_blank(workspace_id, "workspace_id")
        actor = require_non_blank(actor, "actor")
        reason = require_non_blank(reason, "reason")
        record = await self._require_state(workspace_id, pack_id, "configure")
        pack = pack_from_snapshot(record.manifest, pack_id)
        validated = self._validate_configuration(pack, configuration)
        configured = PackActivationRecord(
            workspace_id=record.workspace_id,
            pack_id=record.pack_id,
            state=record.state,
            version=record.version,
            manifest=record.manifest,
            configuration=validated,
            enabled_by=record.enabled_by,
            activated_at=record.activated_at,
            updated_at=self._clock(),
        )
        await self._commit(
            configured,
            expected=record,
            kind=PackTransitionKind.CONFIGURE,
            actor=actor,
            reason=reason,
            from_state=record.state,
            from_version=record.version,
            to_version=record.version,
        )
        return configured

    # -- upgrade -----------------------------------------------------------

    async def preflight_upgrade(
        self,
        workspace_id: str,
        pack_id: PackId,
        *,
        authorized_backends: AuthorizedBackends = frozenset(),
    ) -> PackUpgradePreflight:
        """Evaluate the registry's release against this Workspace's activation.

        Re-evaluates dependencies (every backend the target declares must be
        Workspace-authorized) and configuration (every overridden Rubric
        dimension id must still be declared). Any failure blocks the upgrade
        and is named in `blocked_by`.
        """
        require_non_blank(workspace_id, "workspace_id")
        record = await self._store.get_record(workspace_id, pack_id)
        target = self._registry_pack(pack_id)
        authorized = frozenset(authorized_backends)

        # A tombstoned (REMOVED) activation is as unavailable as a missing one:
        # upgrade_pack refuses both, so preflight must never advertise an
        # upgrade the operation is guaranteed to reject.
        if record is None or record.state is PackLifecycleState.REMOVED:
            return PackUpgradePreflight(
                workspace_id=workspace_id,
                pack_id=pack_id,
                current_version="",
                target_version=target.version,
                can_upgrade=False,
                blocked_by=(f"pack {pack_id.value!r} has no active activation in this workspace",),
            )
        return _evaluate_upgrade(record, target, authorized, record.configuration)

    async def upgrade_pack(
        self,
        workspace_id: str,
        pack_id: PackId,
        *,
        actor: str,
        reason: str,
        configuration: WorkspacePackConfiguration | None = None,
        authorized_backends: AuthorizedBackends = frozenset(),
    ) -> PackActivationRecord:
        """Move the activation to the registry's release after preflight.

        Only the activation record moves: the new manifest snapshot and any
        replacement configuration. Already-instantiated Graph templates and
        Rubric catalog revisions keep the provenance they were minted with —
        an upgrade rewrites nothing historical, by construction (it writes a
        new record; it has no path to any other object).
        """
        require_non_blank(workspace_id, "workspace_id")
        actor = require_non_blank(actor, "actor")
        reason = require_non_blank(reason, "reason")
        record = await self._store.get_record(workspace_id, pack_id)
        if record is None or record.state is PackLifecycleState.REMOVED:
            raise PackRegistryUpgradeUnavailable(
                f"pack {pack_id.value!r} has no active activation in workspace "
                f"{workspace_id!r}; enable it first"
            )
        pack = self._registry_pack(pack_id)
        if (
            parse_pack_version(pack.version) == parse_pack_version(record.version)
            and snapshot_pack(pack).sha256 != record.manifest.sha256
        ):
            raise PackIdentityConflict(
                f"registry pack {pack_id.value!r} changed content under unchanged "
                f"version {pack.version}: a pack version is global identity, and a "
                "Workspace snapshot may not be reconciled silently"
            )
        preflight = (
            await self.preflight_upgrade(
                workspace_id,
                pack_id,
                authorized_backends=authorized_backends,
            )
            if configuration is None
            else _evaluate_upgrade(
                record,
                pack,
                frozenset(authorized_backends),
                self._validate_configuration(pack, configuration),
            )
        )
        if not preflight.can_upgrade:
            raise PackUpgradeBlocked("upgrade blocked: " + "; ".join(preflight.blocked_by))
        replacement = (
            self._validate_configuration(pack, configuration)
            if configuration is not None
            else record.configuration
        )
        upgraded = PackActivationRecord(
            workspace_id=record.workspace_id,
            pack_id=record.pack_id,
            state=record.state,
            version=pack.version,
            manifest=snapshot_pack(pack),
            configuration=replacement,
            enabled_by=record.enabled_by,
            activated_at=record.activated_at,
            updated_at=self._clock(),
        )
        await self._commit(
            upgraded,
            expected=record,
            kind=PackTransitionKind.UPGRADE,
            actor=actor,
            reason=reason,
            from_state=record.state,
            from_version=record.version,
            to_version=pack.version,
        )
        return upgraded

    # -- new-use gates ------------------------------------------------------

    async def require_enabled(self, workspace_id: str, pack_id: PackId) -> PackActivationRecord:
        """The new-use gate: the ENABLED record, or `PackNotEnabled`.

        Every governed path to new use passes through here, so disabling or
        removing a pack blocks new Goal/Graph creation from it immediately,
        while historical objects — never routed through this gate — stay
        interpretable.
        """
        require_non_blank(workspace_id, "workspace_id")
        record = await self._store.get_record(workspace_id, pack_id)
        if record is None:
            raise PackNotEnabled(
                f"pack {pack_id.value!r} is not activated in workspace {workspace_id!r}"
            )
        if record.state is not PackLifecycleState.ENABLED:
            raise PackNotEnabled(
                f"pack {pack_id.value!r} is {record.state.value} in workspace "
                f"{workspace_id!r}; new use requires an enabled pack"
            )
        return record

    async def materialize_template(self, workspace_id: str, pack_id: PackId) -> GraphTemplate:
        """The pack's canonical Graph template, from the activated snapshot.

        The template materializes from the Workspace's snapshot — digest
        re-verified — so a registry upgrade cannot silently change what new
        Graphs look like in a Workspace that has not upgraded.
        """
        record = await self.require_enabled(workspace_id, pack_id)
        pack = pack_from_snapshot(record.manifest, pack_id)
        return pack_graph_template(pack, workspace_id=workspace_id)

    async def instantiate_catalog(
        self,
        workspace_id: str,
        pack_id: PackId,
        *,
        goal_id: str,
        goal_revision: int,
        catalog_id: str | None = None,
    ) -> GoalRubricCatalog:
        """Instantiate the pack's Rubric defaults onto a canonical Goal.

        The Workspace's configuration override selects which declared
        dimensions apply; the catalog identity is minted per instantiation
        and carries `pack_version` provenance, so the Goal owns a record of
        which release its evaluation criteria came from.
        """
        record = await self.require_enabled(workspace_id, pack_id)
        pack = pack_from_snapshot(record.manifest, pack_id)
        return GoalRubricCatalog.instantiate(
            pack_id=pack.pack_id,
            pack_version=record.version,
            dimensions=_configured_dimensions(pack, record.configuration),
            goal_id=goal_id,
            goal_revision=goal_revision,
            catalog_id=catalog_id,
        )

    # -- internals ----------------------------------------------------------

    def _registry_pack(self, pack_id: PackId) -> DomainPack:
        try:
            return self._registry.get(pack_id)
        except UnknownPackError as exc:  # a closed enum cannot name an unknown pack
            raise PackLifecycleError(str(exc)) from exc

    async def _require_state(
        self, workspace_id: str, pack_id: PackId, operation: str
    ) -> PackActivationRecord:
        """The record an operation needs, asserting it is ENABLED."""
        record = await self._store.get_record(workspace_id, pack_id)
        if record is None:
            raise PackNotEnabled(
                f"pack {pack_id.value!r} is not activated in workspace {workspace_id!r}; "
                f"cannot {operation}"
            )
        if record.state is not PackLifecycleState.ENABLED:
            raise InvalidLifecycleOperation(
                f"cannot {operation} pack {pack_id.value!r} in workspace "
                f"{workspace_id!r}: state is {record.state.value}"
            )
        return record

    @staticmethod
    def _require_backends_authorized(
        pack: DomainPack, authorized_backends: AuthorizedBackends
    ) -> None:
        authorized = frozenset(authorized_backends)
        missing = [backend for backend in pack.execute_backends if backend not in authorized]
        if missing:
            raise PackUpgradeBlocked(
                f"pack {pack.pack_id.value!r} requires backends this workspace has not "
                "authorized: "
                + ", ".join(sorted(backend.value for backend in missing))
                + " (an absent grant authorizes nothing)"
            )

    @staticmethod
    def _validate_configuration(
        pack: DomainPack, configuration: WorkspacePackConfiguration | None
    ) -> WorkspacePackConfiguration:
        if configuration is None:
            return WorkspacePackConfiguration()
        declared = {dimension.dimension_id for dimension in pack.rubric_dimensions}
        selected = configuration.rubric_dimension_ids or ()
        unknown = [dimension_id for dimension_id in selected if dimension_id not in declared]
        if unknown:
            raise PackConfigurationInvalid(
                f"workspace configuration selects rubric dimensions pack "
                f"{pack.pack_id.value!r} does not declare: " + ", ".join(sorted(unknown))
            )
        return configuration

    async def _commit(
        self,
        record: PackActivationRecord,
        *,
        expected: PackActivationRecord | None,
        kind: PackTransitionKind,
        actor: str,
        reason: str,
        from_state: PackLifecycleState,
        from_version: str,
        to_version: str,
    ) -> None:
        """Commit through the store's compare-and-set seam: `expected` is the
        record this operation read (`None` if none), so a concurrent write
        since the read makes the store reject this one — a stale disable can
        never overwrite a `REMOVED` tombstone. `next_seq` may suspend before
        the CAS, but the store checks and writes in one step."""
        transition = PackTransition(
            seq=await self._store.next_seq(),
            at=self._clock(),
            kind=kind,
            workspace_id=record.workspace_id,
            pack_id=record.pack_id,
            actor=actor,
            from_state=from_state,
            to_state=record.state,
            from_version=from_version,
            to_version=to_version,
            reason=reason,
        )
        await self._store.commit(record, transition, expected=expected)


def _block_on_regression(
    record: PackActivationRecord, target: DomainPack, blocked: list[str]
) -> None:
    """Name a target release that is not an upgrade over the activation."""
    if parse_pack_version(target.version) > parse_pack_version(record.version):
        return
    relation = "same release" if target.version == record.version else "an older release"
    blocked.append(
        f"registry release {target.version} is {relation}, not an upgrade "
        f"over activated {record.version}"
    )


def _authority_delta(
    record: PackActivationRecord,
    target: DomainPack,
    authorized: frozenset[ExecuteBackend],
    blocked: list[str],
) -> tuple[tuple[ExecuteBackend, ...], tuple[ExecuteBackend, ...]]:
    """Re-evaluate the dependency surface: backends the target adds, and the
    ones the Workspace must hold before the move may proceed."""
    current = pack_from_snapshot(record.manifest, record.pack_id)
    target_backends = set(target.execute_backends)
    new_backends = tuple(
        sorted(target_backends - set(current.execute_backends), key=lambda backend: backend.value)
    )
    unauthorized = tuple(
        backend
        for backend in sorted(target_backends, key=lambda backend: backend.value)
        if backend not in authorized
    )
    if unauthorized:
        blocked.append(
            "target release requires backends this workspace has not authorized: "
            + ", ".join(backend.value for backend in unauthorized)
        )
    return new_backends, unauthorized


def _configuration_delta(
    candidate_configuration: WorkspacePackConfiguration,
    target: DomainPack,
    blocked: list[str],
) -> tuple[str, ...]:
    """Re-evaluate the overrides that would survive the move."""
    configured_ids = candidate_configuration.rubric_dimension_ids or ()
    declared_ids = {dimension.dimension_id for dimension in target.rubric_dimensions}
    dropped = tuple(oid for oid in configured_ids if oid not in declared_ids)
    if dropped:
        blocked.append(
            "workspace configuration selects rubric dimensions the target release "
            "no longer declares: " + ", ".join(sorted(dropped))
        )
    return dropped


def _evaluate_upgrade(
    record: PackActivationRecord,
    target: DomainPack,
    authorized: frozenset[ExecuteBackend],
    candidate_configuration: WorkspacePackConfiguration,
) -> PackUpgradePreflight:
    """Re-evaluate dependencies and configuration against a target release.

    `candidate_configuration` is what would be in effect after the move — the
    current overrides for a read-only preflight, or the operator's replacement
    configuration for an upgrade that migrates in the same audited step.
    """
    blocked: list[str] = []
    _block_on_regression(record, target, blocked)
    new_backends, unauthorized = _authority_delta(record, target, authorized, blocked)
    dropped = _configuration_delta(candidate_configuration, target, blocked)
    return PackUpgradePreflight(
        workspace_id=record.workspace_id,
        pack_id=record.pack_id,
        current_version=record.version,
        target_version=target.version,
        can_upgrade=not blocked,
        blocked_by=tuple(blocked),
        new_backends=new_backends,
        unauthorized_backends=unauthorized,
        dropped_rubric_dimensions=dropped,
    )


def _configured_dimensions(
    pack: DomainPack, configuration: WorkspacePackConfiguration
) -> tuple[RubricDimension, ...]:
    """The pack's dimensions, filtered to the Workspace's override (pack order)."""
    selected = configuration.rubric_dimension_ids
    if selected is None:
        return pack.rubric_dimensions
    wanted = set(selected)
    return tuple(d for d in pack.rubric_dimensions if d.dimension_id in wanted)
