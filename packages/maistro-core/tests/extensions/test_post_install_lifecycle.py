"""The post-install extension lifecycle (#954, under M9-B/#939).

These tests pin the governed post-install surface — disable, enable,
rollback, remove and operator pins — against reachable production behavior.
The load-bearing properties:

* disabling stops a version being served while preserving its frozen grant,
  immutable snapshot and full audit trail;
* re-enabling re-serves an already-activated artifact without running the
  loader again and never moves a version silently over a live one;
* rollback restores a previously authorized version under its frozen grant,
  never executes code and never widens authority;
* removal is terminal: the record never reactivates, yet its evidence stays
  queryable (append-only stores);
* a pin is an explicit, audited operator hold that fences version moves
  (install of another version, rollback away) but never fences disabling or
  removal, so incident response is never blocked;
* superseding an active version on upgrade keeps exactly one ACTIVE record
  per (scope, extension) and lands every step on the audit trail.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace

import pytest

from maistro.extensions import (
    InMemoryExtensionStore,
    InvalidTransition,
    TrustPolicy,
    UnknownInstall,
    VersionPinned,
)
from maistro.extensions.service import (
    ExtensionInstallService,
    LoadedExtension,
)
from maistro.extensions.types import (
    ExtensionPackage,
    ExtensionScope,
    ExtensionState,
    TrustClaim,
)

PAYLOAD_V1 = b"lifecycle-payload-1.0.0"
PAYLOAD_V2 = b"lifecycle-payload-1.1.0"
PAYLOAD_V3 = b"lifecycle-payload-1.2.0"

TRUST = TrustClaim(publisher_id="acme", signature_present=True, signer_key_id="key-1")
POLICY = TrustPolicy(
    trusted_publishers=frozenset({"acme"}),
    require_signature=True,
    allowed_signer_keys=frozenset({"key-1"}),
)
SCOPE = ExtensionScope(org_id="org-1", workspace_id="ws-1")
OTHER_SCOPE = ExtensionScope(org_id="org-1", workspace_id="ws-2")

_ids = iter(f"install-{n}" for n in range(10000))


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_bytes(*, version: str, payload: bytes, permissions: tuple[str, ...]) -> bytes:
    document = {
        "manifest_version": 1,
        "id": "acme.chart_tools",
        "name": "Chart Tools",
        "version": version,
        "publisher": "acme",
        "api_version": "1.0.0",
        "permissions": list(permissions),
        "entry_points": [{"name": "main", "module": "acme_chart.main", "attribute": "activate"}],
        "artifact": {"sha256": _digest(payload), "size": len(payload)},
        "dependencies": [],
    }
    return json.dumps(document).encode("utf-8")


class RecordingLoader:
    """Loader spy: every activation is recorded, so tests can prove when
    code ran — and, critically, when a lifecycle op could not have run it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes]] = []

    async def load(self, record, payload: bytes) -> LoadedExtension:  # type: ignore[no-untyped-def]
        self.calls.append((record.install_id, bytes(payload)))
        return LoadedExtension(extension_id=record.extension_id, version=record.version)


def make_service() -> tuple[ExtensionInstallService, InMemoryExtensionStore, RecordingLoader]:
    loader = RecordingLoader()
    store = InMemoryExtensionStore()
    service = ExtensionInstallService(
        store,
        loader=loader,
        trust_policy=POLICY,
        platform_api_version="1.0.0",
        clock=lambda: __import__("datetime").datetime(
            2026, 10, 8, tzinfo=__import__("datetime").UTC
        ),
        install_id_factory=lambda: f"install-{next(_ids)}",
    )
    return service, store, loader


async def install_version(
    service: ExtensionInstallService,
    *,
    version: str,
    payload: bytes,
    permissions: tuple[str, ...] = ("network.http",),
    scope: ExtensionScope = SCOPE,
    actor: str = "operator-1",
) -> object:
    """inspect → authorize → install one version; returns the ACTIVE record."""
    record = await service.inspect(
        actor=actor,
        scope=scope,
        package=ExtensionPackage(
            manifest_bytes=manifest_bytes(
                version=version, payload=payload, permissions=permissions
            ),
            payload=payload,
        ),
        trust_evidence=TRUST,
    )
    await service.authorize(
        record.install_id, actor=actor, scope=scope, approve=True, reason="reviewed"
    )
    return await service.install(record.install_id, actor=actor, scope=scope, payload=payload)


