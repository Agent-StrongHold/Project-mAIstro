"""The governed extension install lifecycle (#953, M9-B2).

These tests drive the inspect → authorize → install state machine end to end
and pin each acceptance criterion of the issue against reachable production
behavior: no extension code runs before authorization, denied/abandoned
requests leave nothing active, permissions display from the immutable
snapshot, failures are truthful and recoverable, retries neither duplicate
records nor broaden authority, and every transition carries actor, scope,
version and reason.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from maistro.extensions import (
    ArtifactMismatch,
    ExtensionLifecycleError,
    InMemoryExtensionStore,
    InspectionConflict,
    InvalidTransition,
    ManifestRejected,
    TrustPolicy,
    UnknownInstall,
)
from maistro.extensions.service import (
    ExtensionCodeLoader,
    ExtensionInstallService,
    LoadedExtension,
    UnwiredExtensionLoader,
)
from maistro.extensions.types import (
    ExtensionInstallRecord,
    ExtensionPackage,
    ExtensionScope,
    ExtensionState,
    TrustClaim,
)

PAYLOAD = b"extension-payload-v1"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_bytes(
    *,
    extension_id: str = "acme.chart_tools",
    version: str = "1.4.0",
    permissions: tuple[str, ...] = ("network.http", "storage.workspace"),
    payload: bytes = PAYLOAD,
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
    """A clock the tests move by hand, so expiry is structural, not timed."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class RecordingLoader:
    """Loader spy: records every activation, so tests can prove when code
    would have run — and, critically, when it could not have."""

    def __init__(self, *, fail: bool = False, identity_swap: bool = False) -> None:
        self.calls: list[tuple[str, bytes]] = []
        self._fail = fail
        self._identity_swap = identity_swap

    async def load(self, record: ExtensionInstallRecord, payload: bytes) -> LoadedExtension:
        self.calls.append((record.install_id, bytes(payload)))
        if self._fail:
            raise RuntimeError("simulated activation crash")
        if self._identity_swap:
            return LoadedExtension(extension_id="other.extension", version="9.9.9")
        return LoadedExtension(extension_id=record.extension_id, version=record.version)


