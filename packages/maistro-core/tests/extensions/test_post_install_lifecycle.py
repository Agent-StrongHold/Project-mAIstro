"""The post-install extension lifecycle (#954, M9-B3; epic #939).

These tests drive pin → upgrade → rollback → disable → resume → remove
against the governed service and pin the epic's acceptance criteria on
reachable production behavior:

* a pinned version does not move silently (activation of another version is
  refused until the pin is explicitly lifted, and both decisions are audited);
* an upgrade cannot silently broaden authority — the broader request parks
  for explicit re-authorization, and the grant afterwards is exactly the new
  snapshot's, never a silent union;
* rollback restores a superseded version only when its frozen grant declares
  no authority the current grant lacks and its manifest still evaluates
  compatible — otherwise it refuses before corrupting the current state;
* disable removes the extension from the resolution seam immediately while
  every record, snapshot and transition stays queryable;
* remove runs the host janitor before any transition, is terminal for the
  record's authority, and preserves the historical evidence;
* every lifecycle operation — including pin/unpin, which change no state —
  lands on the same audited trail with actor, scope, version and reason.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace

import pytest

from extensions.test_install_lifecycle import (
    PAYLOAD,
    POLICY,
    SCOPE,
    RecordingLoader,
    authorize_and_install,
    inspect_default,
    make_service,
)
from maistro.extensions import (
    ArtifactMismatch,
    ExtensionLifecycleError,
    ExtensionPinned,
    ExtensionState,
    InMemoryExtensionStore,
    InvalidTransition,
    RollbackRefused,
    UnknownInstall,
)
from maistro.extensions.service import ExtensionInstallService, RetainAllJanitor
from maistro.extensions.types import ExtensionScope

OTHER_PAYLOAD = b"extension-payload-v2"
THIRD_PAYLOAD = b"extension-payload-v3"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def activate(
    service: ExtensionInstallService,
    *,
    version: str = "1.4.0",
    permissions: tuple[str, ...] = ("network.http", "storage.workspace"),
    payload: bytes = PAYLOAD,
    extension_id: str = "acme.chart_tools",
    actor: str = "operator-1",
    scope: ExtensionScope = SCOPE,
    **manifest_kwargs: object,
) -> object:
    """Inspect → authorize → install one candidate, returning the record."""
    record = await inspect_default(
        service,
        extension_id=extension_id,
        version=version,
        permissions=permissions,
        payload=payload,
        scope=scope,
        actor=actor,
        **manifest_kwargs,
    )
    return await authorize_and_install(service, record, payload=payload, actor=actor)


class PurgeSpy:
    """Janitor spy: records purge calls, optionally fails them."""

    def __init__(self, *, fail: bool = False) -> None:
        self.purged: list[str] = []
        self._fail = fail

    async def purge(self, record: object) -> tuple[str, ...]:
        name = f"{record.extension_id}@{record.version}"  # type: ignore[attr-defined]
        if self._fail:
            raise RuntimeError("simulated janitor outage")
        self.purged.append(name)
        return (f"owned:{name}",)


class TestPin:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_pin_holds_the_active_version_and_is_audited(self) -> None:
        service, _store, _loader, _clock = make_service()
        record = await activate(service)

        pinned = await service.pin(
            record.install_id, actor="operator-1", scope=SCOPE, reason="freeze the known-good"
        )

        assert pinned.pinned is True
        assert pinned.pinned_by == "operator-1"
        assert pinned.pinned_at is not None
        assert await service.pinned_record(SCOPE, record.extension_id) is pinned
        trail = await service.transitions(record.install_id, scope=SCOPE)
        last = trail[-1]
        assert last.from_state is ExtensionState.ACTIVE
        assert last.to_state is ExtensionState.ACTIVE
        assert last.actor == "operator-1"
        assert "pinned" in last.reason and "freeze the known-good" in last.reason

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_pinned_version_does_not_move_silently(self) -> None:
        """AC: update cannot silently change a pinned version.

        Activating another version while the pin stands is refused before any
        transition: the candidate stays AUTHORIZED, the pinned version stays
        active, and the trail of the pinned record is untouched.
        """
        service, _store, loader, _clock = make_service()
        first = await activate(service)
        await service.pin(first.install_id, actor="operator-1", scope=SCOPE, reason="hold")
        trail_before = await service.transitions(first.install_id, scope=SCOPE)

        candidate = await inspect_default(service, version="1.5.0", payload=OTHER_PAYLOAD)
        await service.authorize(
            candidate.install_id, actor="operator-1", scope=SCOPE, approve=True, reason="ok"
        )
        with pytest.raises(ExtensionPinned, match="pinned"):
            await service.install(
                candidate.install_id, actor="operator-1", scope=SCOPE, payload=OTHER_PAYLOAD
            )

        active = await service.active(SCOPE, "acme.chart_tools")
        assert active is not None and active.version == "1.4.0"
        assert active.pinned is True
        assert len(await service.transitions(first.install_id, scope=SCOPE)) == len(trail_before)
        assert len(loader.calls) == 1  # the refused activation never reached the loader

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_unpin_is_audited_and_allows_the_upgrade(self) -> None:
        service, _store, _loader, _clock = make_service()
        first = await activate(service)
        await service.pin(first.install_id, actor="operator-1", scope=SCOPE, reason="hold")

        await service.unpin(
            first.install_id, actor="operator-2", scope=SCOPE, reason="upgrade window"
        )
        assert await service.pinned_record(SCOPE, "acme.chart_tools") is None
        upgraded = await activate(service, version="1.5.0", payload=OTHER_PAYLOAD)
        active = await service.active(SCOPE, "acme.chart_tools")
        assert active is not None and active.version == "1.5.0"

        trail = await service.transitions(first.install_id, scope=SCOPE)
        unpin_events = [t for t in trail if "unpinned" in t.reason]
        assert len(unpin_events) == 1 and unpin_events[0].actor == "operator-2"
        retirement = trail[-1]
        assert retirement.to_state is ExtensionState.SUPERSEDED
        assert retirement.from_state is ExtensionState.ACTIVE
        assert upgraded.version == "1.5.0"

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_repin_and_unpin_of_an_unpinned_record_are_idempotent(self) -> None:
        service, _store, _loader, _clock = make_service()
        record = await activate(service)

        again = await service.pin(
            record.install_id, actor="operator-1", scope=SCOPE, reason="re-pin"
        )
        assert again.pinned is True
        trail = await service.transitions(record.install_id, scope=SCOPE)
        assert sum(1 for t in trail if "pinned" in t.reason) == 1

        unpinned = await service.unpin(
            record.install_id, actor="operator-1", scope=SCOPE, reason="release"
        )
        assert unpinned.pinned is False
        untouched = await service.unpin(
            record.install_id, actor="operator-1", scope=SCOPE, reason="again"
        )
        assert untouched.pinned is False
        trail = await service.transitions(record.install_id, scope=SCOPE)
        assert sum(1 for t in trail if "unpinned" in t.reason) == 1

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_pin_requires_an_active_record(self) -> None:
        service, _store, _loader, _clock = make_service()
        candidate = await inspect_default(service)
        with pytest.raises(InvalidTransition):
            await service.pin(candidate.install_id, actor="operator-1", scope=SCOPE, reason="early")

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_pin_refuses_a_second_pin_for_the_extension(self) -> None:
        """The one-pin invariant is enforced, not assumed.

        The only way two records of one extension can both carry ``pinned``
        is corrupt state, so the test writes a stale pinned record through
        the store directly and proves the service refuses to add a second.
        """
        store = InMemoryExtensionStore()
        service, _store, _loader, _clock = make_service(store=store)
        live = await activate(service, version="1.5.0", payload=OTHER_PAYLOAD)
        # Corrupt state: a second record of the same extension carries a pin.
        stale = await inspect_default(service, version="1.4.0")
        stale = replace(
            stale,
            state=ExtensionState.DISABLED,
            pinned=True,
            pinned_by="ghost-operator",
            pinned_at=stale.updated_at,
        )
        await store.save_record(stale)

        with pytest.raises(ExtensionPinned, match="already pinned"):
            await service.pin(live.install_id, actor="operator-1", scope=SCOPE, reason="second pin")

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_pin_demands_actor_and_reason(self) -> None:
        service, _store, _loader, _clock = make_service()
        record = await activate(service)
        with pytest.raises(ValueError, match="actor"):
            await service.pin(record.install_id, actor="  ", scope=SCOPE, reason="x")
        with pytest.raises(ValueError, match="reason"):
            await service.pin(record.install_id, actor="op", scope=SCOPE, reason=" ")


class TestDisableResume:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_disable_stops_new_use_immediately_and_keeps_evidence(self) -> None:
        """AC: disable immediately stops new extension use while preserving
        historical evidence.

        The resolution seam returns nothing the moment the disable lands,
        the scope's installed-versions view drops it, and the record keeps
        its manifest snapshot, frozen grant and artifact digest queryable.
        """
        service, _store, _loader, _clock = make_service()
        record = await activate(service)

        disabled = await service.disable(
            SCOPE, record.extension_id, actor="operator-1", reason="suspect release"
        )

        assert disabled.state is ExtensionState.DISABLED
        assert await service.active(SCOPE, record.extension_id) is None
        assert (await service._store.installed_versions(SCOPE)) == {}
        intact = await service.get(record.install_id, scope=SCOPE)
        assert intact.granted_permissions == record.granted_permissions
        assert intact.manifest.source_sha256 == record.manifest.source_sha256
        assert intact.artifact_sha256 == record.artifact_sha256

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_disable_is_audited(self) -> None:
        service, _store, _loader, _clock = make_service()
        record = await activate(service)
        await service.disable(
            SCOPE, record.extension_id, actor="operator-9", reason="suspect release"
        )
        trail = await service.transitions(record.install_id, scope=SCOPE)
        last = trail[-1]
        assert last.from_state is ExtensionState.ACTIVE
        assert last.to_state is ExtensionState.DISABLED
        assert last.actor == "operator-9" and "suspect release" in last.reason

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_resume_requires_the_bound_artifact_and_reruns_the_loader(self) -> None:
        service, _store, loader, _clock = make_service()
        record = await activate(service)
        await service.disable(SCOPE, record.extension_id, actor="op", reason="pause")
        loader.calls.clear()

        with pytest.raises(ArtifactMismatch):
            await service.resume(
                record.install_id,
                actor="op",
                scope=SCOPE,
                payload=b"tampered",
                reason="back",
            )
        still = await service.get(record.install_id, scope=SCOPE)
        assert still.state is ExtensionState.DISABLED

        resumed = await service.resume(
            record.install_id, actor="op", scope=SCOPE, payload=PAYLOAD, reason="all clear"
        )
        assert resumed.state is ExtensionState.ACTIVE
        active = await service.active(SCOPE, record.extension_id)
        assert active is not None and active.install_id == record.install_id
        assert [call[0] for call in loader.calls] == [record.install_id]
        trail = await service.transitions(record.install_id, scope=SCOPE)
        verbs = [t.reason for t in trail]
        assert any("resumed" in reason for reason in verbs)
        # The mandatory operator rationale is carried verbatim on the trail.
        assert any("all clear" in reason for reason in verbs)

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_disable_twice_is_idempotent(self) -> None:
        service, _store, _loader, _clock = make_service()
        record = await activate(service)
        first = await service.disable(SCOPE, record.extension_id, actor="op", reason="pause")
        trail_len = len(await service.transitions(record.install_id, scope=SCOPE))
        second = await service.disable(SCOPE, record.extension_id, actor="op", reason="pause again")
        assert second.state is ExtensionState.DISABLED
        assert second.install_id == first.install_id
        assert len(await service.transitions(record.install_id, scope=SCOPE)) == trail_len

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_disable_retry_after_a_newer_disable_returns_latest_record(self) -> None:
        """A repeated disable with no active pointer is idempotent on the most
        recently disabled record, not the oldest one: disabling 1.4.0, then
        installing and disabling 1.5.0, must report 1.5.0 on retry — the
        records iterate oldest-first, so the newest DISABLED wins."""
        service, _store, _loader, _clock = make_service()
        first = await activate(service)
        await service.disable(SCOPE, first.extension_id, actor="op", reason="pause 1.4.0")
        second = await activate(service, version="1.5.0", payload=OTHER_PAYLOAD)
        await service.disable(SCOPE, second.extension_id, actor="op", reason="pause 1.5.0")

        retry = await service.disable(
            SCOPE, second.extension_id, actor="op", reason="pause 1.5.0 again"
        )

        assert retry.state is ExtensionState.DISABLED
        assert retry.install_id == second.install_id
        assert retry.version == "1.5.0"
        assert retry.install_id != first.install_id

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_disable_of_an_unknown_extension_is_unknown(self) -> None:
        service, _store, _loader, _clock = make_service()
        await activate(service)
        with pytest.raises(UnknownInstall):
            await service.disable(SCOPE, "acme.nobody", actor="op", reason="nope")

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_resume_of_an_active_record_is_idempotent(self) -> None:
        """Retrying a resume after a crash cannot double-activate: an already
        ACTIVE record returns as-is, without another loader run."""
        service, _store, loader, _clock = make_service()
        record = await activate(service)
        loader.calls.clear()

        again = await service.resume(
            record.install_id, actor="op", scope=SCOPE, payload=PAYLOAD, reason="retry"
        )
        assert again.state is ExtensionState.ACTIVE
        assert loader.calls == []  # no second activation


class TestRollback:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_restores_the_superseded_version(self) -> None:
        """AC: rollback succeeds with proven compatible state.

        After a same-authority upgrade, rolling back re-crosses the loader
        with the original bound artifact, swaps the pointer back, and retires
        the newer version — audited on both trails.
        """
        service, _store, loader, _clock = make_service()
        first = await activate(service)
        upgraded = await activate(service, version="1.5.0", payload=OTHER_PAYLOAD)
        loader.calls.clear()

        rolled_back = await service.rollback(
            SCOPE,
            "acme.chart_tools",
            actor="operator-1",
            payload=PAYLOAD,
            reason="1.5.0 regressed",
        )

        assert rolled_back.install_id == first.install_id
        assert rolled_back.state is ExtensionState.ACTIVE
        active = await service.active(SCOPE, "acme.chart_tools")
        assert active is not None and active.version == "1.4.0"
        assert [call[0] for call in loader.calls] == [first.install_id]
        newer_trail = await service.transitions(upgraded.install_id, scope=SCOPE)
        assert newer_trail[-1].to_state is ExtensionState.SUPERSEDED
        older_trail = await service.transitions(first.install_id, scope=SCOPE)
        assert any("rolled back" in t.reason for t in older_trail)
        # The mandatory operator rationale is carried verbatim on the trail.
        assert any("1.5.0 regressed" in t.reason for t in older_trail)

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_refuses_broadened_authority_before_touching_state(self) -> None:
        """AC: broader authority always requires explicit new authorization.

        The superseded record's frozen grant declares a permission the
        current active grant lacks; the rollback is refused and neither the
        current record nor the target gains a single new transition.
        """
        service, _store, _loader, _clock = make_service()
        narrow = await activate(service, permissions=("network.http",))
        wider = await activate(
            service,
            version="1.5.0",
            permissions=("network.http", "storage.workspace"),
            payload=OTHER_PAYLOAD,
        )
        narrower_still = await activate(service, version="2.0.0", permissions=("network.http",))
        assert narrower_still.version == "2.0.0"

        target_trail = len(await service.transitions(wider.install_id, scope=SCOPE))
        current_trail = len(await service.transitions(narrower_still.install_id, scope=SCOPE))
        with pytest.raises(RollbackRefused, match=r"storage\.workspace"):
            await service.rollback(
                SCOPE,
                "acme.chart_tools",
                actor="op",
                payload=OTHER_PAYLOAD,
                reason="go back to 1.5.0",
                to_install_id=wider.install_id,
            )
        active = await service.active(SCOPE, "acme.chart_tools")
        assert active is not None and active.version == "2.0.0"
        assert active.granted_permissions == ("network.http",)
        assert len(await service.transitions(wider.install_id, scope=SCOPE)) == target_trail
        assert (
            len(await service.transitions(narrower_still.install_id, scope=SCOPE)) == current_trail
        )
        assert narrow is not None  # the old narrow version was never consulted

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_refuses_an_incompatible_target(self) -> None:
        """A target whose dependencies are no longer satisfied is refused.

        The superseded version declared a dependency on another extension;
        that dependency has since been disabled, so the target no longer
        evaluates compatible and the rollback must not corrupt the current
        state by half-restoring it.
        """
        service, _store, _loader, _clock = make_service()
        lib = await activate(service, extension_id="acme.lib", version="0.9.0")
        with_dep = await activate(
            service,
            version="1.4.0",
            dependencies=({"id": "acme.lib", "range": "*"},),
        )
        plain = await activate(service, version="1.5.0", payload=OTHER_PAYLOAD)
        await service.disable(SCOPE, "acme.lib", actor="op", reason="retire the lib")

        with pytest.raises(RollbackRefused, match=r"acme\.lib"):
            await service.rollback(
                SCOPE,
                "acme.chart_tools",
                actor="op",
                payload=PAYLOAD,
                reason="back to the dependency-using build",
                to_install_id=with_dep.install_id,
            )
        active = await service.active(SCOPE, "acme.chart_tools")
        assert active is not None and active.install_id == plain.install_id
        assert lib is not None

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_with_wrong_payload_records_nothing(self) -> None:
        service, _store, _loader, _clock = make_service()
        first = await activate(service)
        await activate(service, version="1.5.0", payload=OTHER_PAYLOAD)

        with pytest.raises(ArtifactMismatch):
            await service.rollback(
                SCOPE,
                "acme.chart_tools",
                actor="op",
                payload=b"not the artifact",
                reason="rollback",
            )
        first_trail = await service.transitions(first.install_id, scope=SCOPE)
        assert first_trail[-1].to_state is ExtensionState.SUPERSEDED

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_from_a_pinned_version_is_refused(self) -> None:
        service, _store, _loader, _clock = make_service()
        first = await activate(service)
        await activate(service, version="1.5.0", payload=OTHER_PAYLOAD)
        active = await service.active(SCOPE, "acme.chart_tools")
        assert active is not None and active.install_id != first.install_id
        await service.pin(active.install_id, actor="op", scope=SCOPE, reason="hold")

        with pytest.raises(ExtensionPinned):
            await service.rollback(
                SCOPE,
                "acme.chart_tools",
                actor="op",
                payload=PAYLOAD,
                reason="go back",
            )

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_retry_is_idempotent(self) -> None:
        service, _store, _loader, _clock = make_service()
        first = await activate(service)
        await activate(service, version="1.5.0", payload=OTHER_PAYLOAD)
        rolled = await service.rollback(
            SCOPE, "acme.chart_tools", actor="op", payload=PAYLOAD, reason="regression"
        )
        trail_len = len(await service.transitions(first.install_id, scope=SCOPE))

        again = await service.rollback(
            SCOPE,
            "acme.chart_tools",
            actor="op",
            payload=PAYLOAD,
            reason="retry after a crash",
            to_install_id=first.install_id,
        )
        assert again.install_id == rolled.install_id
        assert again.state is ExtensionState.ACTIVE
        assert len(await service.transitions(first.install_id, scope=SCOPE)) == trail_len

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_without_a_superseded_target_is_refused(self) -> None:
        service, _store, _loader, _clock = make_service()
        await activate(service)
        with pytest.raises(InvalidTransition, match="SUPERSEDED"):
            await service.rollback(
                SCOPE, "acme.chart_tools", actor="op", payload=PAYLOAD, reason="nothing to undo"
            )

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_rollback_refuses_a_record_of_another_extension(self) -> None:
        service, _store, _loader, _clock = make_service()
        await activate(service)
        other = await activate(service, extension_id="acme.lib", version="0.9.0")
        await service.disable(SCOPE, "acme.lib", actor="op", reason="park")
        with pytest.raises(UnknownInstall, match="not a record"):
            await service.rollback(
                SCOPE,
                "acme.chart_tools",
                actor="op",
                payload=PAYLOAD,
                reason="wrong target",
                to_install_id=other.install_id,
            )


class TestFailedActivationRetry:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_failed_rollback_cannot_reenter_through_the_install_gate(self) -> None:
        """A FAILED record is not a free initial-install retry.

        A rollback that passes its authority/compatibility gates but fails
        in the loader leaves the target FAILED. If a narrower version has
        since become active, reactivating the failed record through the
        ordinary install endpoint must re-prove those gates first — else the
        retry would activate authority the current grant does not hold
        without a fresh inspect → authorize pass.
        """
        service, store, _loader, _clock = make_service()
        wide = await activate(service, permissions=("network.http", "storage.workspace"))
        mid = await activate(
            service,
            version="1.5.0",
            permissions=("network.http", "storage.workspace"),
            payload=OTHER_PAYLOAD,
        )
        assert mid.state is ExtensionState.ACTIVE

        # The rollback's gates pass; the loader crashes. Wide ends FAILED and
        # the failed rollback moved nothing else.
        broken = ExtensionInstallService(
            store,
            loader=RecordingLoader(fail=True),
            trust_policy=POLICY,
            platform_api_version="1.0.0",
        )
        with pytest.raises(ExtensionLifecycleError, match="rolled back"):
            await broken.rollback(
                SCOPE,
                "acme.chart_tools",
                actor="op",
                payload=PAYLOAD,
                reason="1.5.0 regressed",
                to_install_id=wide.install_id,
            )
        failed = await store.get_record(wide.install_id)
        assert failed is not None and failed.state is ExtensionState.FAILED
        assert mid.state is ExtensionState.ACTIVE

        # A narrower version becomes active before anyone retries the failure.
        narrow = await activate(service, version="2.0.0", permissions=("network.http",))
        assert narrow.state is ExtensionState.ACTIVE

        trail = len(await service.transitions(wide.install_id, scope=SCOPE))
        narrow_trail = len(await service.transitions(narrow.install_id, scope=SCOPE))
        with pytest.raises(RollbackRefused, match=r"storage\.workspace"):
            await service.install(wide.install_id, actor="op", scope=SCOPE, payload=PAYLOAD)
        active = await service.active(SCOPE, "acme.chart_tools")
        assert active is not None and active.version == "2.0.0"
        assert len(await service.transitions(wide.install_id, scope=SCOPE)) == trail
        assert len(await service.transitions(narrow.install_id, scope=SCOPE)) == narrow_trail

        # The retry is not blanket-refused: once the active grant covers the
        # failed record's authority again, the ordinary retry re-crosses the
        # loader and swaps the pointer.
        await activate(
            service,
            version="2.1.0",
            permissions=("network.http", "storage.workspace"),
        )
        revived = await service.install(wide.install_id, actor="op", scope=SCOPE, payload=PAYLOAD)
        assert revived.state is ExtensionState.ACTIVE
        active = await service.active(SCOPE, "acme.chart_tools")
        assert active is not None and active.install_id == wide.install_id


class TestRemove:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_remove_stops_use_and_preserves_historical_evidence(self) -> None:
        """AC: remove does not delete canonical historical evidence.

        After removal the record is terminal for authority but every piece
        of provenance — manifest snapshot, artifact digest, frozen grant,
        full transition trail — remains queryable through the same seams.
        """
        service, _store, _loader, _clock = make_service()
        record = await activate(service)

        removed = await service.remove(
            record.install_id, actor="operator-1", scope=SCOPE, reason="obsolete"
        )

        assert removed.state is ExtensionState.REMOVED
        assert await service.active(SCOPE, record.extension_id) is None
        evidence = await service.get(record.install_id, scope=SCOPE)
        assert evidence.manifest.source_sha256 == record.manifest.source_sha256
        assert evidence.artifact_sha256 == record.artifact_sha256
        assert evidence.granted_permissions == record.granted_permissions
        trail = await service.transitions(record.install_id, scope=SCOPE)
        assert trail[-1].to_state is ExtensionState.REMOVED
        assert "obsolete" in trail[-1].reason

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_removed_record_is_terminal_for_authority(self) -> None:
        service, _store, _loader, _clock = make_service()
        first = await activate(service)
        newer = await activate(service, version="1.5.0", payload=OTHER_PAYLOAD)
        # Put the older version back in service so a version IS active.
        await service.rollback(
            SCOPE, "acme.chart_tools", actor="op", payload=PAYLOAD, reason="undo"
        )
        await service.remove(newer.install_id, actor="op", scope=SCOPE, reason="gone")

        with pytest.raises(InvalidTransition):
            await service.authorize(
                newer.install_id, actor="op", scope=SCOPE, approve=True, reason="zombie"
            )
        with pytest.raises(InvalidTransition, match="superseded record"):
            await service.rollback(
                SCOPE,
                "acme.chart_tools",
                actor="op",
                payload=PAYLOAD,
                reason="back from the dead",
                to_install_id=newer.install_id,
            )
        with pytest.raises(InvalidTransition):
            await service.resume(
                newer.install_id, actor="op", scope=SCOPE, payload=OTHER_PAYLOAD, reason="zombie"
            )
        # The active survivor is untouched by every refused operation.
        active = await service.active(SCOPE, first.extension_id)
        assert active is not None and active.install_id == first.install_id

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_janitor_failure_aborts_removal_with_the_record_untouched(self) -> None:
        """The janitor runs before any transition: a purge failure leaves the
        extension exactly as it was, with no half-removed state on the trail."""
        service, _store, _loader, _clock = make_service()
        record = await activate(service)
        failing = PurgeSpy(fail=True)
        trail_len = len(await service.transitions(record.install_id, scope=SCOPE))

        with pytest.raises(RuntimeError, match="janitor"):
            await service.remove(
                record.install_id, actor="op", scope=SCOPE, reason="cleanup", janitor=failing
            )

        still = await service.get(record.install_id, scope=SCOPE)
        assert still.state is ExtensionState.ACTIVE
        active = await service.active(SCOPE, record.extension_id)
        assert active is not None
        assert len(await service.transitions(record.install_id, scope=SCOPE)) == trail_len

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_removed_janitor_resources_are_recorded_on_the_trail(self) -> None:
        service, _store, _loader, _clock = make_service()
        record = await activate(service)
        spy = PurgeSpy()
        await service.remove(
            record.install_id, actor="op", scope=SCOPE, reason="cleanup", janitor=spy
        )
        assert spy.purged == ["acme.chart_tools@1.4.0"]
        trail = await service.transitions(record.install_id, scope=SCOPE)
        assert "owned:acme.chart_tools@1.4.0" in trail[-1].reason

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_default_policy_is_retain_all(self) -> None:
        """The epic requires removal to preserve history, so the default
        janitor retains every owned resource and says so on the trail."""
        service, _store, _loader, _clock = make_service()
        assert isinstance(service._janitor, RetainAllJanitor)
        record = await activate(service)
        await service.remove(record.install_id, actor="op", scope=SCOPE, reason="gone")
        trail = await service.transitions(record.install_id, scope=SCOPE)
        assert "retained" in trail[-1].reason

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_remove_clears_the_pin_and_the_pointer(self) -> None:
        service, _store, _loader, _clock = make_service()
        record = await activate(service)
        await service.pin(record.install_id, actor="op", scope=SCOPE, reason="hold")

        await service.remove(record.install_id, actor="op", scope=SCOPE, reason="gone")

        assert await service.pinned_record(SCOPE, record.extension_id) is None
        assert await service.active(SCOPE, record.extension_id) is None
        removed = await service.get(record.install_id, scope=SCOPE)
        assert removed.pinned is False

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_remove_twice_is_idempotent(self) -> None:
        service, _store, _loader, _clock = make_service()
        record = await activate(service)
        await service.remove(record.install_id, actor="op", scope=SCOPE, reason="gone")
        trail_len = len(await service.transitions(record.install_id, scope=SCOPE))
        again = await service.remove(record.install_id, actor="op", scope=SCOPE, reason="again")
        assert again.state is ExtensionState.REMOVED
        assert len(await service.transitions(record.install_id, scope=SCOPE)) == trail_len

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_remove_refuses_records_that_never_held_a_grant(self) -> None:
        service, _store, _loader, _clock = make_service()
        denied = await inspect_default(service)
        await service.authorize(
            denied.install_id, actor="op", scope=SCOPE, approve=False, reason="no"
        )
        with pytest.raises(InvalidTransition, match="removed"):
            await service.remove(denied.install_id, actor="op", scope=SCOPE, reason="tidy")

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_remove_of_a_disabled_record(self) -> None:
        service, _store, _loader, _clock = make_service()
        record = await activate(service)
        await service.disable(SCOPE, record.extension_id, actor="op", reason="pause")
        removed = await service.remove(
            record.install_id, actor="op", scope=SCOPE, reason="gone for good"
        )
        assert removed.state is ExtensionState.REMOVED
        assert await service.active(SCOPE, record.extension_id) is None


class TestUpgradeAuthority:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_broader_upgrade_parks_until_reauthorized(self) -> None:
        """AC: update cannot silently increase declared authority.

        The upgrade candidate's authority delta names exactly the new
        permission against the active grant; installation before the
        explicit decision is refused and the old version stays active; after
        approval the grant is the new snapshot's set — computed, not unioned.
        """
        service, _store, loader, _clock = make_service()
        first = await activate(service, permissions=("network.http",))
        assert first.granted_permissions == ("network.http",)

        upgrade = await inspect_default(
            service,
            version="1.5.0",
            permissions=("network.http", "storage.workspace"),
            payload=OTHER_PAYLOAD,
        )
        assert upgrade.state is ExtensionState.AWAITING_AUTHORIZATION
        assert upgrade.authority_delta == ("storage.workspace",)

        with pytest.raises(InvalidTransition):
            await service.install(
                upgrade.install_id, actor="op", scope=SCOPE, payload=OTHER_PAYLOAD
            )
        active = await service.active(SCOPE, "acme.chart_tools")
        assert active is not None and active.version == "1.4.0"

        await service.authorize(
            upgrade.install_id,
            actor="operator-2",
            scope=SCOPE,
            approve=True,
            reason="needs storage",
        )
        upgraded = await service.install(
            upgrade.install_id, actor="op", scope=SCOPE, payload=OTHER_PAYLOAD
        )
        assert upgraded.granted_permissions == ("network.http", "storage.workspace")
        assert upgraded.authorized_by == "operator-2"
        active = await service.active(SCOPE, "acme.chart_tools")
        assert active is not None and active.version == "1.5.0"
        old = await service.get(first.install_id, scope=SCOPE)
        assert old.state is ExtensionState.SUPERSEDED
        assert old.granted_permissions == ("network.http",)  # frozen, untouched
        assert len(loader.calls) == 2

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_same_authority_upgrade_changes_exactly_the_snapshot(self) -> None:
        """AC: compatible same-authority upgrades apply without silently
        changing permissions — the grant afterwards is exactly the new
        snapshot's requested set, identical to the old one here."""
        service, _store, _loader, _clock = make_service()
        first = await activate(service)
        upgraded = await activate(service, version="1.5.0", payload=OTHER_PAYLOAD)

        assert upgraded.granted_permissions == first.granted_permissions
        assert upgraded.requested_permissions == first.requested_permissions

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_superseded_record_keeps_its_snapshot_queryable(self) -> None:
        """AC: active version and publisher provenance are queryable — for
        the retired version too: publisher, digest and manifest survive the
        displacement."""
        service, _store, _loader, _clock = make_service()
        first = await activate(service)
        await activate(service, version="1.5.0", payload=OTHER_PAYLOAD)

        old = await service.get(first.install_id, scope=SCOPE)
        assert old.state is ExtensionState.SUPERSEDED
        assert old.manifest.publisher == "acme"
        assert old.artifact_sha256 == _digest(PAYLOAD)
        assert old.manifest.source_sha256 is not None
        assert await service.pinned_record(SCOPE, "acme.chart_tools") is None