class TestDisable:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_disable_stops_serving_and_preserves_grant_and_history(self) -> None:
        service, store, _loader = make_service()
        active = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        history_before = len(await store.transitions_for(active.install_id))  # type: ignore[attr-defined]

        disabled = await service.disable(
            active.install_id,  # type: ignore[attr-defined]
            actor="operator-1",
            scope=SCOPE,
            reason="incident triage",
        )

        assert disabled.state is ExtensionState.DISABLED
        assert disabled.granted_permissions == active.granted_permissions  # type: ignore[attr-defined]
        assert await store.active_record(SCOPE, "acme.chart_tools") is None
        assert "acme.chart_tools" not in await store.installed_versions(SCOPE)
        history = await store.transitions_for(active.install_id)  # type: ignore[attr-defined]
        assert len(history) == history_before + 1
        assert history[-1].to_state is ExtensionState.DISABLED
        assert history[-1].actor == "operator-1"
        assert "incident triage" in history[-1].reason

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_disable_requires_an_active_record(self) -> None:
        service, _store, _loader = make_service()
        awaiting = await service.inspect(
            actor="operator-1",
            scope=SCOPE,
            package=ExtensionPackage(
                manifest_bytes=manifest_bytes(
                    version="1.0.0", payload=PAYLOAD_V1, permissions=("network.http",)
                ),
                payload=PAYLOAD_V1,
            ),
            trust_evidence=TRUST,
        )
        with pytest.raises(InvalidTransition, match="only an active record"):
            await service.disable(
                awaiting.install_id, actor="operator-1", scope=SCOPE, reason="not active"
            )

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_disable_is_scope_contained(self) -> None:
        service, _store, _loader = make_service()
        active = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        with pytest.raises(UnknownInstall):
            await service.disable(
                active.install_id,  # type: ignore[attr-defined]
                actor="operator-1",
                scope=OTHER_SCOPE,
                reason="cross-workspace attempt",
            )


class TestEnable:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_enable_re_serves_without_rerunning_the_loader(self) -> None:
        service, store, loader = make_service()
        active = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        loader_calls_at_activation = len(loader.calls)
        await service.disable(
            active.install_id,
            actor="operator-1",
            scope=SCOPE,
            reason="triage",  # type: ignore[attr-defined]
        )

        reenabled = await service.enable(
            active.install_id,
            actor="operator-1",
            scope=SCOPE,
            reason="triage clean",  # type: ignore[attr-defined]
        )

        assert reenabled.state is ExtensionState.ACTIVE
        assert reenabled.install_attempts == active.install_attempts  # type: ignore[attr-defined]
        assert len(loader.calls) == loader_calls_at_activation, (
            "re-enabling must re-serve the already-activated artifact; the "
            "loader is the only code-execution seam and must never re-run"
        )
        assert await store.active_record(SCOPE, "acme.chart_tools") is reenabled

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_enable_over_a_live_version_is_a_refused_version_move(self) -> None:
        service, store, _loader = make_service()
        v1 = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        await install_version(service, version="1.1.0", payload=PAYLOAD_V2)  # supersedes v1

        # The superseded record cannot be re-enabled at all — the state machine
        # only re-serves disabled records.
        with pytest.raises(InvalidTransition, match="superseded; only a disabled record"):
            await service.enable(
                v1.install_id,
                actor="operator-1",
                scope=SCOPE,
                reason="silent swap",  # type: ignore[attr-defined]
            )

        # Reach the version-move guard directly: roll back to v1 (1.1.0 becomes
        # DISABLED while 1.0.0 is live), then try to re-enable it over the
        # live version.
        v2 = await store.latest_record(SCOPE, "acme.chart_tools", "1.1.0")
        assert v2 is not None
        await service.rollback(
            actor="operator-1",
            scope=SCOPE,
            extension_id="acme.chart_tools",
            to_version="1.0.0",
            reason="back to 1.0.0",
        )
        with pytest.raises(InvalidTransition, match="version move"):
            await service.enable(
                v2.install_id,
                actor="operator-1",
                scope=SCOPE,
                reason="over a live version",  # type: ignore[union-attr]
            )
        current = await store.active_record(SCOPE, "acme.chart_tools")
        assert current is not None and current.version == "1.0.0"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_enable_requires_a_disabled_record(self) -> None:
        service, _store, _loader = make_service()
        active = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        with pytest.raises(InvalidTransition, match="only a disabled record"):
            await service.enable(
                active.install_id,
                actor="operator-1",
                scope=SCOPE,
                reason="already active",  # type: ignore[attr-defined]
            )


