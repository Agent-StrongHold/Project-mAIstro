"""The post-install extension lifecycle over HTTP (#954, M9-B3).

The routes are the operator surface of pin / upgrade / rollback / disable /
resume / remove. These tests drive the real service through the real router
and pin the issue's acceptance criteria at the HTTP boundary: same-authority
upgrades carry an empty authority delta, broader authority demands the
explicit decision before activation, refused rollbacks leave the active
version untouched, disable flips resolution to 404 immediately, removal
keeps the audit trail queryable, and every write attributes the
authenticated principal.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.extensions import InMemoryExtensionStore, TrustPolicy
from maistro.extensions.service import (
    ExtensionCodeLoader,
    ExtensionInstallService,
    LoadedExtension,
)
from maistro.workspaces import InMemoryWorkspaceStore, WorkspaceRole
from maistro_server.api import extensions as extensions_api
from maistro_server.api import workspaces as workspace_api
from maistro_server.api.auth import verify_api_key
from maistro_server.api.principal import AuthenticatedPrincipal

PAYLOAD_V1 = b"extension-payload-v1"
PAYLOAD_V2 = b"extension-payload-v2"

TRUST_BODY = {
    "publisher_id": "acme",
    "signature_present": True,
    "signer_key_id": "key-1",
    "package_sha256": "",
}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _manifest_text(
    *,
    extension_id: str = "acme.chart_tools",
    version: str = "1.4.0",
    publisher: str = "acme",
    permissions: tuple[str, ...] = ("network.http", "storage.workspace"),
    payload: bytes = PAYLOAD_V1,
) -> str:
    document = {
        "manifest_version": 1,
        "id": extension_id,
        "name": "Chart Tools",
        "version": version,
        "publisher": publisher,
        "api_version": "1.0.0",
        "permissions": list(permissions),
        "entry_points": [{"name": "main", "module": "acme_chart.main", "attribute": "activate"}],
        "artifact": {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        },
    }
    return json.dumps(document)


def _trust_body(payload: bytes) -> dict:
    return {**TRUST_BODY, "package_sha256": hashlib.sha256(payload).hexdigest()}


class RecordingLoader(ExtensionCodeLoader):
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes]] = []

    async def load(self, record: object, payload: bytes) -> LoadedExtension:
        from maistro.extensions.types import ExtensionInstallRecord

        assert isinstance(record, ExtensionInstallRecord)
        self.calls.append((record.install_id, bytes(payload)))
        return LoadedExtension(extension_id=record.extension_id, version=record.version)


class _Harness:
    def __init__(self, client: TestClient, service: ExtensionInstallService) -> None:
        self.client = client
        self.service = service

    def inspect(
        self,
        *,
        org_id: str = "org-1",
        workspace_id: str = "ws-1",
        payload: bytes = PAYLOAD_V1,
        **manifest_kwargs: object,
    ) -> dict:
        return self.client.post(
            "/extensions/inspections",
            json={
                "org_id": org_id,
                "workspace_id": workspace_id,
                "manifest_text": _manifest_text(payload=payload, **manifest_kwargs),  # type: ignore[arg-type]
                "payload_b64": _b64(payload),
                "trust": _trust_body(payload),
            },
        )

    def authorize(
        self,
        install_id: str,
        *,
        approve: bool = True,
        org_id: str = "org-1",
        workspace_id: str = "ws-1",
        reason: str = "reviewed",
    ) -> dict:
        return self.client.post(
            f"/extensions/installations/{install_id}/authorization",
            json={
                "org_id": org_id,
                "workspace_id": workspace_id,
                "approve": approve,
                "reason": reason,
            },
        )

    def install(
        self,
        install_id: str,
        *,
        payload: bytes = PAYLOAD_V1,
        org_id: str = "org-1",
        workspace_id: str = "ws-1",
    ) -> dict:
        return self.client.post(
            f"/extensions/installations/{install_id}/installation",
            json={
                "org_id": org_id,
                "workspace_id": workspace_id,
                "payload_b64": _b64(payload),
            },
        )

    def install_active(
        self,
        *,
        version: str = "1.4.0",
        payload: bytes = PAYLOAD_V1,
        extension_id: str = "acme.chart_tools",
        permissions: tuple[str, ...] = ("network.http", "storage.workspace"),
        actor: str = "operator-1",
    ) -> dict:
        inspected = self.inspect(
            version=version,
            payload=payload,
            extension_id=extension_id,
            permissions=permissions,
        )
        assert inspected.status_code == 201, inspected.text
        record = inspected.json()
        decided = self.authorize(record["install_id"], reason="reviewed")
        assert decided.status_code == 200, decided.text
        installed = self.install(record["install_id"], payload=payload)
        assert installed.status_code == 200, installed.text
        return installed.json()

    def upgrade(self, *, version: str = "1.5.0", payload: bytes = PAYLOAD_V2, **kwargs: object):
        return self.client.post(
            "/extensions/upgrades",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "manifest_text": _manifest_text(version=version, payload=payload, **kwargs),  # type: ignore[arg-type]
                "payload_b64": _b64(payload),
                "trust": _trust_body(payload),
            },
        )

    def activate_upgrade(self, install_id: str, *, payload: bytes = PAYLOAD_V2):
        return self.client.post(
            f"/extensions/installations/{install_id}/upgrade-activation",
            json={"org_id": "org-1", "workspace_id": "ws-1", "payload_b64": _b64(payload)},
        )

    def rollback(self, install_id: str, *, payload: bytes = PAYLOAD_V1, **body: object):
        return self.client.post(
            f"/extensions/installations/{install_id}/rollback",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "payload_b64": _b64(payload),
                "reason": str(body.pop("reason", "regression")),
                **body,
            },
        )

    def disable(self, install_id: str, *, reason: str = "suspected"):
        return self.client.post(
            f"/extensions/installations/{install_id}/disable",
            json={"org_id": "org-1", "workspace_id": "ws-1", "reason": reason},
        )

    def resume(self, install_id: str, *, payload: bytes = PAYLOAD_V1):
        return self.client.post(
            f"/extensions/installations/{install_id}/resume",
            json={"org_id": "org-1", "workspace_id": "ws-1", "payload_b64": _b64(payload)},
        )

    def remove(self, install_id: str, *, reason: str = "sunset"):
        return self.client.post(
            f"/extensions/installations/{install_id}/removal",
            json={"org_id": "org-1", "workspace_id": "ws-1", "reason": reason},
        )

    def resolution(self, *, extension_id: str = "acme.chart_tools"):
        return self.client.get(
            "/extensions/resolution",
            params={"org_id": "org-1", "workspace_id": "ws-1", "extension_id": extension_id},
        )


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        token=f"token-{user_id}",
        roles=frozenset({"user"}),
    )


TRUST_POLICY = TrustPolicy(
    trusted_publishers=frozenset({"acme"}),
    require_signature=True,
    allowed_signer_keys=frozenset({"key-1"}),
)


@pytest.fixture
async def harness() -> AsyncIterator[tuple[_Harness, InMemoryWorkspaceStore, RecordingLoader]]:
    loader = RecordingLoader()
    service = ExtensionInstallService(
        InMemoryExtensionStore(),
        loader=loader,
        trust_policy=TRUST_POLICY,
        platform_api_version="1.0.0",
        clock=lambda: datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC),
        authorization_ttl=timedelta(minutes=15),
    )
    workspaces = InMemoryWorkspaceStore()
    app = FastAPI()
    app.state.container = SimpleNamespace(ensure_extension_install_service=lambda: service)
    app.include_router(extensions_api.router)
    workspace_api.configure_workspace_store(workspaces)
    client = TestClient(app)
    try:
        yield _Harness(client, service), workspaces, loader
    finally:
        client.close()
        app.dependency_overrides.clear()
        workspace_api.configure_workspace_store(None)


def _login(app: FastAPI, user_id: str) -> None:
    app.dependency_overrides[verify_api_key] = lambda: _principal(user_id)


def _own_workspace(workspaces: InMemoryWorkspaceStore, owner: str, workspace_id: str) -> None:
    import asyncio

    async def create() -> None:
        await workspaces.create(creator_user_id=owner, name="Extensions", workspace_id=workspace_id)

    asyncio.run(create())


def _admit_member(workspaces: InMemoryWorkspaceStore, workspace_id: str, user_id: str) -> None:
    import asyncio

    async def admit() -> None:
        await workspaces.set_membership(workspace_id, user_id=user_id, role=WorkspaceRole.OWNER)

    asyncio.run(admit())


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestUpgradeRoutes:
    def test_same_authority_upgrade_reports_empty_delta_and_activates(self, harness) -> None:
        """AC: compatible same-authority upgrades apply without silently
        changing permissions — visible end to end over HTTP."""
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        v1 = h.install_active()
        assert v1["state"] == "active"

        upgrade = h.upgrade()
        assert upgrade.status_code == 201, upgrade.text
        body = upgrade.json()
        assert body["preflight"]["allowed"] is True
        assert body["preflight"]["authority"]["new"] == []
        assert body["preflight"]["from_version"] == "1.4.0"
        assert body["preflight"]["to_version"] == "1.5.0"
        assert body["record"]["state"] == "awaiting_authorization"

        decided = h.authorize(body["record"]["install_id"], reason="reviewed")
        assert decided.status_code == 200
        activated = h.activate_upgrade(body["record"]["install_id"])
        assert activated.status_code == 200, activated.text
        assert activated.json()["state"] == "active"
        assert activated.json()["version"] == "1.5.0"
        assert activated.json()["granted_permissions"] == v1["granted_permissions"], (
            "permissions must not change silently"
        )

        resolution = h.resolution()
        assert resolution.status_code == 200
        assert resolution.json()["install_id"] == body["record"]["install_id"]

    def test_broader_authority_blocks_activation_until_authorized(self, harness) -> None:
        """AC: broader authority always requires explicit new authorization."""
        h, workspaces, loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        h.install_active()
        calls_before = len(loader.calls)

        upgrade = h.upgrade(
            version="1.5.0",
            permissions=("network.http", "storage.workspace", "filesystem.read"),
        )
        assert upgrade.status_code == 201
        body = upgrade.json()
        assert body["preflight"]["authority"]["new"] == ["filesystem.read"]
        assert body["preflight"]["broadens_authority"] is True
        assert body["record"]["authority_delta"] == ["filesystem.read"]

        early = h.activate_upgrade(body["record"]["install_id"])
        assert early.status_code == 409
        assert len(loader.calls) == calls_before, "activation before decision must not run code"

        decided = h.authorize(body["record"]["install_id"], reason="delta approved")
        assert decided.status_code == 200
        activated = h.activate_upgrade(body["record"]["install_id"])
        assert activated.status_code == 200
        assert activated.json()["granted_permissions"] == [
            "network.http",
            "storage.workspace",
            "filesystem.read",
        ]

    def test_pinned_extension_refuses_the_upgrade_with_409(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        h.install_active()

        pinned = h.client.post(
            "/extensions/pins",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "extension_id": "acme.chart_tools",
                "reason": "freeze for the quarter",
            },
        )
        assert pinned.status_code == 201, pinned.text
        assert pinned.json()["version"] == "1.4.0"
        assert pinned.json()["pinned_by"] == "operator-1"

        refused = h.upgrade()
        assert refused.status_code == 409
        assert "pinned at 1.4.0" in refused.json()["detail"]

        # Resolution and the active record are untouched by the refusal.
        assert h.resolution().json()["version"] == "1.4.0"

        released = h.client.post(
            "/extensions/pins/release",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "extension_id": "acme.chart_tools",
                "reason": "quarter closed",
            },
        )
        assert released.status_code == 200
        assert [event["action"] for event in released.json()["events"]] == ["pin", "unpin"]

        upgrade = h.upgrade()
        assert upgrade.status_code == 201
        record = upgrade.json()["record"]
        h.authorize(record["install_id"], reason="now allowed")
        activated = h.activate_upgrade(record["install_id"])
        assert activated.status_code == 200
        assert activated.json()["version"] == "1.5.0"

    def test_downgrade_and_same_version_new_bytes_are_refused(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        h.install_active(version="1.4.0")

        older = h.upgrade(version="1.0.0")
        assert older.status_code == 409
        assert "rollback, not an upgrade" in older.json()["detail"]

        tampered = h.upgrade(version="1.4.0", payload=PAYLOAD_V2)
        assert tampered.status_code == 409
        assert "different manifest bytes" in tampered.json()["detail"]


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestRollbackRoutes:
    def _install_and_upgrade(self, h: _Harness) -> tuple[dict, dict]:
        v1 = h.install_active(version="1.4.0", payload=PAYLOAD_V1)
        upgrade = h.upgrade(version="1.5.0", payload=PAYLOAD_V2)
        assert upgrade.status_code == 201
        record = upgrade.json()["record"]
        h.authorize(record["install_id"], reason="ok")
        v2 = h.activate_upgrade(record["install_id"])
        assert v2.status_code == 200
        return v1, v2.json()

    def test_rollback_restores_the_previous_version(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        v1, v2 = self._install_and_upgrade(h)

        rolled = h.rollback(v1["install_id"], reason="regression in 1.5.0")
        assert rolled.status_code == 200, rolled.text
        assert rolled.json()["state"] == "active"
        assert rolled.json()["version"] == "1.4.0"
        assert h.resolution().json()["install_id"] == v1["install_id"]

        trail = h.client.get(
            f"/extensions/installations/{v2['install_id']}/transitions",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        assert trail.status_code == 200
        assert trail.json()[-1]["to_state"] == "superseded"
        assert "rolled back to 1.4.0" in trail.json()[-1]["reason"]

    def test_rollback_with_wrong_payload_answers_409_and_changes_nothing(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        v1, v2 = self._install_and_upgrade(h)

        refused = h.rollback(v1["install_id"], payload=b"tampered")
        assert refused.status_code == 409
        assert h.resolution().json()["install_id"] == v2["install_id"]

    def test_rollback_broadening_authority_requires_the_flag(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        v1 = h.install_active(
            version="1.4.0",
            payload=PAYLOAD_V1,
            permissions=("network.http", "storage.workspace", "filesystem.read"),
        )
        upgrade = h.upgrade(version="1.5.0", payload=PAYLOAD_V2, permissions=("network.http",))
        record = upgrade.json()["record"]
        h.authorize(record["install_id"], reason="narrowing accepted")
        v2 = h.activate_upgrade(record["install_id"])
        assert v2.status_code == 200

        refused = h.rollback(v1["install_id"])
        assert refused.status_code == 409
        assert "filesystem.read" in refused.json()["detail"]
        assert h.resolution().json()["install_id"] == v2.json()["install_id"]

        allowed = h.rollback(v1["install_id"], allow_broadened=True)
        assert allowed.status_code == 200
        assert allowed.json()["granted_permissions"] == [
            "network.http",
            "storage.workspace",
            "filesystem.read",
        ]


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestDisableResumeRemoveRoutes:
    def test_disable_flips_resolution_to_404_and_resume_restores_it(self, harness) -> None:
        """AC: disable prevents new invocations immediately while history is
        preserved — the resolution seam answers 404 the moment disable
        returns, and the transition trail stays queryable."""
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        active = h.install_active()
        assert h.resolution().status_code == 200

        disabled = h.disable(active["install_id"], reason="suspected bad outputs")
        assert disabled.status_code == 200
        assert disabled.json()["state"] == "disabled"
        assert h.resolution().status_code == 404

        trail = h.client.get(
            f"/extensions/installations/{active['install_id']}/transitions",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        states = [t["to_state"] for t in trail.json()]
        assert states[-1] == "disabled"
        assert "active" in states, "history must be preserved"

        resumed = h.resume(active["install_id"])
        assert resumed.status_code == 200
        assert resumed.json()["state"] == "active"
        assert resumed.json()["granted_permissions"] == active["granted_permissions"]
        assert h.resolution().status_code == 200

    def test_remove_keeps_record_and_trails_queryable(self, harness) -> None:
        """AC: remove does not delete canonical historical evidence."""
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        active = h.install_active()

        removed = h.remove(active["install_id"], reason="contract ended")
        assert removed.status_code == 200
        assert removed.json()["state"] == "removed"
        assert h.resolution().status_code == 404

        fetched = h.client.get(
            f"/extensions/installations/{active['install_id']}",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        assert fetched.status_code == 200
        assert fetched.json()["state"] == "removed"
        trail = h.client.get(
            f"/extensions/installations/{active['install_id']}/transitions",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        assert [t["to_state"] for t in trail.json()] == [
            "awaiting_authorization",
            "authorized",
            "installing",
            "active",
            "removed",
        ]

    def test_remove_is_idempotent_and_the_removal_notes_are_listed(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        active = h.install_active()
        first = h.remove(active["install_id"])
        assert first.status_code == 200
        again = h.remove(active["install_id"], reason="retry")
        assert again.status_code == 200
        assert again.json()["state"] == "removed"

        notes = h.client.get(
            f"/extensions/installations/{active['install_id']}/removal-notes",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        assert notes.status_code == 200
        assert notes.json() == []  # no janitor wired: retain-everything default


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestResolutionAndReconciliationRoutes:
    def test_resolution_answers_404_for_unknown_extensions(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        assert h.resolution(extension_id="acme.absent").status_code == 404

    def test_reconciliation_requires_scope_authority_and_repairs(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        h.install_active()
        response = h.client.post(
            "/extensions/reconciliation",
            json={"org_id": "org-1", "workspace_id": "ws-1", "extension_id": "acme.chart_tools"},
        )
        assert response.status_code == 200
        assert response.json() == {"repaired": 0}

        # A non-member of the workspace must not run maintenance.
        _login(h.client.app, "intruder")  # type: ignore[attr-defined]
        denied = h.client.post(
            "/extensions/reconciliation",
            json={"org_id": "org-1", "workspace_id": "ws-1", "extension_id": "acme.chart_tools"},
        )
        assert denied.status_code in (401, 403, 404)  # no existence leak


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestAttribution:
    def test_lifecycle_writes_attribute_the_authenticated_principal(self, harness) -> None:
        """Every B3 write must name the authenticated principal — the pin by
        its owner, the disable/remove by their transition actor."""
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _admit_member(workspaces, "ws-1", "operator-2")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        active = h.install_active()  # installed by operator-1

        _login(h.client.app, "operator-2")  # type: ignore[attr-defined]
        pinned = h.client.post(
            "/extensions/pins",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "extension_id": "acme.chart_tools",
                "reason": "hold",
            },
        )
        assert pinned.json()["pinned_by"] == "operator-2"
        h.client.post(
            "/extensions/pins/release",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "extension_id": "acme.chart_tools",
                "reason": "release",
            },
        )
        disabled = h.disable(active["install_id"], reason="ops")
        assert disabled.status_code == 200
        removed = h.remove(active["install_id"], reason="done")
        assert removed.status_code == 200

        trail = h.client.get(
            f"/extensions/installations/{active['install_id']}/transitions",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        ).json()
        actors = {t["actor"] for t in trail}
        assert "operator-1" in actors, "the installer must be attributed"
        assert "operator-2" in actors, "the disable/remove actor must be attributed"
        disable_transition = next(t for t in trail if t["to_state"] == "disabled")
        assert disable_transition["actor"] == "operator-2"
