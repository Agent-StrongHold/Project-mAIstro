"""Workspace-scoped pack lifecycle (M9-F3, #968) — activation to removal.

Issue-acceptance mapping (each test class names the criterion it proves):

- AC-1 "same pack can be enabled in Workspace A and disabled in Workspace B"
  → `TestSamePackEnabledHereDisabledThere`
- AC-2 "Workspace configuration never mutates global package identity"
  → `TestConfigurationNeverMutatesGlobalIdentity`
- AC-3 "pack upgrade cannot silently rewrite historical Graph/Persona/Rubric
  revisions" → `TestUpgradePreservesHistoricalRevisions`
- AC-4 "disabling/removing a pack blocks new use while existing historical
  Runs/artifacts remain interpretable" → `TestDisableAndRemoveBlockNewUseOnly`
- AC-5 "dependencies and authority are re-evaluated on upgrade"
  → `TestUpgradeReevaluatesDependencyAndAuthority`
- AC-6 "lifecycle transitions are durable, restart-safe, and auditable"
  → `TestTransitionsAreAuditedAtomicAndRestartSafe`

The upgrade fixture builds a changed release programmatically over the
builtin `product` manifest (`DomainPack.model_copy`) — the same contract the
service snapshots, so a version bump and a shape change are both expressible
without a second YAML file.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from maistro.graph.definitions import GraphTemplate
from maistro_design.packs import (
    DomainPack,
    ExecuteBackend,
    GoalRubricCatalog,
    InMemoryPackLifecycleStore,
    InvalidLifecycleOperation,
    PackConfigurationInvalid,
    PackId,
    PackIdentityConflict,
    PackLifecycleError,
    PackLifecycleService,
    PackLifecycleState,
    PackNotEnabled,
    PackRegistry,
    PackRegistryUpgradeUnavailable,
    PackTransitionKind,
    PackUpgradeBlocked,
    PackUpgradePreflight,
    SnapshotIntegrityError,
    WorkspacePackConfiguration,
    pack_graph_template,
    snapshot_pack,
)

WS_A = "ws-968-a"
WS_B = "ws-968-b"
ACTOR = "operator-968"
GOAL_ID = "goal-968"
GRANTS = frozenset({ExecuteBackend.BUILDERS, ExecuteBackend.CANVAS})
#: A test clock: every call advances one second past the last, so record
#: timestamps and transition ordering are deterministic without wall time.
_TICKS = iter(range(1, 1_000_000))


def _clock() -> Any:
    from datetime import UTC, datetime, timedelta

    base = datetime(2026, 10, 6, tzinfo=UTC)
    return base + timedelta(seconds=next(_TICKS))


def _service(
    registry: PackRegistry | None = None, store: InMemoryPackLifecycleStore | None = None
) -> PackLifecycleService:
    return PackLifecycleService(
        registry=registry or PackRegistry.builtin(),
        store=store or InMemoryPackLifecycleStore(),
        clock=_clock,
    )


def _registry_with(pack: DomainPack) -> PackRegistry:
    return PackRegistry((pack,))


def _release(
    version: str,
    *,
    drop_dimension: str | None = None,
    add_backend: ExecuteBackend | None = None,
) -> DomainPack:
    """A changed `product` release: new version, optionally new shape."""
    pack = PackRegistry.builtin().get(PackId.PRODUCT)
    updates: dict[str, Any] = {"version": version}
    if drop_dimension is not None:
        updates["rubric_dimensions"] = tuple(
            dimension
            for dimension in pack.rubric_dimensions
            if dimension.dimension_id != drop_dimension
        )
    if add_backend is not None:
        updates["execute_backends"] = tuple(sorted([*pack.execute_backends, add_backend]))
    return pack.model_copy(update=updates)


# --- AC-1: per-Workspace activation -----------------------------------------


class TestSamePackEnabledHereDisabledThere:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_enabled_in_a_while_never_activated_in_b(self) -> None:
        service = _service()
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="onboard", authorized_backends=GRANTS
        )
        record = await service.record(WS_A, PackId.PRODUCT)
        assert record is not None and record.state is PackLifecycleState.ENABLED
        assert await service.record(WS_B, PackId.PRODUCT) is None
        # New use is gated per Workspace, not globally.
        template = await service.materialize_template(WS_A, PackId.PRODUCT)
        assert isinstance(template, GraphTemplate)
        with pytest.raises(PackNotEnabled, match="not activated"):
            await service.materialize_template(WS_B, PackId.PRODUCT)

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_disabled_in_b_while_enabled_in_a(self) -> None:
        service = _service()
        for workspace in (WS_A, WS_B):
            await service.enable_pack(
                workspace,
                PackId.PRODUCT,
                actor=ACTOR,
                reason="onboard",
                authorized_backends=GRANTS,
            )
        disabled = await service.disable_pack(WS_B, PackId.PRODUCT, actor=ACTOR, reason="cost")
        assert disabled.state is PackLifecycleState.DISABLED
        with pytest.raises(PackNotEnabled, match="disabled"):
            await service.materialize_template(WS_B, PackId.PRODUCT)
        template = await service.materialize_template(WS_A, PackId.PRODUCT)
        assert template.template_id == "pack.product"
        # The trails are per-Workspace too: A has one transition, B two.
        assert len(await service.transitions(WS_A, PackId.PRODUCT)) == 1
        assert [t.kind for t in await service.transitions(WS_B, PackId.PRODUCT)] == [
            PackTransitionKind.ENABLE,
            PackTransitionKind.DISABLE,
        ]

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_records_are_independent_per_workspace_and_pack(self) -> None:
        service = _service()
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        await service.enable_pack(
            WS_A,
            PackId.BOOK,
            actor=ACTOR,
            reason="r",
            authorized_backends={ExecuteBackend.TEXT_ARTIFACT_TREE},
        )
        records = await service.workspace_records(WS_A)
        assert [record.pack_id for record in records] == [PackId.BOOK, PackId.PRODUCT]
        assert all(record.workspace_id == WS_A for record in records)
        assert await service.workspace_records(WS_B) == []


# --- AC-2: Workspace configuration never mutates global identity -------------


class TestConfigurationNeverMutatesGlobalIdentity:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_configure_leaves_the_registry_and_other_workspaces_unchanged(self) -> None:
        service = _service()
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        await service.enable_pack(
            WS_B, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        before = snapshot_pack(PackRegistry.builtin().get(PackId.PRODUCT))
        await service.configure_pack(
            WS_A,
            PackId.PRODUCT,
            WorkspacePackConfiguration(rubric_dimension_ids=("clarity_of_offer",)),
            actor=ACTOR,
            reason="narrow the rubric",
        )
        # The global contract is byte-identical after a Workspace write.
        after = snapshot_pack(PackRegistry.builtin().get(PackId.PRODUCT))
        assert after == before
        # And the override lives on the Workspace's record alone.
        a = (await service.record(WS_A, PackId.PRODUCT)).configuration
        b = (await service.record(WS_B, PackId.PRODUCT)).configuration
        assert a.rubric_dimension_ids == ("clarity_of_offer",)
        assert b == WorkspacePackConfiguration()

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_override_may_only_narrow_declared_defaults(self) -> None:
        service = _service()
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        with pytest.raises(PackConfigurationInvalid, match="does not declare"):
            await service.configure_pack(
                WS_A,
                PackId.PRODUCT,
                WorkspacePackConfiguration(rubric_dimension_ids=("not_a_dimension",)),
                actor=ACTOR,
                reason="r",
            )
        # And an enable-time configuration is validated the same way.
        with pytest.raises(PackConfigurationInvalid):
            await service.enable_pack(
                WS_B,
                PackId.PRODUCT,
                actor=ACTOR,
                reason="r",
                configuration=WorkspacePackConfiguration(rubric_dimension_ids=("nope",)),
                authorized_backends=GRANTS,
            )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_instantiation_applies_the_override_over_the_defaults(self) -> None:
        service = _service()
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        await service.configure_pack(
            WS_A,
            PackId.PRODUCT,
            WorkspacePackConfiguration(rubric_dimension_ids=("claim_evidence",)),
            actor=ACTOR,
            reason="focus",
        )
        catalog = await service.instantiate_catalog(
            WS_A, PackId.PRODUCT, goal_id=GOAL_ID, goal_revision=1
        )
        assert [dimension.dimension_id for dimension in catalog.dimensions] == ["claim_evidence"]
        unconfigured = (
            PackRegistry.builtin()
            .get(PackId.PRODUCT)
            .instantiate_rubric_catalog(goal_id=GOAL_ID, goal_revision=1)
        )
        assert len(unconfigured.dimensions) == 3  # the pack defaults, unchanged


# --- AC-3: upgrades never rewrite historical revisions -----------------------


class TestUpgradePreservesHistoricalRevisions:
    @pytest.fixture()
    async def activated(self) -> Any:
        service = _service()
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        template = await service.materialize_template(WS_A, PackId.PRODUCT)
        catalog = await service.instantiate_catalog(
            WS_A, PackId.PRODUCT, goal_id=GOAL_ID, goal_revision=2
        )
        return service, template, catalog

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_upgrade_moves_only_the_record(self, activated: Any) -> None:
        service, template, catalog = activated
        upgraded_registry = _registry_with(_release("1.1.0"))
        moved = _service(store=service._store, registry=upgraded_registry)
        preflight = await moved.preflight_upgrade(WS_A, PackId.PRODUCT, authorized_backends=GRANTS)
        assert isinstance(preflight, PackUpgradePreflight)
        assert preflight.can_upgrade
        assert (preflight.current_version, preflight.target_version) == ("1.0.0", "1.1.0")
        await moved.upgrade_pack(
            WS_A,
            PackId.PRODUCT,
            actor=ACTOR,
            reason="new release",
            authorized_backends=GRANTS,
        )
        record = await service.record(WS_A, PackId.PRODUCT)
        assert record is not None and record.version == "1.1.0"
        # Historical objects are value objects minted earlier: untouched.
        assert (
            template.content_hash
            == pack_graph_template(
                PackRegistry.builtin().get(PackId.PRODUCT), workspace_id=WS_A
            ).content_hash
        )
        assert isinstance(catalog, GoalRubricCatalog)
        assert catalog.pack_version == "1.0.0"
        assert catalog.goal_revision == 2
        # New use now materializes the release the Workspace upgraded to.
        new_template = await service.materialize_template(WS_A, PackId.PRODUCT)
        assert new_template.metadata["pack_version"] == "1.1.0"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_an_unupgraded_workspace_keeps_running_its_snapshot(self) -> None:
        # WS_A activates at 1.0.0; the registry then moves to 1.1.0. WS_A has
        # not upgraded, so its new use must still materialize 1.0.0 — the
        # registry release cannot silently rewrite what a Workspace runs.
        store = InMemoryPackLifecycleStore()
        first = _service(store=store)
        await first.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        a_before = await first.materialize_template(WS_A, PackId.PRODUCT)
        assert a_before.metadata["pack_version"] == "1.0.0"

        moved = _service(store=store, registry=_registry_with(_release("1.1.0")))
        a_after_registry_move = await moved.materialize_template(WS_A, PackId.PRODUCT)
        assert a_after_registry_move.metadata["pack_version"] == "1.0.0"
        assert a_after_registry_move.content_hash == a_before.content_hash
        # WS_B activates *now*: fresh activations take the current registry
        # release, WS_A stays where it is until it upgrades.
        await moved.enable_pack(
            WS_B, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        assert (await moved.record(WS_B, PackId.PRODUCT)).version == "1.1.0"
        b_template = await moved.materialize_template(WS_B, PackId.PRODUCT)
        assert b_template.metadata["pack_version"] == "1.1.0"
        # Downgrade the registry underneath both: nobody follows it silently.
        downgraded = _service(store=store, registry=_registry_with(_release("0.9.0")))
        preflight = await downgraded.preflight_upgrade(
            WS_A, PackId.PRODUCT, authorized_backends=GRANTS
        )
        assert not preflight.can_upgrade and "older" in preflight.blocked_by[0]

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_upgrade_preflight_and_upgrade_refuse_without_a_record(self) -> None:
        service = _service(registry=_registry_with(_release("1.1.0")))
        preflight = await service.preflight_upgrade(
            WS_A, PackId.PRODUCT, authorized_backends=GRANTS
        )
        assert not preflight.can_upgrade
        assert "not activated" in preflight.blocked_by[0]
        with pytest.raises(PackRegistryUpgradeUnavailable):
            await service.upgrade_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="r")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_same_version_under_different_content_is_an_identity_conflict(self) -> None:
        service = _service()
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        # Same declared version, different contract bytes: global identity is
        # version+content, so the drift is refused, never reconciled.
        tampered_registry = _registry_with(
            PackRegistry.builtin()
            .get(PackId.PRODUCT)
            .model_copy(update={"summary": "a different contract under 1.0.0"})
        )
        conflicted = _service(store=service._store, registry=tampered_registry)
        with pytest.raises(PackIdentityConflict, match="changed content"):
            await conflicted.upgrade_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="r")

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_upgrade_to_the_same_release_is_refused(self) -> None:
        service = _service()
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        preflight = await service.preflight_upgrade(
            WS_A, PackId.PRODUCT, authorized_backends=GRANTS
        )
        assert not preflight.can_upgrade and "same release" in preflight.blocked_by[0]
        with pytest.raises(PackUpgradeBlocked):
            await service.upgrade_pack(
                WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
            )


# --- AC-4: disable/remove block new use, history stays interpretable ---------


class TestDisableAndRemoveBlockNewUseOnly:
    @pytest.fixture()
    async def activated(self) -> Any:
        service = _service()
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        template = await service.materialize_template(WS_A, PackId.PRODUCT)
        catalog = await service.instantiate_catalog(
            WS_A, PackId.PRODUCT, goal_id=GOAL_ID, goal_revision=1
        )
        return service, template, catalog

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_disable_blocks_new_use_and_keeps_history_usable(self, activated: Any) -> None:
        service, template, catalog = activated
        await service.disable_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="pause")
        with pytest.raises(PackNotEnabled, match="disabled"):
            await service.materialize_template(WS_A, PackId.PRODUCT)
        with pytest.raises(PackNotEnabled, match="disabled"):
            await service.instantiate_catalog(
                WS_A, PackId.PRODUCT, goal_id=GOAL_ID, goal_revision=1
            )
        # The historical objects are self-contained canonical values: the
        # template still hashes to what ran, the Goal-owned catalog still
        # carries its dimensions and provenance.
        assert (
            template.content_hash
            == pack_graph_template(
                PackRegistry.builtin().get(PackId.PRODUCT), workspace_id=WS_A
            ).content_hash
        )
        assert catalog.pack_version == "1.0.0" and len(catalog.dimensions) == 3
        # Re-enable resumes the same release, not the registry's current one.
        registry_moves = _service(store=service._store, registry=_registry_with(_release("9.9.9")))
        resumed = await registry_moves.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="back", authorized_backends=GRANTS
        )
        assert resumed.version == "1.0.0"
        assert (await service.materialize_template(WS_A, PackId.PRODUCT)).metadata[
            "pack_version"
        ] == "1.0.0"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_remove_tombstones_cleans_owned_assets_keeps_evidence(
        self, activated: Any
    ) -> None:
        service, template, catalog = activated
        cleaned: list[Any] = []
        removed = await service.remove_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="offboard", owned_asset_cleanup=cleaned.append
        )
        assert removed.state is PackLifecycleState.REMOVED
        # The callback saw the record being removed — its pre-removal state —
        # before the tombstone was persisted.
        assert len(cleaned) == 1
        assert cleaned[0].state is PackLifecycleState.ENABLED
        assert cleaned[0].version == removed.version
        assert cleaned[0].manifest == removed.manifest
        with pytest.raises(PackNotEnabled, match="removed"):
            await service.materialize_template(WS_A, PackId.PRODUCT)
        # The tombstone retains the snapshot: what this Workspace activated
        # stays provable after the pack is gone — that is what keeps the
        # historical template/catalog interpretable.
        tombstone = await service.record(WS_A, PackId.PRODUCT)
        assert tombstone is not None
        assert tombstone.manifest == snapshot_pack(PackRegistry.builtin().get(PackId.PRODUCT))
        assert (
            template.content_hash
            == pack_graph_template(
                PackRegistry.builtin().get(PackId.PRODUCT), workspace_id=WS_A
            ).content_hash
        )
        assert catalog.pack_version == "1.0.0"
        # Removal is a tombstone, not a deletion: the trail survives.
        kinds = [t.kind for t in await service.transitions(WS_A, PackId.PRODUCT)]
        assert kinds == [
            PackTransitionKind.ENABLE,
            PackTransitionKind.REMOVE,
        ]

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_failed_cleanup_persists_nothing(self, activated: Any) -> None:
        service, _template, _catalog = activated

        def explodes(record: Any) -> None:
            raise RuntimeError("asset store unreachable")

        with pytest.raises(RuntimeError, match="asset store unreachable"):
            await service.remove_pack(
                WS_A, PackId.PRODUCT, actor=ACTOR, reason="offboard", owned_asset_cleanup=explodes
            )
        record = await service.record(WS_A, PackId.PRODUCT)
        assert record is not None and record.state is PackLifecycleState.ENABLED
        assert len(await service.transitions(WS_A, PackId.PRODUCT)) == 1

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_reenable_after_removal_is_a_fresh_activation(self, activated: Any) -> None:
        service, _template, _catalog = activated
        await service.remove_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="offboard")
        registry_moves = _service(store=service._store, registry=_registry_with(_release("2.0.0")))
        fresh = await registry_moves.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="return", authorized_backends=GRANTS
        )
        # A post-removal activation takes the current registry release.
        assert fresh.version == "2.0.0"
        assert fresh.activated_at == fresh.updated_at
        kinds = [t.kind for t in await registry_moves.transitions(WS_A, PackId.PRODUCT)]
        assert kinds[0] is PackTransitionKind.ENABLE and kinds[-1] is PackTransitionKind.ENABLE
        assert kinds[1] is PackTransitionKind.REMOVE

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_remove_twice_and_remove_unactivated_are_refused(self, activated: Any) -> None:
        service, _template, _catalog = activated
        await service.remove_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="offboard")
        with pytest.raises(InvalidLifecycleOperation, match="already removed"):
            await service.remove_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="again")
        with pytest.raises(PackRegistryUpgradeUnavailable, match="no activation"):
            await service.remove_pack(WS_B, PackId.PRODUCT, actor=ACTOR, reason="nothing there")


# --- AC-5: dependencies and authority re-evaluated on upgrade ----------------


class TestUpgradeReevaluatesDependencyAndAuthority:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_enable_requires_every_declared_backend(self) -> None:
        service = _service()
        # The default (empty) grant authorizes nothing: fail closed.
        with pytest.raises(PackUpgradeBlocked, match="has not authorized: builders, canvas"):
            await service.enable_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="r")
        with pytest.raises(PackUpgradeBlocked, match="has not authorized: canvas"):
            await service.enable_pack(
                WS_A,
                PackId.PRODUCT,
                actor=ACTOR,
                reason="r",
                authorized_backends={ExecuteBackend.BUILDERS},
            )
        assert await service.record(WS_A, PackId.PRODUCT) is None

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_upgrade_blocked_until_the_new_backend_is_authorized(self) -> None:
        # 1.1.0 adds `media` to the product pack's dependency surface.
        store = InMemoryPackLifecycleStore()
        service = _service(store=store)
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        moved = _service(
            store=store,
            registry=_registry_with(_release("1.1.0", add_backend=ExecuteBackend.MEDIA)),
        )
        preflight = await moved.preflight_upgrade(WS_A, PackId.PRODUCT, authorized_backends=GRANTS)
        assert not preflight.can_upgrade
        assert preflight.new_backends == (ExecuteBackend.MEDIA,)
        assert preflight.unauthorized_backends == (ExecuteBackend.MEDIA,)
        assert any("media" in reason for reason in preflight.blocked_by)
        with pytest.raises(PackUpgradeBlocked, match="media"):
            await moved.upgrade_pack(
                WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
            )
        assert (await service.record(WS_A, PackId.PRODUCT)).version == "1.0.0"
        # The Workspace grants the new backend; the upgrade now passes.
        await moved.upgrade_pack(
            WS_A,
            PackId.PRODUCT,
            actor=ACTOR,
            reason="grant landed",
            authorized_backends={*GRANTS, ExecuteBackend.MEDIA},
        )
        assert (await service.record(WS_A, PackId.PRODUCT)).version == "1.1.0"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_upgrade_blocked_while_configuration_outlives_the_release(self) -> None:
        service = _service()
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        await service.configure_pack(
            WS_A,
            PackId.PRODUCT,
            WorkspacePackConfiguration(rubric_dimension_ids=("channel_fit",)),
            actor=ACTOR,
            reason="focus",
        )
        moved = _service(
            store=service._store,
            registry=_registry_with(_release("1.1.0", drop_dimension="channel_fit")),
        )
        preflight = await moved.preflight_upgrade(WS_A, PackId.PRODUCT, authorized_backends=GRANTS)
        assert preflight.dropped_rubric_dimensions == ("channel_fit",)
        assert not preflight.can_upgrade
        with pytest.raises(PackUpgradeBlocked, match="channel_fit"):
            await moved.upgrade_pack(
                WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
            )
        # The operator migrates the configuration in the same audited step.
        upgraded = await moved.upgrade_pack(
            WS_A,
            PackId.PRODUCT,
            actor=ACTOR,
            reason="migrate config with the release",
            configuration=WorkspacePackConfiguration(rubric_dimension_ids=("claim_evidence",)),
            authorized_backends=GRANTS,
        )
        assert upgraded.version == "1.1.0"
        assert upgraded.configuration.rubric_dimension_ids == ("claim_evidence",)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_resume_rechecks_authority_revoked_while_disabled(self) -> None:
        service = _service()
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        await service.disable_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="pause")
        # The default (empty) grant authorizes nothing: a resume cannot
        # silently reactivate a dependency the Workspace no longer holds.
        with pytest.raises(PackUpgradeBlocked, match="has not authorized"):
            await service.enable_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="resume")
        record = await service.record(WS_A, PackId.PRODUCT)
        assert record is not None and record.state is PackLifecycleState.DISABLED
        assert len(await service.transitions(WS_A, PackId.PRODUCT)) == 2


# --- AC-6: audited, atomic, restart-safe -------------------------------------


class _CommitSpyStore(InMemoryPackLifecycleStore):
    """Counts `commit` calls: one per lifecycle operation, record+transition."""

    def __init__(self) -> None:
        super().__init__()
        self.commits: list[tuple[Any, Any]] = []

    async def commit(self, record: Any, transition: Any) -> None:
        self.commits.append((record, transition))
        await super().commit(record, transition)


class TestTransitionsAreAuditedAtomicAndRestartSafe:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_every_operation_commits_one_record_and_one_transition(self) -> None:
        store = _CommitSpyStore()
        service = _service(store=store)
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        await service.configure_pack(
            WS_A,
            PackId.PRODUCT,
            WorkspacePackConfiguration(settings={"tone": "plain"}),
            actor=ACTOR,
            reason="r",
        )
        await service.disable_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="r")
        await service.remove_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="r")
        assert len(store.commits) == 4
        for record, transition in store.commits:
            # Record and evidence commit together — the atomicity seam.
            assert (record.workspace_id, record.pack_id, record.state) == (
                WS_A,
                PackId.PRODUCT,
                transition.to_state,
            )
            assert transition.seq >= 1 and transition.reason == "r" and transition.actor == ACTOR
        kinds = [transition.kind for _record, transition in store.commits]
        assert kinds == [
            PackTransitionKind.ENABLE,
            PackTransitionKind.CONFIGURE,
            PackTransitionKind.DISABLE,
            PackTransitionKind.REMOVE,
        ]

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_trail_is_ordered_complete_and_version_aware(self) -> None:
        service = _service()
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        moved = _service(store=service._store, registry=_registry_with(_release("1.1.0")))
        await moved.upgrade_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="new release", authorized_backends=GRANTS
        )
        await moved.disable_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="pause")
        trail = await service.transitions(WS_A, PackId.PRODUCT)
        assert [(t.seq, t.kind.value) for t in trail] == [
            (1, "enable"),
            (2, "upgrade"),
            (3, "disable"),
        ]
        upgrade_transition = trail[1]
        assert (upgrade_transition.from_version, upgrade_transition.to_version) == (
            "1.0.0",
            "1.1.0",
        )
        # Every row carries the full attribution the issue's audit criterion
        # names: actor, timestamps, states and versions.
        for transition in trail:
            assert transition.actor == ACTOR and transition.reason
            assert transition.at.isoformat().startswith("2026-10-06")
            assert transition.from_state and transition.to_state

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("integration")
    async def test_service_holds_no_state_so_a_restart_over_one_store_sees_it_all(self) -> None:
        store = InMemoryPackLifecycleStore()
        first = _service(store=store)
        await first.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        await first.disable_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="r")
        # A "restarted" deployment: a brand-new service over the same store.
        second = _service(store=store)
        record = await second.record(WS_A, PackId.PRODUCT)
        assert record is not None and record.state is PackLifecycleState.DISABLED
        assert len(await second.transitions(WS_A, PackId.PRODUCT)) == 2
        with pytest.raises(PackNotEnabled):
            await second.materialize_template(WS_A, PackId.PRODUCT)

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_operations_are_refused_without_full_attribution(self) -> None:
        service = _service()
        for kwargs in (
            {"actor": "", "reason": "r"},
            {"actor": "  ", "reason": "r"},
            {"actor": ACTOR, "reason": ""},
        ):
            with pytest.raises(PackLifecycleError, match="required"):
                await service.enable_pack(
                    WS_A, PackId.PRODUCT, authorized_backends=GRANTS, **kwargs
                )
        with pytest.raises(PackLifecycleError, match="workspace_id is required"):
            await service.enable_pack("  ", PackId.PRODUCT, actor=ACTOR, reason="r")
        assert await service.record(WS_A, PackId.PRODUCT) is None

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_new_use_refuses_to_materialize_tampered_evidence(self) -> None:
        service = _service()
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        store = service._store
        assert isinstance(store, InMemoryPackLifecycleStore)
        record = await store.get_record(WS_A, PackId.PRODUCT)
        assert record is not None
        tampered = replace(record, manifest=replace(record.manifest, body='{"pack_id": "product"}'))
        store._records[(WS_A, PackId.PRODUCT)] = tampered
        with pytest.raises(SnapshotIntegrityError, match="digest mismatch"):
            await service.materialize_template(WS_A, PackId.PRODUCT)
        with pytest.raises(SnapshotIntegrityError):
            await service.instantiate_catalog(
                WS_A, PackId.PRODUCT, goal_id=GOAL_ID, goal_revision=1
            )


# --- contract edges ----------------------------------------------------------


class TestLifecycleContractEdges:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_enable_twice_is_refused_not_duplicated(self) -> None:
        service = _service()
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        with pytest.raises(PackLifecycleError, match="already enabled"):
            await service.enable_pack(
                WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
            )
        assert len(await service.transitions(WS_A, PackId.PRODUCT)) == 1

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_disable_and_configure_require_an_enabled_record(self) -> None:
        service = _service()
        with pytest.raises(PackNotEnabled, match="not activated"):
            await service.disable_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="r")
        with pytest.raises(PackNotEnabled, match="not activated"):
            await service.configure_pack(
                WS_A, PackId.PRODUCT, WorkspacePackConfiguration(), actor=ACTOR, reason="r"
            )
        await service.enable_pack(
            WS_A, PackId.PRODUCT, actor=ACTOR, reason="r", authorized_backends=GRANTS
        )
        await service.disable_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="r")
        with pytest.raises(InvalidLifecycleOperation, match="state is disabled"):
            await service.disable_pack(WS_A, PackId.PRODUCT, actor=ACTOR, reason="r")
        with pytest.raises(InvalidLifecycleOperation, match="state is disabled"):
            await service.configure_pack(
                WS_A, PackId.PRODUCT, WorkspacePackConfiguration(), actor=ACTOR, reason="r"
            )

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_pack_versions_must_be_release_triples(self) -> None:
        from maistro_design.packs import parse_pack_version

        assert parse_pack_version("1.2.3") == (1, 2, 3)
        with pytest.raises(PackLifecycleError, match="malformed pack version"):
            parse_pack_version("1.2")
        # The manifest contract enforces the same grammar at parse time.
        with pytest.raises(Exception, match="String should match pattern"):
            DomainPack.model_validate(
                {
                    **PackRegistry.builtin().get(PackId.PRODUCT).model_dump(mode="json"),
                    "version": "not-a-version",
                }
            )