class TestRemove:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_remove_is_terminal_but_evidence_outlives_it(self) -> None:
        service, store, loader = make_service()
        active = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        history_before = len(await store.transitions_for(active.install_id))  # type: ignore[attr-defined]

        removed = await service.remove(
            active.install_id,
            actor="operator-1",
            scope=SCOPE,
            reason="retired",  # type: ignore[attr-defined]
        )

        assert removed.state is ExtensionState.REMOVED
        assert await store.active_record(SCOPE, "acme.chart_tools") is None
        # Append-only: the record and its trail remain queryable.
        assert await store.get_record(active.install_id) is removed  # type: ignore[attr-defined]
        assert len(await store.transitions_for(active.install_id)) == history_before + 1  # type: ignore[attr-defined]
        # Terminal: no lifecycle op can resurrect it, and the loader never ran.
        loader_calls = len(loader.calls)
        with pytest.raises(InvalidTransition):
            await service.enable(
                removed.install_id,
                actor="operator-1",
                scope=SCOPE,
                reason="resurrect",  # type: ignore[attr-defined]
            )
        with pytest.raises(InvalidTransition):
            await service.disable(
                removed.install_id,
                actor="operator-1",
                scope=SCOPE,
                reason="again",  # type: ignore[attr-defined]
            )
        assert len(loader.calls) == loader_calls

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_fresh_install_of_a_removed_version_is_a_new_track(self) -> None:
        service, _store, _loader = make_service()
        first = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        await service.remove(
            first.install_id,
            actor="operator-1",
            scope=SCOPE,
            reason="retired",  # type: ignore[attr-defined]
        )

        fresh = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)

        assert fresh.install_id != first.install_id  # type: ignore[attr-defined]
        assert fresh.state is ExtensionState.ACTIVE  # type: ignore[attr-defined]
        assert fresh.granted_permissions == first.granted_permissions  # type: ignore[attr-defined]

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_only_served_records_can_be_removed(self) -> None:
        service, _store, _loader = make_service()
        awaiting = await service.inspect(
            actor="operator-1",
            scope=SCOPE,
            package=ExtensionPackage(
                manifest_bytes=manifest_bytes(
                    version="1.0.0", payload=PAYLOAD_V1, permissions=("network.http",)
                ),
                payload=PAYLOAD_V1,
            ),
            trust_evidence=TRUST,
        )
        with pytest.raises(InvalidTransition, match="only a served record"):
            await service.remove(
                awaiting.install_id, actor="operator-1", scope=SCOPE, reason="not served"
            )


