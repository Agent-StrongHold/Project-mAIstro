"""The post-install extension lifecycle (#954, M9-B3).

These tests drive pin / upgrade / rollback / disable / remove end to end on
the same state machine B2 installed, and pin each acceptance criterion of
the issue against reachable production behavior:

- compatible same-authority upgrades apply without silently changing
  permissions (the grant is frozen from the immutable snapshot, and the
  authority delta of a same-authority upgrade is empty);
- broader authority always requires the explicit new authorization decision
  before the new version can activate;
- rollback either succeeds with proven-compatible state or fails before the
  first state change (digest, compatibility, pin, and broadened-authority
  refusals all leave the scope untouched);
- disable stops invocation resolution immediately while every record and
  transition survives;
- remove never deletes canonical historical evidence;
- lifecycle retries are idempotent, and the pointer/state invariants a crash
  can leave behind are repaired by the reconciliation sweep.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from maistro.extensions import (
    ArtifactMismatch,
    ExtensionLifecycleError,
    InMemoryExtensionStore,
    InvalidTransition,
    PinConflict,
    PreflightError,
    TrustPolicy,
)
from maistro.extensions.service import (
    ExtensionCodeLoader,
    ExtensionInstallService,
    LoadedExtension,
)
from maistro.extensions.types import (
    ExtensionPackage,
    ExtensionScope,
    ExtensionState,
    PinRecord,
    RemovalNote,
    TrustEvidence,
)

PAYLOAD_V1 = b"extension-payload-v1"
PAYLOAD_V2 = b"extension-payload-v2"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_bytes(
    *,
    extension_id: str = "acme.chart_tools",
    version: str = "1.4.0",
    permissions: tuple[str, ...] = ("network.http", "storage.workspace"),
    payload: bytes = PAYLOAD_V1,
    api_version: str = "1.0.0",
    publisher: str = "acme",
    dependencies: tuple[dict[str, str], ...] = (),
) -> bytes:
    """A valid manifest whose artifact claim describes ``payload`` exactly."""
    document = {
        "manifest_version": 1,
        "id": extension_id,
        "name": "Chart Tools",
        "version": version,
        "publisher": publisher,
        "api_version": api_version,
        "permissions": list(permissions),
        "entry_points": [{"name": "main", "module": "acme_chart.main", "attribute": "activate"}],
        "artifact": {"sha256": _digest(payload), "size": len(payload)},
        "dependencies": [dict(dep) for dep in dependencies],
    }
    return json.dumps(document).encode("utf-8")


class DeterministicClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class RecordingLoader:
    """Loader spy recording every activation across the whole lifecycle."""

    def __init__(self, *, fail_once: bool = False) -> None:
        self.calls: list[tuple[str, str, bytes]] = []
        self._fail_once = fail_once
        self._failed_already = False

    def arm(self) -> None:
        """Fail on the next activation (the previous ones already passed)."""
        self._fail_once = True

    async def load(self, record, payload: bytes) -> LoadedExtension:
        self.calls.append((record.install_id, record.version, bytes(payload)))
        if self._fail_once and not self._failed_already:
            self._failed_already = True
            raise RuntimeError("simulated activation crash")
        return LoadedExtension(extension_id=record.extension_id, version=record.version)


class RecordingJanitor:
    """Janitor spy: names the resources it purges, or fails on demand."""

    def __init__(self, *, fail: bool = False) -> None:
        self.purged: list[str] = []
        self.calls: list[str] = []
        self._fail = fail

    async def purge(self, record) -> tuple[str, ...]:
        self.calls.append(record.install_id)
        if self._fail:
            raise RuntimeError("storage bucket unavailable")
        resources = (f"ws-data://{record.extension_id}/{record.version}",)
        self.purged.extend(resources)
        return resources


TRUST = TrustEvidence(publisher_id="acme", signature_present=True, signer_key_id="key-1")
POLICY = TrustPolicy(
    trusted_publishers=frozenset({"acme"}),
    require_signature=True,
    allowed_signer_keys=frozenset({"key-1"}),
)
SCOPE = ExtensionScope(org_id="org-1", workspace_id="ws-1")

_ids = iter(f"install-{n}" for n in range(10000))


def make_service(
    *,
    loader: ExtensionCodeLoader | None = None,
    clock: DeterministicClock | None = None,
    store: InMemoryExtensionStore | None = None,
    janitor: RecordingJanitor | None = None,
) -> tuple[ExtensionInstallService, InMemoryExtensionStore, RecordingLoader, DeterministicClock]:
    chosen_loader = loader or RecordingLoader()
    chosen_clock = clock or DeterministicClock()
    chosen_store = store or InMemoryExtensionStore()
    service = ExtensionInstallService(
        chosen_store,
        loader=chosen_loader,
        trust_policy=POLICY,
        platform_api_version="1.0.0",
        clock=chosen_clock,
        install_id_factory=lambda: f"install-{next(_ids)}",
        owned_resource_janitor=janitor,
    )
    return service, chosen_store, chosen_loader, chosen_clock


async def install_version(
    service: ExtensionInstallService,
    *,
    version: str,
    payload: bytes = PAYLOAD_V1,
    permissions: tuple[str, ...] = ("network.http", "storage.workspace"),
    extension_id: str = "acme.chart_tools",
    actor: str = "operator-1",
    scope: ExtensionScope = SCOPE,
    **manifest_kwargs: object,
):
    """inspect → authorize → install: one governed install, end to end."""
    record = await service.inspect(
        actor=actor,
        scope=scope,
        package=ExtensionPackage(
            manifest_bytes=manifest_bytes(
                extension_id=extension_id,
                version=version,
                permissions=permissions,
                payload=payload,
                **manifest_kwargs,  # type: ignore[arg-type]
            ),
            payload=payload,
        ),
        trust_evidence=TRUST,
    )
    assert record.state is ExtensionState.AWAITING_AUTHORIZATION, record
    await service.authorize(
        record.install_id, actor=actor, scope=scope, approve=True, reason="reviewed"
    )
    return await service.install(record.install_id, actor=actor, scope=scope, payload=payload)


async def begin_upgrade(
    service: ExtensionInstallService,
    *,
    version: str,
    payload: bytes = PAYLOAD_V2,
    permissions: tuple[str, ...] = ("network.http", "storage.workspace"),
    extension_id: str = "acme.chart_tools",
    actor: str = "operator-2",
    scope: ExtensionScope = SCOPE,
    **manifest_kwargs: object,
):
    """The upgrade request alone: preflight + inspect, before any decision."""
    return await service.upgrade(
        actor=actor,
        scope=scope,
        package=ExtensionPackage(
            manifest_bytes=manifest_bytes(
                extension_id=extension_id,
                version=version,
                permissions=permissions,
                payload=payload,
                **manifest_kwargs,  # type: ignore[arg-type]
            ),
            payload=payload,
        ),
        trust_evidence=TRUST,
    )


async def upgrade_to(
    service: ExtensionInstallService,
    **kwargs: object,
) -> tuple[object, object, object]:
    """upgrade → authorize → activate_upgrade: one governed upgrade."""
    record, report = await begin_upgrade(service, **kwargs)
    scope = kwargs.get("scope", SCOPE)
    actor = str(kwargs.get("actor", "operator-2"))
    payload = bytes(kwargs.get("payload", PAYLOAD_V2))
    await service.authorize(
        record.install_id, actor=actor, scope=scope, approve=True, reason="delta reviewed"
    )
    activated = await service.activate_upgrade(
        record.install_id, actor=actor, scope=scope, payload=payload
    )
    return activated, report, record


async def install_then_upgrade(service: ExtensionInstallService):
    v1 = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
    v2, _report, _candidate = await upgrade_to(service, version="1.5.0", payload=PAYLOAD_V2)
    return v1, v2


class TestSameAuthorityUpgrade:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_upgrade_applies_with_empty_authority_delta_and_frozen_grant(self) -> None:
        """AC: compatible same-authority upgrades apply without silently
        changing permissions.

        The upgrade record's authority delta must be empty against the active
        grant, the new grant must be exactly the snapshot's declared
        permissions, and the old version must keep its own record and grant
        intact as provenance.
        """
        service, _store, _loader, _clock = make_service()
        v1 = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        assert v1.granted_permissions == ("network.http", "storage.workspace")

        v2, report, _candidate = await upgrade_to(service, version="1.5.0", payload=PAYLOAD_V2)

        assert v2.state is ExtensionState.ACTIVE
        assert v2.version == "1.5.0"
        assert report.allowed
        assert report.authority.new == (), "same-authority upgrade must request nothing new"
        assert v2.granted_permissions == v1.granted_permissions, (
            "permissions must not drift from the authorized set"
        )
        assert v2.requested_permissions == v2.manifest.permissions
        # The old version is retired, not deleted: provenance survives.
        v1_final = await service.get(v1.install_id, scope=SCOPE)
        assert v1_final.state is ExtensionState.SUPERSEDED
        assert v1.granted_permissions == ("network.http", "storage.workspace")
        # Resolution serves exactly the new version.
        resolved = await service.resolve(SCOPE, "acme.chart_tools")
        assert resolved is not None and resolved.install_id == v2.install_id

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_upgraded_permissions_come_from_the_new_immutable_snapshot(self) -> None:
        """The grant follows the snapshot the operator approved — verified
        against its anchored digest, not re-derived from a request."""
        service, _store, _loader, _clock = make_service()
        await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        v2, _report, _candidate = await upgrade_to(
            service,
            version="1.5.0",
            payload=PAYLOAD_V2,
            permissions=("network.http",),
        )
        # Narrowing is allowed (it never broadens); the grant is the snapshot's.
        assert v2.granted_permissions == ("network.http",)
        displayed = await service.permissions_in_snapshot(v2)
        assert displayed == ("network.http",)

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_upgrade_swaps_pointer_once_and_retires_the_predecessor(self) -> None:
        service, store, _loader, _clock = make_service()
        await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        v2, _report, _candidate = await upgrade_to(service, version="1.5.0", payload=PAYLOAD_V2)
        pointer = await store.active_record(SCOPE, "acme.chart_tools")
        assert pointer is not None and pointer.install_id == v2.install_id
        actives = [
            r for r in await store.records_in_state(ExtensionState.ACTIVE) if r.org_id == "org-1"
        ]
        assert [r.install_id for r in actives] == [v2.install_id]

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_upgrade_requires_an_active_predecessor(self) -> None:
        service, _store, _loader, _clock = make_service()
        with pytest.raises(PreflightError, match="no ACTIVE install"):
            await begin_upgrade(service, version="2.0.0")

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_upgrade_preflight_refuses_downgrades_and_same_version_new_bytes(self) -> None:
        service, store, _loader, _clock = make_service()
        await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        with pytest.raises(PreflightError, match="rollback, not an upgrade"):
            await begin_upgrade(service, version="1.0.0")
        # Same version, different bytes: one version may never have two contents.
        with pytest.raises(PreflightError, match="different manifest bytes"):
            await begin_upgrade(service, version="1.4.0", payload=PAYLOAD_V2)
        # Nothing changed by the refused upgrades.
        resolved = await service.resolve(SCOPE, "acme.chart_tools")
        assert resolved is not None and resolved.version == "1.4.0"
        assert await store.records_in_state(ExtensionState.AWAITING_AUTHORIZATION) == []

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_byte_identical_upgrade_request_is_idempotent(self) -> None:
        service, _store, _loader, _clock = make_service()
        active = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        record, report = await begin_upgrade(service, version="1.4.0", payload=PAYLOAD_V1)
        assert record.install_id == active.install_id
        assert record.state is ExtensionState.ACTIVE
        assert report.allowed

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_upgrade_inspect_failure_records_rejected(self) -> None:
        """A candidate that passes preflight metadata but fails trust at
        inspection is recorded REJECTED — truthfully, with nothing changed."""
        service, _store, _loader, _clock = make_service()
        await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        record, _report = await service.upgrade(
            actor="operator-2",
            scope=SCOPE,
            package=ExtensionPackage(
                manifest_bytes=manifest_bytes(version="1.5.0", payload=PAYLOAD_V2),
                payload=PAYLOAD_V2,
            ),
            trust_evidence=TrustEvidence(publisher_id="acme", signature_present=False),
        )
        assert record.state is ExtensionState.REJECTED
        resolved = await service.resolve(SCOPE, "acme.chart_tools")
        assert resolved is not None and resolved.version == "1.4.0"


class TestBroadenedAuthorityReauthorization:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_broader_authority_names_the_new_permission_and_requires_decision(self) -> None:
        """AC: broader authority always requires explicit new authorization.

        The upgraded manifest adds ``filesystem.read``. The record must park
        in AWAITING_AUTHORIZATION with the delta naming exactly the new
        permission, activation must be structurally impossible before the
        decision, and only the explicit approval lets it through.
        """
        service, _store, loader, _clock = make_service()
        await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        calls_after_install = len(loader.calls)

        record, report = await begin_upgrade(
            service,
            version="1.5.0",
            permissions=("network.http", "storage.workspace", "filesystem.read"),
        )
        assert record.state is ExtensionState.AWAITING_AUTHORIZATION
        assert record.authority_delta == ("filesystem.read",)
        assert report.authority.new == ("filesystem.read",)
        assert report.broadens_authority
        assert len(loader.calls) == calls_after_install, (
            "no code may run before the explicit decision"
        )

        with pytest.raises(InvalidTransition):
            await service.activate_upgrade(
                record.install_id, actor="operator-2", scope=SCOPE, payload=PAYLOAD_V2
            )
        assert len(loader.calls) == calls_after_install, (
            "a refused activation must not reach the loader either"
        )

        await service.authorize(
            record.install_id,
            actor="operator-2",
            scope=SCOPE,
            approve=True,
            reason="delta approved",
        )
        activated = await service.activate_upgrade(
            record.install_id, actor="operator-2", scope=SCOPE, payload=PAYLOAD_V2
        )
        assert activated.state is ExtensionState.ACTIVE
        assert activated.granted_permissions == (
            "network.http",
            "storage.workspace",
            "filesystem.read",
        )
        transitions = await service.transitions(record.install_id, scope=SCOPE)
        authorized = next(t for t in transitions if t.to_state is ExtensionState.AUTHORIZED)
        assert authorized.actor == "operator-2"
        assert "delta approved" in authorized.reason

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_denial_of_broadened_upgrade_leaves_current_version_active(self) -> None:
        service, _store, _loader, _clock = make_service()
        v1 = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        record, _report = await begin_upgrade(
            service,
            version="1.5.0",
            permissions=("network.http", "storage.workspace", "filesystem.read"),
        )
        await service.authorize(
            record.install_id, actor="operator-2", scope=SCOPE, approve=False, reason="too broad"
        )
        resolved = await service.resolve(SCOPE, "acme.chart_tools")
        assert resolved is not None and resolved.install_id == v1.install_id


class TestRollback:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_restores_proven_compatible_state(self) -> None:
        """AC: rollback succeeds with proven compatible state.

        The superseded v1 becomes ACTIVE again through the loader seam, the
        pointer swaps, v2 is retained as SUPERSEDED with its grant, and both
        versions' audit trails survive.
        """
        service, _store, loader, _clock = make_service()
        v1, v2 = await install_then_upgrade(service)

        rolled = await service.rollback(
            v1.install_id,
            actor="operator-3",
            scope=SCOPE,
            payload=PAYLOAD_V1,
            reason="regression in 1.5.0",
        )
        assert rolled.state is ExtensionState.ACTIVE
        assert rolled.version == "1.4.0"
        assert rolled.granted_permissions == v1.granted_permissions
        v2_final = await service.get(v2.install_id, scope=SCOPE)
        assert v2_final.state is ExtensionState.SUPERSEDED
        resolved = await service.resolve(SCOPE, "acme.chart_tools")
        assert resolved is not None and resolved.install_id == v1.install_id
        # The rollback went through the loader seam with the exact v1 bytes.
        assert any(
            install_id == v1.install_id and payload == PAYLOAD_V1
            for install_id, _version, payload in loader.calls
        )
        # Both trails retained; the rollback step is explicit and attributed.
        for record in (v1, v2):
            trail = await service.transitions(record.install_id, scope=SCOPE)
            assert trail, f"{record.version} must keep its audit trail"
        rollback_transition = [
            t
            for t in await service.transitions(v1.install_id, scope=SCOPE)
            if t.to_state is ExtensionState.INSTALLING
        ][-1]
        assert "rollback" in rollback_transition.reason
        assert rollback_transition.actor == "operator-3"
        # The displaced v2 records who rolled it away and why.
        v2_trail = await service.transitions(v2.install_id, scope=SCOPE)
        assert v2_trail[-1].to_state is ExtensionState.SUPERSEDED
        assert "rolled back to 1.4.0" in v2_trail[-1].reason

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_with_substituted_bytes_fails_before_any_change(self) -> None:
        """AC: rollback fails before corrupting current state.

        A tampered payload must be refused on the digest check with zero
        state changes: states, pointer and audit trails all untouched, and
        the loader never reached.
        """
        service, store, loader, _clock = make_service()
        v1, v2 = await install_then_upgrade(service)
        transitions_before = await service.transitions(v1.install_id, scope=SCOPE)

        with pytest.raises(ArtifactMismatch):
            await service.rollback(
                v1.install_id,
                actor="operator-3",
                scope=SCOPE,
                payload=b"tampered-bytes",
                reason="oops",
            )

        pointer = await store.active_record(SCOPE, "acme.chart_tools")
        assert pointer is not None and pointer.install_id == v2.install_id
        assert (await service.get(v1.install_id, scope=SCOPE)).state is ExtensionState.SUPERSEDED
        assert (await service.get(v2.install_id, scope=SCOPE)).state is ExtensionState.ACTIVE
        assert await service.transitions(v1.install_id, scope=SCOPE) == transitions_before
        assert not any(
            payload == b"tampered-bytes" for _install_id, _version, payload in loader.calls
        ), "refused rollback must not reach the loader"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_refused_when_incompatible_with_current_scope(self) -> None:
        """v1 declared a dependency the current scope can no longer satisfy
        once the dependency partner moves on: the preflight must refuse
        before anything changes."""
        service, store, _loader, _clock = make_service()
        # The dependency partner must be active before v1 (which requires it) installs.
        await install_version(service, extension_id="acme.dep", version="2.1.0", payload=b"dep-v2")
        v1 = await install_version(
            service,
            version="1.4.0",
            payload=PAYLOAD_V1,
            dependencies=({"id": "acme.dep", "range": "^2.0.0"},),
        )
        v2, _r, _c = await upgrade_to(service, version="1.5.0", payload=PAYLOAD_V2)
        # The dependency partner then upgrades past v1's declared range.
        dep3, _r2, _c2 = await upgrade_to(
            service, extension_id="acme.dep", version="3.0.0", payload=b"dep-v3"
        )
        assert dep3.state is ExtensionState.ACTIVE

        with pytest.raises(PreflightError, match="dependency"):
            await service.rollback(
                v1.install_id,
                actor="operator-3",
                scope=SCOPE,
                payload=PAYLOAD_V1,
                reason="try old version",
            )
        pointer = await store.active_record(SCOPE, "acme.chart_tools")
        assert pointer is not None and pointer.install_id == v2.install_id, (
            "a refused rollback must leave the current version active"
        )
        assert (await service.get(v1.install_id, scope=SCOPE)).state is ExtensionState.SUPERSEDED

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_restoring_dropped_authority_requires_explicit_acknowledgment(
        self,
    ) -> None:
        """Rolling back to a version whose grant holds permissions the
        current version no longer asks for is a real authority change: it is
        refused without the explicit acknowledgment, and the refusal names
        the permissions. With the acknowledgment it proceeds — as an explicit
        act, with the restored authority named in the audit trail."""
        service, store, _loader, _clock = make_service()
        v1 = await install_version(
            service,
            version="1.4.0",
            payload=PAYLOAD_V1,
            permissions=("network.http", "storage.workspace", "filesystem.read"),
        )
        v2, _r, _c = await upgrade_to(
            service, version="1.5.0", payload=PAYLOAD_V2, permissions=("network.http",)
        )
        assert v2.granted_permissions == ("network.http",)

        with pytest.raises(PreflightError, match=r"filesystem\.read"):
            await service.rollback(
                v1.install_id,
                actor="operator-3",
                scope=SCOPE,
                payload=PAYLOAD_V1,
                reason="downgrade",
            )
        pointer = await store.active_record(SCOPE, "acme.chart_tools")
        assert pointer is not None and pointer.install_id == v2.install_id

        rolled = await service.rollback(
            v1.install_id,
            actor="operator-3",
            scope=SCOPE,
            payload=PAYLOAD_V1,
            reason="downgrade, broadened authority accepted",
            allow_broadened=True,
        )
        assert rolled.state is ExtensionState.ACTIVE
        assert rolled.granted_permissions == (
            "network.http",
            "storage.workspace",
            "filesystem.read",
        )
        trail = await service.transitions(v1.install_id, scope=SCOPE)
        installing = [t for t in trail if t.to_state is ExtensionState.INSTALLING][-1]
        assert "filesystem.read" in installing.reason, (
            "the restored authority must be named in the audit trail"
        )

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_refused_while_pinned_to_other_version(self) -> None:
        service, _store, _loader, _clock = make_service()
        v1, _v2 = await install_then_upgrade(service)
        await service.pin(
            SCOPE, "acme.chart_tools", actor="operator-1", version="1.5.0", reason="hold"
        )
        with pytest.raises(PinConflict, match=r"pinned at 1\.5\.0"):
            await service.rollback(
                v1.install_id,
                actor="operator-3",
                scope=SCOPE,
                payload=PAYLOAD_V1,
                reason="downgrade",
            )

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_completed_rollback_retries_idempotently(self) -> None:
        service, _store, loader, _clock = make_service()
        v1, _v2 = await install_then_upgrade(service)
        first = await service.rollback(
            v1.install_id, actor="operator-3", scope=SCOPE, payload=PAYLOAD_V1, reason="regression"
        )
        activations_after_first = len(loader.calls)
        again = await service.rollback(
            v1.install_id, actor="operator-3", scope=SCOPE, payload=PAYLOAD_V1, reason="regression"
        )
        assert again.install_id == first.install_id
        assert again.state is ExtensionState.ACTIVE
        assert len(loader.calls) == activations_after_first, "the retry must not re-activate"


class TestDisable:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_disable_stops_resolution_immediately_and_preserves_history(self) -> None:
        """AC: disable prevents new invocations immediately while preserving
        historical Runs/Invocations.

        In this platform the invocation seam is ``resolve``; it must return
        None the moment disable returns. Every prior transition, the record
        and its frozen grant survive verbatim.
        """
        service, _store, _loader, _clock = make_service()
        active = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        before = await service.transitions(active.install_id, scope=SCOPE)

        disabled = await service.disable(
            active.install_id, actor="operator-4", scope=SCOPE, reason="suspected bad outputs"
        )
        assert disabled.state is ExtensionState.DISABLED
        assert disabled.status_reason == "suspected bad outputs"
        assert await service.resolve(SCOPE, "acme.chart_tools") is None

        after = await service.transitions(active.install_id, scope=SCOPE)
        assert len(after) == len(before) + 1
        disable_transition = after[-1]
        assert disable_transition.from_state is ExtensionState.ACTIVE
        assert disable_transition.to_state is ExtensionState.DISABLED
        assert disable_transition.actor == "operator-4"
        assert "suspected bad outputs" in disable_transition.reason
        # The grant is retained, not revoked: disable is suspension.
        assert disabled.granted_permissions == active.granted_permissions

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_resume_restores_resolution_through_the_loader_without_new_authorization(
        self,
    ) -> None:
        service, _store, loader, _clock = make_service()
        active = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        await service.disable(
            active.install_id, actor="operator-4", scope=SCOPE, reason="maintenance"
        )

        resumed = await service.resume(
            active.install_id, actor="operator-4", scope=SCOPE, payload=PAYLOAD_V1
        )
        assert resumed.state is ExtensionState.ACTIVE
        assert resumed.granted_permissions == active.granted_permissions, (
            "resume must not change the grant"
        )
        resolved = await service.resolve(SCOPE, "acme.chart_tools")
        assert resolved is not None and resolved.install_id == active.install_id
        assert any(call[0] == active.install_id for call in loader.calls)

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_resume_refuses_substituted_bytes(self) -> None:
        service, _store, _loader, _clock = make_service()
        active = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        await service.disable(
            active.install_id, actor="operator-4", scope=SCOPE, reason="maintenance"
        )
        with pytest.raises(ArtifactMismatch):
            await service.resume(
                active.install_id, actor="operator-4", scope=SCOPE, payload=b"other-bytes"
            )
        assert await service.resolve(SCOPE, "acme.chart_tools") is None

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_disable_is_idempotent_and_refuses_non_active(self) -> None:
        service, _store, _loader, _clock = make_service()
        active = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        first = await service.disable(
            active.install_id, actor="operator-4", scope=SCOPE, reason="once"
        )
        second = await service.disable(
            active.install_id, actor="operator-4", scope=SCOPE, reason="twice"
        )
        assert second.install_id == first.install_id
        assert second.state is ExtensionState.DISABLED

        record = await service.inspect(
            actor="operator-1",
            scope=SCOPE,
            package=ExtensionPackage(
                manifest_bytes=manifest_bytes(version="1.5.0", payload=PAYLOAD_V2),
                payload=PAYLOAD_V2,
            ),
            trust_evidence=TRUST,
        )
        with pytest.raises(InvalidTransition):
            await service.disable(
                record.install_id, actor="operator-4", scope=SCOPE, reason="not active"
            )


class TestPin:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_pin_holds_the_version_against_upgrades_until_unpinned(self) -> None:
        service, store, _loader, _clock = make_service()
        await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        pin = await service.pin(
            SCOPE, "acme.chart_tools", actor="operator-1", reason="freeze for quarter end"
        )
        assert isinstance(pin, PinRecord)
        assert pin.version == "1.4.0"
        assert pin.pinned_by == "operator-1"

        with pytest.raises(PinConflict, match=r"pinned at 1\.4\.0"):
            await begin_upgrade(service, version="1.5.0")
        # Nothing changed by the refused upgrade.
        assert await store.get_pin(SCOPE, "acme.chart_tools") is not None
        resolved = await service.resolve(SCOPE, "acme.chart_tools")
        assert resolved is not None and resolved.version == "1.4.0"

        assert await service.unpin(
            SCOPE, "acme.chart_tools", actor="operator-1", reason="quarter closed"
        )
        activated, _report, _candidate = await upgrade_to(service, version="1.5.0")
        assert activated.state is ExtensionState.ACTIVE

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_pin_is_idempotent_for_same_version_and_conflicts_for_another(self) -> None:
        service, _store, _loader, _clock = make_service()
        await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        first = await service.pin(SCOPE, "acme.chart_tools", actor="operator-1", reason="a")
        again = await service.pin(SCOPE, "acme.chart_tools", actor="operator-1", reason="b")
        assert again.version == first.version == "1.4.0"
        with pytest.raises(PreflightError, match=r"the active version is 1\.4\.0"):
            await service.pin(
                SCOPE, "acme.chart_tools", actor="operator-1", version="9.9.9", reason="c"
            )

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_unpin_is_idempotent_and_pin_operations_are_audited(self) -> None:
        service, _store, _loader, _clock = make_service()
        await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        assert not await service.unpin(SCOPE, "acme.chart_tools", actor="operator-1", reason="noop")
        await service.pin(SCOPE, "acme.chart_tools", actor="operator-1", reason="hold")
        await service.pin(SCOPE, "acme.chart_tools", actor="operator-1", reason="refresh")
        assert await service.unpin(SCOPE, "acme.chart_tools", actor="operator-1", reason="release")

        _pin, events = await service.pin_status(SCOPE, "acme.chart_tools")
        assert [event.action for event in events] == ["pin", "refresh", "unpin"]
        assert events[0].actor == "operator-1"
        assert events[0].version == "1.4.0"
        assert events[-1].version is None

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_pin_requires_an_active_install_and_a_reason(self) -> None:
        service, _store, _loader, _clock = make_service()
        with pytest.raises(PreflightError, match="no ACTIVE install"):
            await service.pin(SCOPE, "acme.absent", actor="operator-1", reason="x")
        await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        with pytest.raises(ValueError, match="reason is required"):
            await service.pin(SCOPE, "acme.chart_tools", actor="operator-1", reason="  ")


class TestRemove:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_remove_ends_authority_but_never_deletes_canonical_evidence(self) -> None:
        """AC: remove does not delete canonical historical evidence.

        After removal the record (with its immutable manifest snapshot and
        frozen grant) and the full transition trail must remain queryable,
        while resolution stops and the (scope, extension, version) key is
        released for a fresh authorization track.
        """
        service, store, _loader, _clock = make_service()
        active = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        trail_before = await service.transitions(active.install_id, scope=SCOPE)
        assert trail_before

        removed = await service.remove(
            active.install_id, actor="operator-5", scope=SCOPE, reason="contract ended"
        )
        assert removed.state is ExtensionState.REMOVED
        assert removed.status_reason == "contract ended"
        assert await service.resolve(SCOPE, "acme.chart_tools") is None

        fetched = await service.get(active.install_id, scope=SCOPE)
        assert fetched is removed
        assert fetched.manifest.source_sha256 == active.manifest.source_sha256
        assert fetched.granted_permissions == active.granted_permissions
        trail_after = await service.transitions(active.install_id, scope=SCOPE)
        assert len(trail_after) == len(trail_before) + 1
        removal = trail_after[-1]
        assert removal.actor == "operator-5"
        assert removal.from_state is ExtensionState.ACTIVE
        assert removal.to_state is ExtensionState.REMOVED
        assert removal.reason == "removed: contract ended"
        # The store holds no deletion path for records or transitions.
        assert active.install_id in store._records  # retention IS the assertion

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_remove_releases_the_key_so_reinstall_opens_a_fresh_track(self) -> None:
        service, _store, _loader, _clock = make_service()
        active = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        await service.remove(
            active.install_id, actor="operator-5", scope=SCOPE, reason="offboarding"
        )
        fresh = await service.inspect(
            actor="operator-6",
            scope=SCOPE,
            package=ExtensionPackage(
                manifest_bytes=manifest_bytes(version="1.4.0", payload=PAYLOAD_V1),
                payload=PAYLOAD_V1,
            ),
            trust_evidence=TRUST,
        )
        assert fresh.state is ExtensionState.AWAITING_AUTHORIZATION
        assert fresh.install_id != active.install_id, (
            "a removed record must never be silently resurrected"
        )
        # The old record stays REMOVED with its history.
        assert (await service.get(active.install_id, scope=SCOPE)).state is ExtensionState.REMOVED
        assert await service.transitions(active.install_id, scope=SCOPE)

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_remove_runs_the_janitor_and_reports_the_purge(self) -> None:
        """The owned-resource cleanup policy: purge strictly after authority
        ends, report what was purged, attribute the report."""
        janitor = RecordingJanitor()
        service, _store, _loader, _clock = make_service(janitor=janitor)
        active = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        removed = await service.remove(
            active.install_id, actor="operator-5", scope=SCOPE, reason="offboarding"
        )
        assert removed.state is ExtensionState.REMOVED
        assert janitor.calls == [active.install_id]
        notes = await service.removal_history(active.install_id, scope=SCOPE)
        assert len(notes) == 1
        note = notes[0]
        assert isinstance(note, RemovalNote)
        assert note.purged == ("ws-data://acme.chart_tools/1.4.0",)
        assert note.failed == ()
        assert note.actor == "operator-5"
        assert note.install_id == active.install_id

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_janitor_failure_is_recorded_and_never_preserves_authority(self) -> None:
        janitor = RecordingJanitor(fail=True)
        service, _store, _loader, _clock = make_service(janitor=janitor)
        active = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        removed = await service.remove(
            active.install_id, actor="operator-5", scope=SCOPE, reason="offboarding"
        )
        assert removed.state is ExtensionState.REMOVED, "cleanup failure must not undo removal"
        assert await service.resolve(SCOPE, "acme.chart_tools") is None
        notes = await service.removal_history(active.install_id, scope=SCOPE)
        assert notes[0].purged == ()
        assert notes[0].failed and "storage bucket unavailable" in notes[0].failed[0]

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_remove_retry_is_idempotent_and_retries_pending_cleanup(self) -> None:
        service, _store, _loader, _clock = make_service()
        active = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        await service.remove(active.install_id, actor="operator-5", scope=SCOPE, reason="a")
        janitor = RecordingJanitor()
        again = await service.remove(
            active.install_id,
            actor="operator-5",
            scope=SCOPE,
            reason="retry cleanup",
            janitor=janitor,
        )
        assert again.state is ExtensionState.REMOVED
        assert janitor.calls == [active.install_id], "the retry must run the pending cleanup"
        notes = await service.removal_history(active.install_id, scope=SCOPE)
        assert len(notes) == 1

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_remove_of_superseded_leaves_the_active_one_serving(self) -> None:
        service, _store, _loader, _clock = make_service()
        v1, v2 = await install_then_upgrade(service)
        await service.remove(v1.install_id, actor="operator-5", scope=SCOPE, reason="prune old")
        resolved = await service.resolve(SCOPE, "acme.chart_tools")
        assert resolved is not None and resolved.install_id == v2.install_id, (
            "removing a superseded record must not disturb the active one"
        )
        await service.remove(v2.install_id, actor="operator-5", scope=SCOPE, reason="sunset")
        assert await service.resolve(SCOPE, "acme.chart_tools") is None


class TestIdempotencyAndCrashRecovery:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_upgrade_retry_after_activation_is_idempotent(self) -> None:
        service, _store, loader, _clock = make_service()
        await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        record, _report = await begin_upgrade(service, version="1.5.0")
        await service.authorize(
            record.install_id, actor="operator-2", scope=SCOPE, approve=True, reason="ok"
        )
        first = await service.activate_upgrade(
            record.install_id, actor="operator-2", scope=SCOPE, payload=PAYLOAD_V2
        )
        second = await service.activate_upgrade(
            record.install_id, actor="operator-2", scope=SCOPE, payload=PAYLOAD_V2
        )
        assert second.install_id == first.install_id
        assert second.state is ExtensionState.ACTIVE
        activations = [call for call in loader.calls if call[0] == record.install_id]
        assert len(activations) == 1, "retry must not re-run the loader"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_upgrade_retry_reuses_one_authorization_track(self) -> None:
        """Retrying the upgrade request must not fork a second authorization
        track for one candidate version."""
        service, store, _loader, _clock = make_service()
        await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        first, _report = await begin_upgrade(service, version="1.5.0")
        second, _report = await begin_upgrade(service, version="1.5.0")
        assert first.install_id == second.install_id
        awaiting = await store.records_in_state(ExtensionState.AWAITING_AUTHORIZATION)
        assert len([r for r in awaiting if r.extension_id == "acme.chart_tools"]) == 1

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_failed_upgrade_activation_recovers_with_the_same_artifact(self) -> None:
        """AC: lifecycle retries are idempotent and crash/restart-safe.

        A loader crash mid-upgrade leaves a truthful FAILED record and the
        old version serving; recovery presents the same bound artifact and
        completes without a second decision on new authority.
        """
        flaky = RecordingLoader()
        service, _store, _loader, _clock = make_service(loader=flaky)
        v1 = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        record, _report = await begin_upgrade(service, version="1.5.0")
        await service.authorize(
            record.install_id, actor="operator-2", scope=SCOPE, approve=True, reason="ok"
        )
        flaky.arm()  # the crash must hit the UPGRADE activation, not v1's install
        with pytest.raises(ExtensionLifecycleError):
            await service.activate_upgrade(
                record.install_id, actor="operator-2", scope=SCOPE, payload=PAYLOAD_V2
            )
        # Truthful failure: FAILED record, old version still serving.
        failed = await service.get(record.install_id, scope=SCOPE)
        assert failed.state is ExtensionState.FAILED
        assert failed.failure_reason and "activation failed" in failed.failure_reason
        resolved = await service.resolve(SCOPE, "acme.chart_tools")
        assert resolved is not None and resolved.install_id == v1.install_id

        recovered = await service.activate_upgrade(
            record.install_id, actor="operator-2", scope=SCOPE, payload=PAYLOAD_V2
        )
        assert recovered.state is ExtensionState.ACTIVE
        final = await service.resolve(SCOPE, "acme.chart_tools")
        assert final is not None and final.install_id == record.install_id

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_reconcile_supersedes_active_records_the_pointer_lost(self) -> None:
        """Crash window: activation swapped the pointer but the supersede
        never ran. Reconciliation must retire the orphan ACTIVE record as an
        audited transition, leaving exactly one servable version."""
        service, store, _loader, _clock = make_service()
        v1 = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        v2, _report, _candidate = await upgrade_to(service, version="1.5.0")
        # Simulate the crash: v1 is ACTIVE again but the pointer names v2.
        await store.save_record(replace(v1, state=ExtensionState.ACTIVE, status_reason=None))

        repaired = await service.reconcile(scope=SCOPE, extension_id="acme.chart_tools")
        assert [record.install_id for record in repaired] == [v1.install_id]
        superseded = await service.get(v1.install_id, scope=SCOPE)
        assert superseded.state is ExtensionState.SUPERSEDED
        resolved = await service.resolve(SCOPE, "acme.chart_tools")
        assert resolved is not None and resolved.install_id == v2.install_id
        trail = await service.transitions(v1.install_id, scope=SCOPE)
        assert trail[-1].actor == "system:reconciliation"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_reconcile_clears_pointers_to_records_that_lose_activeness(self) -> None:
        """Crash window: a disable transition landed but the pointer drop did
        not. Resolution must not serve a DISABLED record even before
        reconciliation, and reconcile must repair the pointer itself."""
        service, store, _loader, _clock = make_service()
        active = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        disabled = await service.disable(
            active.install_id, actor="operator-4", scope=SCOPE, reason="window"
        )
        # Simulate the crash: the pointer is back, wrongly.
        await store.set_active(disabled)
        assert await store.active_record(SCOPE, "acme.chart_tools") is not None
        assert await service.resolve(SCOPE, "acme.chart_tools") is None, (
            "resolve must never serve a non-ACTIVE record, pointer or not"
        )
        await service.reconcile(scope=SCOPE, extension_id="acme.chart_tools")
        assert await store.active_record(SCOPE, "acme.chart_tools") is None

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_full_lifecycle_leaves_queryable_provenance_for_every_version(self) -> None:
        """Historical provenance retention across the whole lifecycle:
        after install → upgrade → rollback → disable → remove, every record
        and every transition remains queryable in order."""
        service, _store, _loader, _clock = make_service()
        v1 = await install_version(service, version="1.4.0", payload=PAYLOAD_V1)
        v2, _report, _candidate = await upgrade_to(service, version="1.5.0")
        await service.rollback(
            v1.install_id, actor="operator-3", scope=SCOPE, payload=PAYLOAD_V1, reason="regression"
        )
        await service.disable(v1.install_id, actor="operator-4", scope=SCOPE, reason="sunsetting")
        await service.remove(v1.install_id, actor="operator-5", scope=SCOPE, reason="gone")

        for record in (v1, v2):
            trail = await service.transitions(record.install_id, scope=SCOPE)
            assert trail[0].from_state is ExtensionState.INSPECTING
            assert len(trail) >= 4
            assert all(trail[i].seq < trail[i + 1].seq for i in range(len(trail) - 1))
        final = await service.get(v1.install_id, scope=SCOPE)
        assert final.state is ExtensionState.REMOVED
        other = await service.get(v2.install_id, scope=SCOPE)
        assert other.state is ExtensionState.SUPERSEDED