class TestAuditAndIsolation:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_every_lifecycle_operation_is_audited_with_actor_scope_reason(
        self,
    ) -> None:
        """AC: all lifecycle transitions emit canonical auditable evidence."""
        service, _store, _loader, _clock = make_service()
        first = await activate(service)
        await service.pin(first.install_id, actor="op-pin", scope=SCOPE, reason="hold")
        await service.unpin(first.install_id, actor="op-unpin", scope=SCOPE, reason="release")
        second = await activate(service, version="1.5.0", payload=OTHER_PAYLOAD)
        await service.rollback(
            SCOPE, "acme.chart_tools", actor="op-rollback", payload=PAYLOAD, reason="undo"
        )
        await service.disable(SCOPE, "acme.chart_tools", actor="op-disable", reason="pause")
        await service.resume(
            first.install_id, actor="op-resume", scope=SCOPE, payload=PAYLOAD, reason="back"
        )
        await service.remove(second.install_id, actor="op-remove", scope=SCOPE, reason="gone")

        actors = {"op-pin", "op-unpin", "op-rollback", "op-disable", "op-resume", "op-remove"}
        seen: set[str] = set()
        for install_id in (first.install_id, second.install_id):
            for transition in await service.transitions(install_id, scope=SCOPE):
                assert transition.actor
                assert transition.org_id == SCOPE.org_id
                assert transition.workspace_id == SCOPE.workspace_id
                assert transition.extension_id == "acme.chart_tools"
                assert transition.version
                assert transition.reason.strip()
                if transition.actor in actors:
                    seen.add(transition.actor)
        assert seen == actors

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_lifecycle_operations_are_scope_checked(self) -> None:
        service, _store, _loader, _clock = make_service()
        record = await activate(service)
        foreign = ExtensionScope(org_id="org-2", workspace_id="ws-9")

        with pytest.raises(UnknownInstall):
            await service.pin(record.install_id, actor="op", scope=foreign, reason="x")
        with pytest.raises(UnknownInstall):
            await service.remove(record.install_id, actor="op", scope=foreign, reason="x")
        with pytest.raises(UnknownInstall):
            await service.resume(
                record.install_id, actor="op", scope=foreign, payload=PAYLOAD, reason="x"
            )
        # Still intact in its own scope.
        active = await service.active(SCOPE, record.extension_id)
        assert active is not None and active.state is ExtensionState.ACTIVE

    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_new_states_cannot_reach_active_without_the_loader(self) -> None:
        """DISABLED and SUPERSEDED return only through the loader seam.

        Resume of a disabled record whose loader is unwired fails closed:
        the record stays DISABLED, the pointer stays unset, nothing runs.
        """
        from extensions.test_install_lifecycle import UnwiredExtensionLoader

        # UnwiredLoader cannot even activate the first install; drive one
        # with a real loader, then swap the service's loader seam.
        working, store, _loader, clock = make_service()
        record = await activate(working)
        await working.disable(SCOPE, record.extension_id, actor="op", reason="pause")

        resumed_service = ExtensionInstallService(
            store,
            loader=UnwiredExtensionLoader(),
            trust_policy=POLICY,
            platform_api_version="1.0.0",
            clock=clock,
        )
        from maistro.extensions import ExtensionLifecycleError

        with pytest.raises(ExtensionLifecycleError, match="resumed"):
            await resumed_service.resume(
                record.install_id, actor="op", scope=SCOPE, payload=PAYLOAD, reason="back"
            )
        # The truthful failure state is recorded, and — the fail-closed
        # property that matters — the extension did NOT come back into use.
        still = await working.get(record.install_id, scope=SCOPE)
        assert still.state is ExtensionState.FAILED
        assert await working.active(SCOPE, record.extension_id) is None


class TestConcurrentActivation:
    @pytest.mark.contract("behavioral")
    @pytest.mark.scope("unit")
    async def test_concurrent_installs_of_one_extension_leave_exactly_one_active(self) -> None:
        """Two separately authorized installs of the same scoped extension race:
        their distinct install-id record locks never contend, so the pointer
        swap and supersede must be serialized per (scope, extension). The
        loser must end SUPERSEDED — never ACTIVE under a pointer naming the
        winner."""
        service, store, _loader, _clock = make_service()

        # The in-memory store has no suspension points, so the read-prior →
        # supersede → set-active tail is accidentally atomic in a single event
        # loop. Yield inside ``active_record`` and ``set_active`` to open the
        # window where both racers could otherwise capture the same prior
        # active record before either finishes its pointer swap.
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
            record = await inspect_default(
                service,
                version=version,
                payload=payload,
                permissions=("network.http",),
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

        first = await authorize_then_install("1.0.0", PAYLOAD)
        candidate_a, candidate_b = await asyncio.gather(
            authorize_then_install("1.1.0", OTHER_PAYLOAD),
            authorize_then_install("1.2.0", THIRD_PAYLOAD),
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