class TestRollback:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_restores_a_prior_authorized_version(self) -> None:
        service, store, loader = make_service()
        v1 = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        v2 = await install_version(
            service,
            version="1.1.0",
            payload=PAYLOAD_V2,
            permissions=("network.http", "storage.workspace"),
        )
        loader_calls = len(loader.calls)

        restored = await service.rollback(
            actor="operator-1",
            scope=SCOPE,
            extension_id="acme.chart_tools",
            to_version="1.0.0",
            reason="1.1.0 misbehaves",
        )

        assert restored.version == "1.0.0"
        assert restored.state is ExtensionState.ACTIVE
        # The restored grant is the frozen one: exactly what 1.0.0 was given.
        assert restored.granted_permissions == v1.granted_permissions
        retired = await store.latest_record(SCOPE, "acme.chart_tools", "1.1.0")
        assert retired is not None and retired.state is ExtensionState.DISABLED
        assert retired.install_id == v2.install_id
        assert await store.active_record(SCOPE, "acme.chart_tools") is restored
        # Rollback never executes code.
        assert len(loader.calls) == loader_calls

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_target_must_be_restorable(self) -> None:
        service, _store, _loader = make_service()
        v1 = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        await install_version(service, version="1.1.0", payload=PAYLOAD_V2)

        with pytest.raises(UnknownInstall):
            await service.rollback(
                actor="operator-1",
                scope=SCOPE,
                extension_id="acme.chart_tools",
                to_version="9.9.9",
                reason="no such version",
            )
        await service.remove(
            v1.install_id,
            actor="operator-1",
            scope=SCOPE,
            reason="retired",  # type: ignore[attr-defined]
        )
        with pytest.raises(InvalidTransition, match="removed"):
            await service.rollback(
                actor="operator-1",
                scope=SCOPE,
                extension_id="acme.chart_tools",
                to_version="1.0.0",
                reason="removed is terminal",
            )

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_target_is_scope_contained(self) -> None:
        service, _store, _loader = make_service()
        await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        await install_version(service, version="1.1.0", payload=PAYLOAD_V2)
        # Another workspace has neither an active version nor any record; the
        # rollback is refused on both counts, never leaking the other scope's
        # records as targets.
        with pytest.raises(InvalidTransition, match="no active install"):
            await service.rollback(
                actor="operator-1",
                scope=OTHER_SCOPE,
                extension_id="acme.chart_tools",
                to_version="1.0.0",
                reason="cross-workspace attempt",
            )

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_requires_an_active_version_to_roll_back_from(self) -> None:
        service, _store, _loader = make_service()
        active = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        await service.disable(
            active.install_id,
            actor="operator-1",
            scope=SCOPE,
            reason="down",  # type: ignore[attr-defined]
        )
        with pytest.raises(InvalidTransition, match="no active install"):
            await service.rollback(
                actor="operator-1",
                scope=SCOPE,
                extension_id="acme.chart_tools",
                to_version="1.0.0",
                reason="nothing active",
            )

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_to_the_active_version_is_refused(self) -> None:
        service, _store, _loader = make_service()
        await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        with pytest.raises(InvalidTransition, match="nothing to roll back to"):
            await service.rollback(
                actor="operator-1",
                scope=SCOPE,
                extension_id="acme.chart_tools",
                to_version="1.0.0",
                reason="same version",
            )

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_of_a_disabled_prior_version_works(self) -> None:
        """Rollback restores a DISABLED (not only SUPERSEDED) prior version."""
        service, store, _loader = make_service()
        await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        v2 = await install_version(service, version="1.1.0", payload=PAYLOAD_V2)
        # Roll 1.0.0 back in; 1.1.0 becomes the DISABLED prior.
        await service.rollback(
            actor="operator-1",
            scope=SCOPE,
            extension_id="acme.chart_tools",
            to_version="1.0.0",
            reason="1.1.0 misbehaves",
        )
        retired_v2 = await store.latest_record(SCOPE, "acme.chart_tools", "1.1.0")
        assert retired_v2 is not None
        assert retired_v2.state is ExtensionState.DISABLED
        assert retired_v2.install_id == v2.install_id

        restored = await service.rollback(
            actor="operator-1",
            scope=SCOPE,
            extension_id="acme.chart_tools",
            to_version="1.1.0",
            reason="triage done; back to 1.1.0",
        )
        assert restored.version == "1.1.0"
        assert restored.state is ExtensionState.ACTIVE
        assert restored.granted_permissions == v2.granted_permissions


