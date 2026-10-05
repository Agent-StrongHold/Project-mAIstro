"""The governed extension install lifecycle over HTTP (#953, M9-B2).

The routes are the operator surface of the inspect → authorize → install
state machine. These tests drive the real service through the real router:
the happy path, the denial path, scope containment, the fail-closed default
loader, and the audit trail endpoint.
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

from maistro.extensions import (
    InMemoryExtensionStore,
    TrustPolicy,
)
from maistro.extensions.service import (
    ExtensionCodeLoader,
    ExtensionInstallService,
    LoadedExtension,
    UnwiredExtensionLoader,
)
from maistro.workspaces import InMemoryWorkspaceStore, WorkspaceRole
from maistro_server.api import extensions as extensions_api
from maistro_server.api import workspaces as workspace_api
from maistro_server.api.auth import verify_api_key
from maistro_server.api.principal import AuthenticatedPrincipal

PAYLOAD = b"extension-payload-v1"


def _payload_b64(data: bytes = PAYLOAD) -> str:
    return base64.b64encode(data).decode()


def _manifest_text(
    *,
    extension_id: str = "acme.chart_tools",
    version: str = "1.4.0",
    publisher: str = "acme",
    permissions: tuple[str, ...] = ("network.http", "storage.workspace"),
    payload: bytes = PAYLOAD,
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
        **manifest_kwargs: object,
    ) -> dict:
        return self.client.post(
            "/extensions/inspections",
            json={
                "org_id": org_id,
                "workspace_id": workspace_id,
                "manifest_text": _manifest_text(**manifest_kwargs),  # type: ignore[arg-type]
                "payload_b64": _payload_b64(),
                "trust": {
                    "publisher_id": str(manifest_kwargs.get("publisher", "acme")),
                    "signature_present": True,
                    "signer_key_id": "key-1",
                    "package_sha256": hashlib.sha256(PAYLOAD).hexdigest(),
                },
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
        payload_b64: str | None = None,
        org_id: str = "org-1",
        workspace_id: str = "ws-1",
    ) -> dict:
        return self.client.post(
            f"/extensions/installations/{install_id}/installation",
            json={
                "org_id": org_id,
                "workspace_id": workspace_id,
                "payload_b64": payload_b64 or _payload_b64(),
            },
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


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestHappyPath:
    def test_inspect_authorize_install_over_http(self, harness) -> None:
        h, workspaces, loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]

        inspected = h.inspect()
        assert inspected.status_code == 201, inspected.text
        record = inspected.json()
        assert record["state"] == "awaiting_authorization"
        assert record["requested_permissions"] == ["network.http", "storage.workspace"]
        assert record["manifest"]["source_sha256"]
        assert record["authority_delta"] == ["network.http", "storage.workspace"]

        decided = h.authorize(record["install_id"]).json()
        assert decided["state"] == "authorized"
        assert decided["granted_permissions"] == ["network.http", "storage.workspace"]
        assert decided["authorized_by"] == "operator-1"

        installed = h.install(record["install_id"]).json()
        assert installed["state"] == "active"
        assert loader.calls == [(record["install_id"], PAYLOAD)]

        active = h.client.get(
            "/extensions/active",
            params={"org_id": "org-1", "workspace_id": "ws-1", "extension_id": "acme.chart_tools"},
        )
        assert active.status_code == 200
        assert active.json()["install_id"] == record["install_id"]

    def test_rejection_is_a_201_with_truthful_state(self, harness) -> None:
        h, workspaces, loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        response = h.inspect(publisher="untrusted-co")
        assert response.status_code == 201
        assert response.json()["state"] == "rejected"
        assert "publisher" in response.json()["failure_reason"]
        assert loader.calls == []

    def test_invalid_manifest_is_422_and_creates_no_record(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        response = h.client.post(
            "/extensions/inspections",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "manifest_text": "not json at all",
                "payload_b64": _payload_b64(),
                "trust": {
                    "publisher_id": "acme",
                    "signature_present": True,
                    "signer_key_id": "key-1",
                },
            },
        )
        assert response.status_code == 422
        assert "not valid UTF-8 JSON" in response.json()["detail"]

    def test_bad_base64_payload_is_422(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        response = h.client.post(
            "/extensions/inspections",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "manifest_text": _manifest_text(),
                "payload_b64": "!!!not-base64!!!",
                "trust": {
                    "publisher_id": "acme",
                    "signature_present": True,
                    "signer_key_id": "key-1",
                },
            },
        )
        assert response.status_code == 422


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestDenialAndScopeContainment:
    def test_denied_authorization_cannot_install(self, harness) -> None:
        h, workspaces, loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        install_id = h.inspect().json()["install_id"]
        denied = h.authorize(install_id, approve=False, reason="not approved by policy")
        assert denied.json()["state"] == "denied"
        refused = h.install(install_id)
        assert refused.status_code == 409
        assert refused.json()["detail"]
        assert loader.calls == []

    def test_foreign_scope_gets_404_without_existence_leak(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        install_id = h.inspect().json()["install_id"]

        foreign = h.authorize(install_id, org_id="org-2")
        assert foreign.status_code == 404
        assert "no install record" in foreign.json()["detail"]

        foreign_install = h.install(install_id, org_id="org-2")
        assert foreign_install.status_code == 404

        read = h.client.get(
            f"/extensions/installations/{install_id}",
            params={"org_id": "org-2", "workspace_id": "ws-1"},
        )
        assert read.status_code == 404

    def test_workspace_writes_require_administer_membership(self, harness) -> None:
        import asyncio

        h, workspaces, _loader = harness
        _own_workspace(workspaces, "owner-1", "ws-1")

        async def add_member() -> None:
            await workspaces.set_membership(
                "ws-1", user_id="plain-member", role=WorkspaceRole.MEMBER
            )

        asyncio.run(add_member())
        _login(h.client.app, "plain-member")  # type: ignore[attr-defined]
        response = h.inspect()
        assert response.status_code == 403

        # The owner can proceed through the whole flow.
        _login(h.client.app, "owner-1")  # type: ignore[attr-defined]
        inspected = h.inspect()
        assert inspected.status_code == 201


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestAuditTrailEndpoint:
    def test_transitions_carry_actor_scope_version_reason(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        install_id = h.inspect().json()["install_id"]
        h.authorize(install_id, reason="quarterly review")
        h.install(install_id)

        response = h.client.get(
            f"/extensions/installations/{install_id}/transitions",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        assert response.status_code == 200
        trail = response.json()
        assert [t["to_state"] for t in trail] == [
            "awaiting_authorization",
            "authorized",
            "installing",
            "active",
        ]
        for entry in trail:
            assert entry["actor"] == "operator-1"
            assert entry["org_id"] == "org-1"
            assert entry["workspace_id"] == "ws-1"
            assert entry["extension_id"] == "acme.chart_tools"
            assert entry["version"] == "1.4.0"
            assert entry["reason"].strip()

    def test_record_read_displays_snapshot_permissions(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        install_id = h.inspect().json()["install_id"]
        record = h.client.get(
            f"/extensions/installations/{install_id}",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        assert record.status_code == 200
        assert record.json()["requested_permissions"] == [
            "network.http",
            "storage.workspace",
        ]

    def test_expiry_sweep_abandons_expired_requests(self, harness) -> None:
        """The durable guarantee: an expired request is abandoned by the
        sweep, and an abandoned record can never be installed."""
        import asyncio
        from dataclasses import replace
        from datetime import timedelta

        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        install_id = h.inspect().json()["install_id"]

        # The harness clock is fixed at inspection time, so nothing is expired
        # yet and the sweep is a no-op.
        first = h.client.post("/extensions/expired-authorizations")
        assert first.status_code == 200
        assert first.json() == {"abandoned": 0}

        # Move the record past its 15-minute window through the store the
        # served service is wired with.
        record = h.service._store._records[install_id]
        expired_record = replace(record, expires_at=record.expires_at - timedelta(hours=1))
        asyncio.run(h.service._store.save_record(expired_record))

        second = h.client.post("/extensions/expired-authorizations")
        assert second.status_code == 200
        assert second.json() == {"abandoned": 1}
        refused = h.install(install_id)
        assert refused.status_code == 409
        final = h.client.get(
            f"/extensions/installations/{install_id}",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        assert final.json()["state"] == "abandoned"

    def test_missing_service_is_503(self) -> None:
        app = FastAPI()
        app.include_router(extensions_api.router)
        client = TestClient(app)
        response = client.post(
            "/extensions/inspections",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "manifest_text": _manifest_text(),
                "payload_b64": _payload_b64(),
                "trust": {
                    "publisher_id": "acme",
                    "signature_present": True,
                    "signer_key_id": "key-1",
                },
            },
        )
        assert response.status_code == 503


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestFailClosedDefaultLoader:
    def test_unwired_default_loader_answers_409_with_failed_state(self) -> None:
        """The fail-closed default loader must fail activation closed over
        HTTP, leaving a truthful FAILED record and nothing active — the same
        wiring a Container without an activation substrate performs."""
        service = ExtensionInstallService(
            InMemoryExtensionStore(),
            loader=UnwiredExtensionLoader(),
            trust_policy=TRUST_POLICY,
            platform_api_version="1.0.0",
        )
        app = FastAPI()
        app.state.container = SimpleNamespace(ensure_extension_install_service=lambda: service)
        app.include_router(extensions_api.router)
        client = TestClient(app)
        app.dependency_overrides[verify_api_key] = lambda: _principal("operator-1")

        body = {
            "org_id": "org-1",
            "workspace_id": "",  # org-only scope: no workspace authority needed
            "manifest_text": _manifest_text(),
            "payload_b64": _payload_b64(),
            "trust": {
                "publisher_id": "acme",
                "signature_present": True,
                "signer_key_id": "key-1",
                "package_sha256": hashlib.sha256(PAYLOAD).hexdigest(),
            },
        }
        inspected = client.post("/extensions/inspections", json=body)
        assert inspected.status_code == 201, inspected.text
        install_id = inspected.json()["install_id"]

        decided = client.post(
            f"/extensions/installations/{install_id}/authorization",
            json={
                "org_id": "org-1",
                "workspace_id": "",
                "approve": True,
                "reason": "accepted for the pilot",
            },
        )
        assert decided.json()["state"] == "authorized"

        failed = client.post(
            f"/extensions/installations/{install_id}/installation",
            json={"org_id": "org-1", "workspace_id": "", "payload_b64": _payload_b64()},
        )
        assert failed.status_code == 409, failed.text
        assert failed.json()["detail"]
        active = client.get(
            "/extensions/active",
            params={"org_id": "org-1", "workspace_id": "", "extension_id": "acme.chart_tools"},
        )
        assert active.status_code == 404