class SlowLoader:
    """Loader that yields before activating, to overlap concurrent installs."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes]] = []

    async def load(self, record: ExtensionInstallRecord, payload: bytes) -> LoadedExtension:
        await asyncio.sleep(0.01)
        self.calls.append((record.install_id, bytes(payload)))
        return LoadedExtension(extension_id=record.extension_id, version=record.version)


TRUST = TrustClaim(publisher_id="acme", signature_present=True, signer_key_id="key-1")
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
    ttl: timedelta = timedelta(minutes=15),
    store: InMemoryExtensionStore | None = None,
) -> tuple[
    ExtensionInstallService, InMemoryExtensionStore, ExtensionCodeLoader, DeterministicClock
]:
    chosen_loader = loader or RecordingLoader()
    chosen_clock = clock or DeterministicClock()
    chosen_store = store or InMemoryExtensionStore()
    service = ExtensionInstallService(
        chosen_store,
        loader=chosen_loader,
        trust_policy=POLICY,
        platform_api_version="1.0.0",
        authorization_ttl=ttl,
        clock=chosen_clock,
        install_id_factory=lambda: f"install-{next(_ids)}",
    )
    return service, chosen_store, chosen_loader, chosen_clock


async def inspect_default(
    service: ExtensionInstallService,
    *,
    extension_id: str = "acme.chart_tools",
    version: str = "1.4.0",
    payload: bytes = PAYLOAD,
    scope: ExtensionScope = SCOPE,
    permissions: tuple[str, ...] = ("network.http", "storage.workspace"),
    actor: str = "operator-1",
    evidence: TrustClaim = TRUST,
    **manifest_kwargs: object,
) -> ExtensionInstallRecord:
    return await service.inspect(
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
        trust_evidence=evidence,
    )


async def authorize_and_install(
    service: ExtensionInstallService,
    record: ExtensionInstallRecord,
    *,
    payload: bytes = PAYLOAD,
    actor: str = "operator-1",
) -> ExtensionInstallRecord:
    scope = ExtensionScope(org_id=record.org_id, workspace_id=record.workspace_id)
    await service.authorize(
        record.install_id, actor=actor, scope=scope, approve=True, reason="reviewed"
    )
    return await service.install(record.install_id, actor=actor, scope=scope, payload=payload)


class TestNoPreAuthorizationCodeExecution:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_inspection_and_authorization_never_reach_the_loader(self) -> None:
        """AC: no extension code imports during inspect/authorization phases.

        The loader is the only code-execution seam in the platform; if
        inspection and the authorization decision complete without touching
        it, no extension code could have run.
        """
        service, _store, loader, _clock = make_service()
        record = await inspect_default(service)
        assert record.state is ExtensionState.AWAITING_AUTHORIZATION
        assert loader.calls == []  # type: ignore[attr-defined]

        await service.authorize(
            record.install_id, actor="operator-1", scope=SCOPE, approve=True, reason="ok"
        )
        assert loader.calls == [], "authorization must never activate extension code"  # type: ignore[attr-defined]

        denied = await inspect_default(service, version="1.4.1")
        await service.authorize(
            denied.install_id, actor="operator-1", scope=SCOPE, approve=False, reason="no"
        )
        assert loader.calls == [], "a denial must never activate extension code"  # type: ignore[attr-defined]

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rejected_inspections_never_reach_the_loader(self) -> None:
        service, _store, loader, _clock = make_service()
        record = await inspect_default(service, publisher="untrusted-co")
        assert record.state is ExtensionState.REJECTED
        assert loader.calls == []  # type: ignore[attr-defined]


class TestActivationFlow:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_happy_path_activates_only_after_every_check(self) -> None:
        service, store, loader, _clock = make_service()
        record = await inspect_default(service)
        assert record.state is ExtensionState.AWAITING_AUTHORIZATION
        assert await store.active_record(SCOPE, record.extension_id) is None

        authorized = await service.authorize(
            record.install_id, actor="operator-1", scope=SCOPE, approve=True, reason="ok"
        )
        assert authorized.state is ExtensionState.AUTHORIZED
        assert authorized.granted_permissions == record.requested_permissions
        assert authorized.authorized_by == "operator-1"
        assert await store.active_record(SCOPE, record.extension_id) is None

        installed = await service.install(
            record.install_id, actor="operator-1", scope=SCOPE, payload=PAYLOAD
        )
        assert installed.state is ExtensionState.ACTIVE
        assert loader.calls == [(record.install_id, PAYLOAD)]  # type: ignore[attr-defined]
        active = await store.active_record(SCOPE, record.extension_id)
        assert active is not None and active.install_id == record.install_id

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_install_without_authorization_is_refused(self) -> None:
        service, store, loader, _clock = make_service()
        record = await inspect_default(service)
        with pytest.raises(InvalidTransition):
            await service.install(
                record.install_id, actor="operator-1", scope=SCOPE, payload=PAYLOAD
            )
        assert loader.calls == []  # type: ignore[attr-defined]
        assert await store.active_record(SCOPE, record.extension_id) is None
        unchanged = await store.get_record(record.install_id)
        assert unchanged is not None
        assert unchanged.state is ExtensionState.AWAITING_AUTHORIZATION


class TestDeniedAndAbandonedLeaveNothingActive:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_denied_authorization_leaves_no_active_extension(self) -> None:
        """AC: denied authorization leaves no active extension."""
        service, store, loader, _clock = make_service()
        record = await inspect_default(service)
        denied = await service.authorize(
            record.install_id, actor="operator-2", scope=SCOPE, approve=False, reason="not needed"
        )
        assert denied.state is ExtensionState.DENIED
        assert await store.active_record(SCOPE, record.extension_id) is None
        with pytest.raises(InvalidTransition):
            await service.install(
                record.install_id, actor="operator-2", scope=SCOPE, payload=PAYLOAD
            )
        assert loader.calls == []  # type: ignore[attr-defined]

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_expired_request_is_abandoned_and_cannot_be_approved(self) -> None:
        """AC: abandoned authorization leaves no active extension."""
        clock = DeterministicClock()
        service, store, loader, _clock = make_service(clock=clock, ttl=timedelta(minutes=15))
        record = await inspect_default(service)
        assert record.expires_at is not None

        clock.advance(timedelta(minutes=16))
        with pytest.raises(InvalidTransition, match="expired"):
            await service.authorize(
                record.install_id, actor="operator-2", scope=SCOPE, approve=True, reason="late"
            )
        abandoned = await store.get_record(record.install_id)
        assert abandoned is not None and abandoned.state is ExtensionState.ABANDONED
        assert await store.active_record(SCOPE, record.extension_id) is None
        with pytest.raises(InvalidTransition):
            await service.install(
                record.install_id, actor="operator-2", scope=SCOPE, payload=PAYLOAD
            )
        assert loader.calls == []  # type: ignore[attr-defined]

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_expiry_sweep_abandons_only_expired_requests(self) -> None:
        clock = DeterministicClock()
        service, store, _loader, _clock = make_service(clock=clock, ttl=timedelta(minutes=15))
        fresh = await inspect_default(service)
        clock.advance(timedelta(minutes=16))
        stale = await inspect_default(service, version="1.4.1")

        # `fresh` was created before the advance, so its window has passed;
        # `stale` was created after, so it is still inside its own.
        expired = await service.expire_abandoned()
        assert expired == 1
        first = await store.get_record(fresh.install_id)
        second = await store.get_record(stale.install_id)
        assert first is not None and first.state is ExtensionState.ABANDONED
        assert second is not None and second.state is ExtensionState.AWAITING_AUTHORIZATION
        sweep_again = await service.expire_abandoned()
        assert sweep_again == 0


class TestImmutableSnapshot:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_permissions_display_from_the_immutable_snapshot(self) -> None:
        """AC: requested permissions are displayed from the immutable snapshot."""
        service, _store, _loader, _clock = make_service()
        record = await inspect_default(service, permissions=("network.http", "clipboard.read"))
        displayed = await service.permissions_in_snapshot(record)
        assert displayed == ("network.http", "clipboard.read")
        # The display equals the manifest snapshot's own declaration, and the
        # snapshot bytes still hash to the digest anchored at inspection.
        assert displayed == record.manifest.permissions
        assert record.requested_permissions == displayed

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_tampered_snapshot_is_detected_at_display_and_grant(self) -> None:
        service, store, loader, _clock = make_service()
        record = await inspect_default(service)
        tampered = replace(record, manifest=replace(record.manifest, raw=b'{"forged": true}'))
        with pytest.raises(ManifestRejected, match="integrity"):
            await service.permissions_in_snapshot(tampered)

        # Corrupt the stored snapshot itself: the grant must refuse loudly
        # rather than authorize permissions nobody saw.
        await store.save_record(tampered)
        with pytest.raises(ManifestRejected, match="integrity"):
            await service.authorize(
                tampered.install_id, actor="operator-1", scope=SCOPE, approve=True, reason="ok"
            )
        still = await store.get_record(tampered.install_id)
        assert still is not None and still.state is ExtensionState.AWAITING_AUTHORIZATION
        assert loader.calls == []  # type: ignore[attr-defined]


class TestTruthfulActivation:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_activation_failure_records_failed_and_stays_recoverable(self) -> None:
        """AC: atomic from the caller's perspective or truthful recoverable
        intermediate state. A crashed loader leaves FAILED with the reason,
        nothing active, and the same bound artifact activates on retry."""
        failing = RecordingLoader(fail=True)
        service, store, _loader, _clock = make_service(loader=failing)
        record = await inspect_default(service)
        await service.authorize(
            record.install_id, actor="operator-1", scope=SCOPE, approve=True, reason="ok"
        )
        with pytest.raises(ExtensionLifecycleError):
            await service.install(
                record.install_id, actor="operator-1", scope=SCOPE, payload=PAYLOAD
            )
        failed = await store.get_record(record.install_id)
        assert failed is not None
        assert failed.state is ExtensionState.FAILED
        assert (
            failed.failure_reason is not None
            and "simulated activation crash" in failed.failure_reason
        )
        assert failed.install_attempts == 1
        assert await store.active_record(SCOPE, record.extension_id) is None

        # Recovery: same record, same bound artifact, a working loader.
        working = RecordingLoader()
        recovery = ExtensionInstallService(
            store,
            loader=working,
            trust_policy=POLICY,
            clock=DeterministicClock(),
        )
        recovered = await recovery.install(
            record.install_id, actor="operator-1", scope=SCOPE, payload=PAYLOAD
        )
        assert recovered.state is ExtensionState.ACTIVE
        assert recovered.install_attempts == 2
        active = await store.active_record(SCOPE, record.extension_id)
        assert active is not None and active.install_id == record.install_id
        assert len(working.calls) == 1

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_loader_identity_mismatch_is_recorded_failed(self) -> None:
        swapping = RecordingLoader(identity_swap=True)
        service, store, _loader, _clock = make_service(loader=swapping)
        record = await inspect_default(service)
        await service.authorize(
            record.install_id, actor="operator-1", scope=SCOPE, approve=True, reason="ok"
        )
        with pytest.raises(Exception, match="identity mismatch"):
            await service.install(
                record.install_id, actor="operator-1", scope=SCOPE, payload=PAYLOAD
            )
        failed = await store.get_record(record.install_id)
        assert failed is not None and failed.state is ExtensionState.FAILED
        assert await store.active_record(SCOPE, record.extension_id) is None

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_unwired_loader_fails_closed_after_authorization(self) -> None:
        """A deployment with no activation substrate must fail at activation,
        loudly, with the record telling the truth — never improvise imports."""
        service = ExtensionInstallService(
            InMemoryExtensionStore(),
            loader=UnwiredExtensionLoader(),
            trust_policy=POLICY,
            clock=DeterministicClock(),
        )
        record = await inspect_default(service)
        await service.authorize(
            record.install_id, actor="operator-1", scope=SCOPE, approve=True, reason="ok"
        )
        with pytest.raises(ExtensionLifecycleError, match="recorded FAILED"):
            await service.install(
                record.install_id, actor="operator-1", scope=SCOPE, payload=PAYLOAD
            )
        failed = await service.active(SCOPE, record.extension_id)
        assert failed is None
        trail = await service.transitions(record.install_id, scope=SCOPE)
        assert trail[-1].to_state is ExtensionState.FAILED
        assert "no activation loader is wired" in trail[-1].reason

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_wrong_payload_at_install_never_happens_to_the_machine(self) -> None:
        service, store, loader, _clock = make_service()
        record = await inspect_default(service)
        await service.authorize(
            record.install_id, actor="operator-1", scope=SCOPE, approve=True, reason="ok"
        )
        with pytest.raises(ArtifactMismatch):
            await service.install(
                record.install_id, actor="operator-1", scope=SCOPE, payload=b"tampered"
            )
        unchanged = await store.get_record(record.install_id)
        assert unchanged is not None and unchanged.state is ExtensionState.AUTHORIZED
        trail = await store.transitions_for(record.install_id)
        assert [t.to_state for t in trail] == [
            ExtensionState.AWAITING_AUTHORIZATION,
            ExtensionState.AUTHORIZED,
        ]
        assert loader.calls == []  # type: ignore[attr-defined]


class TestRetriesAndIdempotency:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_retry_does_not_duplicate_records_or_broaden_authority(self) -> None:
        """AC: retries do not duplicate install records or broaden authority."""
        service, store, loader, _clock = make_service()
        record = await inspect_default(service)
        installed = await authorize_and_install(service, record)
        assert installed.state is ExtensionState.ACTIVE

        again = await service.install(
            record.install_id, actor="operator-2", scope=SCOPE, payload=PAYLOAD
        )
        assert again.install_id == record.install_id
        assert again.state is ExtensionState.ACTIVE
        assert again.granted_permissions == installed.granted_permissions
        assert len(loader.calls) == 1, "an already-active install must not re-run the loader"  # type: ignore[attr-defined]

        all_records = [r for r in store._records.values() if r.extension_id == record.extension_id]
        assert len(all_records) == 1, "retry must not create a second install record"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_active_record_refuses_a_different_payload(self) -> None:
        service, store, loader, _clock = make_service()
        record = await inspect_default(service)
        await authorize_and_install(service, record)
        with pytest.raises(ArtifactMismatch):
            await service.install(
                record.install_id, actor="operator-1", scope=SCOPE, payload=b"different-bytes"
            )
        assert loader.calls == [(record.install_id, PAYLOAD)]  # type: ignore[attr-defined]
        active = await store.active_record(SCOPE, record.extension_id)
        assert active is not None and active.artifact_sha256 == record.artifact_sha256

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_reinspection_of_identical_bytes_is_idempotent(self) -> None:
        service, store, _loader, _clock = make_service()
        first = await inspect_default(service)
        second = await inspect_default(service)
        assert first.install_id == second.install_id
        assert first.state is ExtensionState.AWAITING_AUTHORIZATION
        records = [r for r in store._records.values() if r.extension_id == "acme.chart_tools"]
        assert len(records) == 1

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_changed_bytes_under_an_open_request_are_a_conflict(self) -> None:
        service, _store, _loader, _clock = make_service()
        await inspect_default(service)
        with pytest.raises(InspectionConflict, match="different bytes"):
            await inspect_default(service, permissions=("network.http",))
        with pytest.raises(InspectionConflict, match="different bytes"):
            await inspect_default(service, payload=PAYLOAD + b"-different")

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_reinspection_after_terminal_decision_starts_a_new_record(self) -> None:
        service, store, _loader, _clock = make_service()
        denied = await inspect_default(service)
        await service.authorize(
            denied.install_id, actor="operator-1", scope=SCOPE, approve=False, reason="no"
        )
        fresh = await inspect_default(service)
        assert fresh.install_id != denied.install_id
        assert fresh.state is ExtensionState.AWAITING_AUTHORIZATION
        assert len(store._records) == 2

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_concurrent_installs_serialize_to_one_activation(self) -> None:
        slow = SlowLoader()
        service, store, _loader, _clock = make_service(loader=slow)
        record = await inspect_default(service)
        await service.authorize(
            record.install_id, actor="operator-1", scope=SCOPE, approve=True, reason="ok"
        )
        results = await asyncio.gather(
            *[
                service.install(record.install_id, actor=f"op-{n}", scope=SCOPE, payload=PAYLOAD)
                for n in range(5)
            ]
        )
        assert {r.install_id for r in results} == {record.install_id}
        assert all(r.state is ExtensionState.ACTIVE for r in results)
        assert len(slow.calls) == 1, "concurrent retries must collapse to one activation"
        records = [r for r in store._records.values() if r.extension_id == record.extension_id]
        assert len(records) == 1


class TestAuthoritySemantics:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_authority_delta_names_only_new_permissions(self) -> None:
        service, _store, _loader, _clock = make_service()
        first = await inspect_default(service, permissions=("network.http",))
        assert first.authority_delta == ("network.http",)
        await authorize_and_install(service, first)

        upgrade = await inspect_default(
            service,
            version="1.5.0",
            permissions=("network.http", "clipboard.read"),
        )
        assert upgrade.authority_delta == ("clipboard.read",)

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_grant_is_frozen_at_authorization_and_survives_retries(self) -> None:
        service, store, _loader, _clock = make_service()
        record = await inspect_default(service, permissions=("network.http", "clipboard.read"))
        authorized = await service.authorize(
            record.install_id, actor="operator-1", scope=SCOPE, approve=True, reason="ok"
        )
        assert authorized.granted_permissions == ("network.http", "clipboard.read")
        installed = await service.install(
            record.install_id, actor="operator-1", scope=SCOPE, payload=PAYLOAD
        )
        assert installed.granted_permissions == authorized.granted_permissions

        # A failed install attempt must not change the frozen grant either.
        failing = ExtensionInstallService(
            store,
            loader=RecordingLoader(fail=True),
            trust_policy=POLICY,
            clock=DeterministicClock(),
        )
        second = await inspect_default(
            failing,
            version="1.4.1",
            permissions=("network.http", "clipboard.read"),
        )
        await failing.authorize(
            second.install_id, actor="operator-1", scope=SCOPE, approve=True, reason="ok"
        )
        with pytest.raises(ExtensionLifecycleError):
            await failing.install(
                second.install_id, actor="operator-1", scope=SCOPE, payload=PAYLOAD
            )
        failed = await store.get_record(second.install_id)
        assert failed is not None
        assert failed.granted_permissions == authorized.granted_permissions


class TestAuditability:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_every_transition_carries_actor_scope_version_reason(self) -> None:
        """AC: every transition is auditable with actor, Workspace/org scope,
        extension version and reason."""
        service, _store, _loader, _clock = make_service()
        record = await inspect_default(service)
        await service.authorize(
            record.install_id,
            actor="operator-9",
            scope=SCOPE,
            approve=True,
            reason="quarterly review",
        )
        await service.install(record.install_id, actor="operator-7", scope=SCOPE, payload=PAYLOAD)

        trail = await service.transitions(record.install_id, scope=SCOPE)
        assert [t.to_state for t in trail] == [
            ExtensionState.AWAITING_AUTHORIZATION,
            ExtensionState.AUTHORIZED,
            ExtensionState.INSTALLING,
            ExtensionState.ACTIVE,
        ]
        assert [t.seq for t in trail] == sorted(t.seq for t in trail)
        assert [t.from_state for t in trail] == [
            ExtensionState.INSPECTING,
            ExtensionState.AWAITING_AUTHORIZATION,
            ExtensionState.AUTHORIZED,
            ExtensionState.INSTALLING,
        ]
        for transition in trail:
            assert transition.actor, "every transition names its actor"
            assert transition.org_id == "org-1"
            assert transition.workspace_id == "ws-1"
            assert transition.extension_id == "acme.chart_tools"
            assert transition.version == "1.4.0"
            assert transition.reason.strip(), "every transition carries a reason"
        assert {"operator-1", "operator-9", "operator-7"} <= {t.actor for t in trail}
        assert record.requested_by == "operator-1"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rejection_and_denial_are_audited_too(self) -> None:
        service, _store, _loader, _clock = make_service()
        rejected = await inspect_default(service, publisher="untrusted-co")
        rejected_trail = await service.transitions(rejected.install_id, scope=SCOPE)
        assert len(rejected_trail) == 1
        assert rejected_trail[0].to_state is ExtensionState.REJECTED
        assert "publisher mismatch" in rejected_trail[0].reason

        denied = await inspect_default(service, version="1.4.1")
        await service.authorize(
            denied.install_id, actor="operator-2", scope=SCOPE, approve=False, reason="policy"
        )
        denied_trail = await service.transitions(denied.install_id, scope=SCOPE)
        assert denied_trail[-1].to_state is ExtensionState.DENIED
        assert "policy" in denied_trail[-1].reason
        assert denied_trail[-1].actor == "operator-2"


class TestScopeContainment:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_records_are_invisible_across_scopes(self) -> None:
        service, _store, _loader, _clock = make_service()
        record = await inspect_default(service)
        other = ExtensionScope(org_id="org-2", workspace_id="ws-9")
        with pytest.raises(UnknownInstall):
            await service.get(record.install_id, scope=other)
        with pytest.raises(UnknownInstall):
            await service.authorize(
                record.install_id, actor="op", scope=other, approve=True, reason="x"
            )
        with pytest.raises(UnknownInstall):
            await service.install(record.install_id, actor="op", scope=other, payload=PAYLOAD)
        with pytest.raises(UnknownInstall):
            await service.transitions(record.install_id, scope=other)
        # The record is untouched by the refused cross-scope attempts.
        still = await service.get(record.install_id, scope=SCOPE)
        assert still.state is ExtensionState.AWAITING_AUTHORIZATION

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_same_extension_id_in_two_scopes_is_two_independent_records(self) -> None:
        service, _store, _loader, _clock = make_service()
        scope_b = ExtensionScope(org_id="org-2", workspace_id="ws-2")
        first = await inspect_default(service)
        second = await inspect_default(service, scope=scope_b)
        assert first.install_id != second.install_id
        await authorize_and_install(service, first)
        assert await service.active(SCOPE, "acme.chart_tools") is not None
        assert await service.active(scope_b, "acme.chart_tools") is None


class TestDecisionDiscipline:
    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_actor_and_reason_are_required_for_decisions(self) -> None:
        service, _store, _loader, _clock = make_service()
        record = await inspect_default(service)
        with pytest.raises(ValueError, match="reason"):
            await service.authorize(
                record.install_id, actor="operator-1", scope=SCOPE, approve=True, reason="   "
            )
        with pytest.raises(ValueError, match="actor"):
            await service.authorize(
                record.install_id, actor="  ", scope=SCOPE, approve=True, reason="ok"
            )
        with pytest.raises(ValueError, match="actor"):
            await inspect_default(service, actor="")
        still = await service.get(record.install_id, scope=SCOPE)
        assert still.state is ExtensionState.AWAITING_AUTHORIZATION

    @pytest.mark.contract("boundary")
    @pytest.mark.scope("unit")
    async def test_decisions_only_apply_to_awaiting_records(self) -> None:
        service, _store, _loader, _clock = make_service()
        record = await inspect_default(service)
        await authorize_and_install(service, record)
        with pytest.raises(InvalidTransition, match="active"):
            await service.authorize(
                record.install_id, actor="operator-1", scope=SCOPE, approve=True, reason="double"
            )