class TestPins:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_pin_fences_install_of_another_version(self) -> None:
        service, store, loader = make_service()
        v1 = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        await service.set_pinned(
            v1.install_id,
            actor="operator-1",
            scope=SCOPE,
            pinned=True,
            reason="freeze",  # type: ignore[attr-defined]
        )
        candidate = await service.inspect(
            actor="operator-1",
            scope=SCOPE,
            package=ExtensionPackage(
                manifest_bytes=manifest_bytes(
                    version="1.1.0", payload=PAYLOAD_V2, permissions=("network.http",)
                ),
                payload=PAYLOAD_V2,
            ),
            trust_evidence=TRUST,
        )
        candidate = await service.authorize(
            candidate.install_id, actor="operator-1", scope=SCOPE, approve=True, reason="ok"
        )

        with pytest.raises(VersionPinned, match="pinned"):
            await service.install(
                candidate.install_id, actor="operator-1", scope=SCOPE, payload=PAYLOAD_V2
            )

        # Fenced before any state moved: the candidate stays AUTHORIZED, the
        # pinned version stays ACTIVE, no code ran.
        assert candidate.state is ExtensionState.AUTHORIZED
        current = await store.active_record(SCOPE, "acme.chart_tools")
        assert current is not None and current.version == "1.0.0"
        assert len(loader.calls) == 1

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_pin_fences_rollback_until_explicit_unpin(self) -> None:
        service, store, _loader = make_service()
        await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        await install_version(service, version="1.1.0", payload=PAYLOAD_V2)
        active = await store.active_record(SCOPE, "acme.chart_tools")
        assert active is not None
        await service.set_pinned(
            active.install_id, actor="operator-1", scope=SCOPE, pinned=True, reason="freeze"
        )

        with pytest.raises(VersionPinned):
            await service.rollback(
                actor="operator-1",
                scope=SCOPE,
                extension_id="acme.chart_tools",
                to_version="1.0.0",
                reason="fenced while pinned",
            )
        still = await store.active_record(SCOPE, "acme.chart_tools")
        assert still is not None and still.version == "1.1.0" and still.pinned

        await service.set_pinned(
            active.install_id, actor="operator-1", scope=SCOPE, pinned=False, reason="freeze lifted"
        )
        restored = await service.rollback(
            actor="operator-1",
            scope=SCOPE,
            extension_id="acme.chart_tools",
            to_version="1.0.0",
            reason="explicit rollback after unpin",
        )
        assert restored.version == "1.0.0"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_pin_is_an_audited_idempotent_same_state_decision(self) -> None:
        service, store, _loader = make_service()
        active = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        history_before = len(await store.transitions_for(active.install_id))  # type: ignore[attr-defined]

        pinned = await service.set_pinned(
            active.install_id,
            actor="operator-1",
            scope=SCOPE,
            pinned=True,
            reason="hold",  # type: ignore[attr-defined]
        )
        assert pinned.pinned and pinned.state is ExtensionState.ACTIVE
        trail = await store.transitions_for(active.install_id)  # type: ignore[attr-defined]
        assert len(trail) == history_before + 1
        assert trail[-1].from_state is trail[-1].to_state is ExtensionState.ACTIVE
        assert trail[-1].reason.startswith("pin:")

        # Idempotent re-pin: no new trail row, same record returned.
        again = await service.set_pinned(
            active.install_id,
            actor="operator-2",
            scope=SCOPE,
            pinned=True,
            reason="redundant",  # type: ignore[attr-defined]
        )
        assert again is pinned
        assert len(await store.transitions_for(active.install_id)) == history_before + 1  # type: ignore[attr-defined]

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_pin_requires_a_served_record(self) -> None:
        service, _store, _loader = make_service()
        awaiting = await service.inspect(
            actor="operator-1",
            scope=SCOPE,
            package=ExtensionPackage(
                manifest_bytes=manifest_bytes(
                    version="1.0.0", payload=PAYLOAD_V1, permissions=("network.http",)
                ),
                payload=PAYLOAD_V1,
            ),
            trust_evidence=TRUST,
        )
        with pytest.raises(InvalidTransition, match="only a served record"):
            await service.set_pinned(
                awaiting.install_id,
                actor="operator-1",
                scope=SCOPE,
                pinned=True,
                reason="not served",
            )

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_pin_never_fences_disable_or_remove(self) -> None:
        """Incident response is never blocked by a pin."""
        service, store, _loader = make_service()
        active = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        await service.set_pinned(
            active.install_id,
            actor="operator-1",
            scope=SCOPE,
            pinned=True,
            reason="freeze",  # type: ignore[attr-defined]
        )
        await service.disable(
            active.install_id,
            actor="responder-9",
            scope=SCOPE,
            reason="kill switch",  # type: ignore[attr-defined]
        )
        # A pinned DISABLED record can still be removed.
        removed = await service.remove(
            active.install_id,
            actor="responder-9",
            scope=SCOPE,
            reason="purge",  # type: ignore[attr-defined]
        )
        assert removed.state is ExtensionState.REMOVED
        assert await store.active_record(SCOPE, "acme.chart_tools") is None


class TestSupersedeOnActivation:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_activation_supersedes_the_prior_active_version(self) -> None:
        service, store, _loader = make_service()
        v1 = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        history_before = len(await store.transitions_for(v1.install_id))  # type: ignore[attr-defined]

        v2 = await install_version(service, version="1.1.0", payload=PAYLOAD_V2)

        superseded = await store.get_record(v1.install_id)
        assert superseded is not None and superseded.state is ExtensionState.SUPERSEDED
        trail = await store.transitions_for(v1.install_id)  # type: ignore[attr-defined]
        assert len(trail) == history_before + 1
        assert trail[-1].to_state is ExtensionState.SUPERSEDED
        assert "1.1.0" in trail[-1].reason
        # Exactly one ACTIVE record per (scope, extension).
        versions = await store.installed_versions(SCOPE)
        assert versions == {"acme.chart_tools": "1.1.0"}
        assert v2.state is ExtensionState.ACTIVE  # type: ignore[attr-defined]

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_superseded_prior_can_return_only_via_explicit_decisions(self) -> None:
        service, _store, _loader = make_service()
        v1 = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        await install_version(service, version="1.1.0", payload=PAYLOAD_V2)
        with pytest.raises(InvalidTransition):
            await service.enable(
                v1.install_id,
                actor="operator-1",
                scope=SCOPE,
                reason="over a live version",  # type: ignore[attr-defined]
            )
        restored = await service.rollback(
            actor="operator-1",
            scope=SCOPE,
            extension_id="acme.chart_tools",
            to_version="1.0.0",
            reason="explicit rollback",
        )
        assert restored.version == "1.0.0"


class TestDecisionDiscipline:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_actor_and_reason_are_required_on_every_lifecycle_op(self) -> None:
        service, _store, _loader = make_service()
        active = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        install_id = active.install_id  # type: ignore[attr-defined]
        blank = "   "
        with pytest.raises(ValueError, match="actor"):
            await service.disable(install_id, actor=blank, scope=SCOPE, reason="r")
        with pytest.raises(ValueError, match="reason"):
            await service.disable(install_id, actor="a", scope=SCOPE, reason=blank)
        with pytest.raises(ValueError, match="actor"):
            await service.enable(install_id, actor=blank, scope=SCOPE, reason="r")
        with pytest.raises(ValueError, match="reason"):
            await service.enable(install_id, actor="a", scope=SCOPE, reason=blank)
        with pytest.raises(ValueError, match="actor"):
            await service.remove(install_id, actor=blank, scope=SCOPE, reason="r")
        with pytest.raises(ValueError, match="reason"):
            await service.remove(install_id, actor="a", scope=SCOPE, reason=blank)
        with pytest.raises(ValueError, match="actor"):
            await service.rollback(
                actor=blank,
                scope=SCOPE,
                extension_id="acme.chart_tools",
                to_version="1.0.0",
                reason="r",
            )
        with pytest.raises(ValueError, match="reason"):
            await service.rollback(
                actor="a",
                scope=SCOPE,
                extension_id="acme.chart_tools",
                to_version="1.0.0",
                reason=blank,
            )
        with pytest.raises(ValueError, match="actor"):
            await service.set_pinned(install_id, actor=blank, scope=SCOPE, pinned=True, reason="r")
        with pytest.raises(ValueError, match="reason"):
            await service.set_pinned(install_id, actor="a", scope=SCOPE, pinned=True, reason=blank)


class TestStorePointerHygiene:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_clear_active_only_drops_its_own_pointer(self) -> None:
        """disable/remove must not clobber a pointer a concurrent activation
        already moved to a different record."""
        service, store, _loader = make_service()
        v1 = await install_version(service, version="1.0.0", payload=PAYLOAD_V1)
        v2 = await install_version(service, version="1.1.0", payload=PAYLOAD_V2)
        assert await store.active_record(SCOPE, "acme.chart_tools") is v2  # type: ignore[arg-type]

        # Clearing the superseded record must leave the live pointer alone.
        await store.clear_active(replace(v1, state=ExtensionState.SUPERSEDED))  # type: ignore[arg-type]
        assert await store.active_record(SCOPE, "acme.chart_tools") is v2  # type: ignore[arg-type]

        # Clearing the live record drops the pointer.
        await store.clear_active(v2)  # type: ignore[arg-type]
        assert await store.active_record(SCOPE, "acme.chart_tools") is None


class TestConcurrentActivation:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_concurrent_installs_of_one_extension_leave_exactly_one_active(self) -> None:
        """Two separately authorized installs of the same scoped extension race:
        their distinct install-id record locks never contend, so the pointer
        swap and supersede must be serialized per (scope, extension). The
        loser must end SUPERSEDED — never ACTIVE under a pointer naming the
        winner."""
        service, store, _loader = make_service()

        # The in-memory store has no suspension points, so the read-prior →
        # set-active → supersede tail is accidentally atomic in a single event
        # loop. Yield inside ``active_record`` and ``set_active`` to open
        # exactly the window the review describes: both racers capture the
        # same prior active record before either finishes its pointer swap,
        # and each supersedes only that shared prior.
        original_active_record = store.active_record
        original_set_active = store.set_active

        async def yielding_active_record(scope: object, extension_id: str) -> object:
            await asyncio.sleep(0)
            return await original_active_record(scope, extension_id)  # type: ignore[arg-type]

        async def yielding_set_active(record: object) -> None:
            await asyncio.sleep(0)
            await original_set_active(record)  # type: ignore[arg-type]

        store.active_record = yielding_active_record  # type: ignore[method-assign]
        store.set_active = yielding_set_active  # type: ignore[method-assign]

        async def authorize_then_install(version: str, payload: bytes) -> object:
            record = await service.inspect(
                actor="operator-1",
                scope=SCOPE,
                package=ExtensionPackage(
                    manifest_bytes=manifest_bytes(
                        version=version,
                        payload=payload,
                        permissions=("network.http",),
                    ),
                    payload=payload,
                ),
                trust_evidence=TRUST,
            )
            await service.authorize(
                record.install_id,
                actor="operator-1",
                scope=SCOPE,
                approve=True,
                reason="ok",
            )
            return await service.install(
                record.install_id, actor="operator-1", scope=SCOPE, payload=payload
            )

        first = await authorize_then_install("1.0.0", PAYLOAD_V1)
        candidate_a, candidate_b = await asyncio.gather(
            authorize_then_install("1.1.0", PAYLOAD_V2),
            authorize_then_install("1.2.0", PAYLOAD_V3),
        )

        # Either candidate may win the race; exactly one may hold the pointer.
        pointer = await store.active_record(SCOPE, "acme.chart_tools")
        assert pointer is not None
        assert pointer.install_id in (candidate_a.install_id, candidate_b.install_id)  # type: ignore[attr-defined]
        loser_id = (
            candidate_b.install_id  # type: ignore[attr-defined]
            if pointer.install_id == candidate_a.install_id  # type: ignore[attr-defined]
            else candidate_a.install_id  # type: ignore[attr-defined]
        )
        # Re-read from the store: the records returned by ``install`` are
        # snapshots taken before any later supersede.
        loser_now = await store.get_record(loser_id)
        assert loser_now is not None and loser_now.state is ExtensionState.SUPERSEDED
        assert pointer.state is ExtensionState.ACTIVE
        first_now = await store.get_record(first.install_id)  # type: ignore[attr-defined]
        assert first_now is not None and first_now.state is ExtensionState.SUPERSEDED
        # Exactly one ACTIVE record for the (scope, extension), and it is the
        # one the pointer names.
        served = [
            record
            for record in await store.records_in_state(ExtensionState.ACTIVE)
            if record.org_id == SCOPE.org_id
            and record.workspace_id == SCOPE.workspace_id
            and record.extension_id == "acme.chart_tools"
        ]
        assert [record.install_id for record in served] == [pointer.install_id]
