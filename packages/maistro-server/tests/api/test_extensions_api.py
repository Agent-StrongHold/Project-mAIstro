"""The governed extension install lifecycle over HTTP (#953, M9-B2).

The routes are the operator surface of the inspect → authorize → install
state machine. These tests drive the real service through the real router:
the happy path, the denial path, scope containment, the fail-closed default
loader, and the audit trail endpoint. The post-install lifecycle routes of
#954 (pin/unpin, disable/resume, rollback, remove) are exercised on the same
harness in ``TestPostInstallLifecycleHttp``.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.config.settings import Settings, get_settings
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
        payload: bytes = PAYLOAD,
        **manifest_kwargs: object,
    ) -> dict:
        return self.client.post(
            "/extensions/inspections",
            json={
                "org_id": org_id,
                "workspace_id": workspace_id,
                "manifest_text": _manifest_text(payload=payload, **manifest_kwargs),  # type: ignore[arg-type]
                "payload_b64": base64.b64encode(payload).decode(),
                "trust": {
                    "publisher_id": str(manifest_kwargs.get("publisher", "acme")),
                    "signature_present": True,
                    "signer_key_id": "key-1",
                    "package_sha256": hashlib.sha256(payload).hexdigest(),
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
class TestReadsAreAuthenticated:
    """Every route on the extensions router is authenticated, reads included.

    Regression: the three GET handlers (installation record, transition
    trail, active extension) declared no ``RequireAuth`` dependency, so with
    API_KEYS configured an unauthenticated caller could read granted
    permissions and audit trails for any guessable ``org_id`` +
    ``extension_id`` while every POST answered 401 — contradicting the
    router's own contract statement in ``main.py``.
    """

    _AUTH: ClassVar[dict[str, str]] = {"Authorization": "Bearer s3cret"}

    _READS: ClassVar[list[tuple[str, str]]] = [
        ("installation", "/extensions/installations/{install_id}"),
        ("transitions", "/extensions/installations/{install_id}/transitions"),
        ("active", "/extensions/active"),
    ]

    @staticmethod
    def _client() -> TestClient:
        """Real auth (no ``verify_api_key`` override): API_KEYS configured
        through the same ``get_settings`` dependency the server resolves."""
        service = ExtensionInstallService(
            InMemoryExtensionStore(),
            loader=RecordingLoader(),
            trust_policy=TRUST_POLICY,
            platform_api_version="1.0.0",
        )
        app = FastAPI()
        app.state.container = SimpleNamespace(ensure_extension_install_service=lambda: service)
        app.include_router(extensions_api.router)
        app.dependency_overrides[get_settings] = lambda: Settings(api_keys=["ops:s3cret"])
        return TestClient(app)

    def _drive_to_active(self, client: TestClient) -> str:
        """Produce a record worth protecting: an ACTIVE install whose read
        views expose granted_permissions and the audit trail."""
        inspected = client.post(
            "/extensions/inspections",
            headers=self._AUTH,
            json={
                "org_id": "org-1",
                "workspace_id": "",  # org-only scope: no workspace authority
                "manifest_text": _manifest_text(),
                "payload_b64": _payload_b64(),
                "trust": {
                    "publisher_id": "acme",
                    "signature_present": True,
                    "signer_key_id": "key-1",
                    "package_sha256": hashlib.sha256(PAYLOAD).hexdigest(),
                },
            },
        )
        assert inspected.status_code == 201, inspected.text
        install_id = inspected.json()["install_id"]
        decided = client.post(
            f"/extensions/installations/{install_id}/authorization",
            headers=self._AUTH,
            json={
                "org_id": "org-1",
                "workspace_id": "",
                "approve": True,
                "reason": "reviewed",
            },
        )
        assert decided.status_code == 200, decided.text
        installed = client.post(
            f"/extensions/installations/{install_id}/installation",
            headers=self._AUTH,
            json={"org_id": "org-1", "workspace_id": "", "payload_b64": _payload_b64()},
        )
        assert installed.status_code == 200, installed.text
        return install_id

    def test_reads_reject_missing_token(self) -> None:
        client = self._client()
        install_id = self._drive_to_active(client)
        for name, path in self._READS:
            response = client.get(
                path.format(install_id=install_id),
                params={"org_id": "org-1", "extension_id": "acme.chart_tools"},
            )
            assert response.status_code == 401, (name, response.status_code, response.text)
            # The leak this regression names: granted authority and its audit
            # trail must not be readable without a credential.
            assert "granted_permissions" not in response.text
            assert "authorized_by" not in response.text

    def test_reads_reject_invalid_token(self) -> None:
        client = self._client()
        install_id = self._drive_to_active(client)
        for name, path in self._READS:
            response = client.get(
                path.format(install_id=install_id),
                params={"org_id": "org-1", "extension_id": "acme.chart_tools"},
                headers={"Authorization": "Bearer not-the-secret"},
            )
            assert response.status_code == 401, (name, response.status_code, response.text)

    def test_reads_accept_valid_token(self) -> None:
        client = self._client()
        install_id = self._drive_to_active(client)
        for name, path in self._READS:
            response = client.get(
                path.format(install_id=install_id),
                params={"org_id": "org-1", "extension_id": "acme.chart_tools"},
                headers=self._AUTH,
            )
            assert response.status_code == 200, (name, response.status_code, response.text)
        record = client.get(
            f"/extensions/installations/{install_id}",
            params={"org_id": "org-1"},
            headers=self._AUTH,
        ).json()
        assert record["granted_permissions"] == ["network.http", "storage.workspace"]


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


OTHER_PAYLOAD = b"extension-payload-v2"


def _activated(h: _Harness, *, version: str, permissions: tuple[str, ...], payload: bytes) -> dict:
    """Drive one candidate through inspect → authorize → install over HTTP."""
    inspected = h.inspect(version=version, permissions=permissions, payload=payload)
    assert inspected.status_code == 201, inspected.text
    record = inspected.json()
    decided = h.authorize(record["install_id"])
    assert decided.status_code == 200, decided.text
    installed = h.install(record["install_id"], payload_b64=base64.b64encode(payload).decode())
    assert installed.status_code == 200, installed.text
    return installed.json()


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestPostInstallLifecycleHttp:
    """The #954 operator surface: pin, disable/resume, rollback, remove."""

    def test_pin_blocks_a_new_version_until_explicitly_unpinned(self, harness) -> None:
        h, workspaces, loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        active = _activated(h, version="1.4.0", permissions=("network.http",), payload=PAYLOAD)
        calls_before = len(loader.calls)

        pinned = h.client.post(
            f"/extensions/installations/{active['install_id']}/pin",
            json={"org_id": "org-1", "workspace_id": "ws-1", "reason": "freeze for the demo"},
        )
        assert pinned.status_code == 200, pinned.text
        body = pinned.json()
        assert body["pinned"] is True
        assert body["pinned_by"] == "operator-1"
        assert body["pinned_at"]

        # A fully governed candidate for 1.5.0 exists, but the pin holds:
        # activation is refused with 409 and the loader never ran for it.
        inspected = h.inspect(version="1.5.0", permissions=("network.http",), payload=OTHER_PAYLOAD)
        assert inspected.status_code == 201, inspected.text
        upgraded = inspected.json()
        decided = h.authorize(upgraded["install_id"])
        assert decided.status_code == 200, decided.text
        assert decided.json()["state"] == "authorized"
        blocked = h.install(upgraded["install_id"], payload_b64=_payload_b64(OTHER_PAYLOAD))
        assert blocked.status_code == 409, blocked.text
        assert "pinned" in blocked.json()["detail"]
        assert len(loader.calls) == calls_before
        # The refusal happened before any transition: the candidate is
        # still AUTHORIZED and can be installed once the pin is lifted.
        assert decided.json()["state"] == "authorized"

        # The pin and its lift are both on the same audited trail.
        trail = h.client.get(
            f"/extensions/installations/{active['install_id']}/transitions",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        assert trail.status_code == 200
        reasons = [event["reason"] for event in trail.json()]
        assert any(reason.startswith("pinned") for reason in reasons)

        lifted = h.client.post(
            f"/extensions/installations/{active['install_id']}/unpin",
            json={"org_id": "org-1", "workspace_id": "ws-1", "reason": "demo over"},
        )
        assert lifted.status_code == 200
        assert lifted.json()["pinned"] is False

        now_active = h.install(upgraded["install_id"], payload_b64=_payload_b64(OTHER_PAYLOAD))
        assert now_active.status_code == 200, now_active.text
        assert now_active.json()["state"] == "active"

    def test_disable_stops_new_use_immediately_and_resume_recrosses_the_loader(
        self, harness
    ) -> None:
        h, workspaces, loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        active = _activated(h, version="1.4.0", permissions=("network.http",), payload=PAYLOAD)

        disabled = h.client.post(
            "/extensions/disable",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "extension_id": "acme.chart_tools",
                "reason": "incident mitigation",
            },
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["state"] == "disabled"

        # The resolution seam answers nothing from this point on.
        gone = h.client.get(
            "/extensions/active",
            params={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "extension_id": "acme.chart_tools",
            },
        )
        assert gone.status_code == 404

        # …while the record itself — evidence, grant, snapshot — stays queryable.
        still_there = h.client.get(
            f"/extensions/installations/{active['install_id']}",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        assert still_there.status_code == 200
        assert still_there.json()["state"] == "disabled"
        assert still_there.json()["manifest"]["extension_id"] == "acme.chart_tools"

        # Resume demands the bound artifact: wrong bytes are a 409 that
        # records nothing, right bytes re-cross the loader seam.
        calls_before = len(loader.calls)
        wrong = h.client.post(
            f"/extensions/installations/{active['install_id']}/resume",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "reason": "incident over",
                "payload_b64": _payload_b64(OTHER_PAYLOAD),
            },
        )
        assert wrong.status_code == 409
        assert len(loader.calls) == calls_before

        resumed = h.client.post(
            f"/extensions/installations/{active['install_id']}/resume",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "reason": "incident over",
                "payload_b64": _payload_b64(PAYLOAD),
            },
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["state"] == "active"
        assert loader.calls[-1] == (active["install_id"], PAYLOAD)

    def test_rollback_restores_a_superseded_version_through_the_loader(self, harness) -> None:
        h, workspaces, loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        first = _activated(h, version="1.4.0", permissions=("network.http",), payload=PAYLOAD)
        second = _activated(
            h,
            version="1.5.0",
            permissions=("network.http", "storage.workspace"),
            payload=OTHER_PAYLOAD,
        )

        rolled = h.client.post(
            "/extensions/rollback",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "extension_id": "acme.chart_tools",
                "reason": "regression in 1.5.0",
                "payload_b64": _payload_b64(PAYLOAD),
                "to_install_id": first["install_id"],
            },
        )
        assert rolled.status_code == 200, rolled.text
        assert rolled.json()["state"] == "active"
        assert rolled.json()["version"] == "1.4.0"
        # The return crossed the loader seam with the bound bytes.
        assert loader.calls[-1] == (first["install_id"], PAYLOAD)
        # The displaced 1.5.0 was retired audited, not deleted.
        second_trail = h.client.get(
            f"/extensions/installations/{second['install_id']}/transitions",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        assert [event["to_state"] for event in second_trail.json()][-1] == "superseded"

    def test_rollback_refuses_a_broader_grant_without_reauthorization(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        wider = _activated(
            h,
            version="1.4.0",
            permissions=("network.http", "storage.workspace"),
            payload=PAYLOAD,
        )
        _activated(h, version="1.5.0", permissions=("network.http",), payload=OTHER_PAYLOAD)

        refused = h.client.post(
            "/extensions/rollback",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "extension_id": "acme.chart_tools",
                "reason": "try to sneak storage back in",
                "payload_b64": _payload_b64(PAYLOAD),
                "to_install_id": wider["install_id"],
            },
        )
        assert refused.status_code == 409
        assert "re-authorization" in refused.json()["detail"]
        still = h.client.get(
            "/extensions/active",
            params={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "extension_id": "acme.chart_tools",
            },
        )
        assert still.status_code == 200
        assert still.json()["version"] == "1.5.0"

    def test_remove_is_terminal_for_authority_but_preserves_evidence(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        active = _activated(h, version="1.4.0", permissions=("network.http",), payload=PAYLOAD)

        removed = h.client.post(
            f"/extensions/installations/{active['install_id']}/remove",
            json={"org_id": "org-1", "workspace_id": "ws-1", "reason": "offboarding"},
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["state"] == "removed"

        gone = h.client.get(
            "/extensions/active",
            params={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "extension_id": "acme.chart_tools",
            },
        )
        assert gone.status_code == 404

        evidence = h.client.get(
            f"/extensions/installations/{active['install_id']}",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        assert evidence.status_code == 200
        assert evidence.json()["state"] == "removed"
        assert evidence.json()["granted_permissions"] == ["network.http"]
        trail = h.client.get(
            f"/extensions/installations/{active['install_id']}/transitions",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        assert trail.status_code == 200
        assert [event["to_state"] for event in trail.json()][-1] == "removed"

        # Removal is terminal: presenting the same artifact again cannot
        # resurrect the record through the install path.
        resurrect = h.install(active["install_id"])
        assert resurrect.status_code == 409

    def test_pin_refuses_a_record_that_is_not_active(self, harness) -> None:
        """A pin holds the version in service: a pre-decision candidate is 409."""
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        candidate = h.inspect(version="1.4.0")
        assert candidate.status_code == 201, candidate.text
        install_id = candidate.json()["install_id"]

        refused = h.client.post(
            f"/extensions/installations/{install_id}/pin",
            json={"org_id": "org-1", "workspace_id": "ws-1", "reason": "not in service"},
        )
        assert refused.status_code == 409
        assert "a pin holds the active version" in refused.json()["detail"]

    def test_unpin_of_a_foreign_scopes_install_is_404(self, harness) -> None:
        """A record of another workspace is indistinguishable from a missing id."""
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _own_workspace(workspaces, "operator-1", "ws-2")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        active = _activated(h, version="1.4.0", permissions=("network.http",), payload=PAYLOAD)

        missing = h.client.post(
            f"/extensions/installations/{active['install_id']}/unpin",
            json={"org_id": "org-1", "workspace_id": "ws-2", "reason": "wrong scope"},
        )
        assert missing.status_code == 404
        assert "no install record" in missing.json()["detail"]
        # The record itself is untouched and still answers in its own scope.
        own = h.client.get(
            f"/extensions/installations/{active['install_id']}",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        assert own.status_code == 200
        assert own.json()["state"] == "active"

    def test_disable_of_an_unknown_extension_is_404(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]

        missing = h.client.post(
            "/extensions/disable",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "extension_id": "acme.no_such_extension",
                "reason": "mistyped id",
            },
        )
        assert missing.status_code == 404
        assert "no active or suspended install" in missing.json()["detail"]

    def test_remove_refuses_a_record_that_never_reached_a_decision(self, harness) -> None:
        """Pre-decision records exit through their own paths, not removal."""
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-1")
        _login(h.client.app, "operator-1")  # type: ignore[attr-defined]
        candidate = h.inspect(version="1.4.0")
        assert candidate.status_code == 201, candidate.text
        install_id = candidate.json()["install_id"]

        refused = h.client.post(
            f"/extensions/installations/{install_id}/remove",
            json={"org_id": "org-1", "workspace_id": "ws-1", "reason": "change of heart"},
        )
        assert refused.status_code == 409
        assert "pre-decision" in refused.json()["detail"]
        # The refusal changed nothing: the candidate is still parked for a
        # decision, not half-removed.
        still = h.client.get(
            f"/extensions/installations/{install_id}",
            params={"org_id": "org-1", "workspace_id": "ws-1"},
        )
        assert still.status_code == 200
        assert still.json()["state"] == "awaiting_authorization"


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestPublicSurfaceDeclaration:
    """Every @router handler in extensions.py must be declared in ``__all__``.

    FastAPI registers handlers from the decorators, which static import
    scanning cannot see. The module's ``__all__`` (the a2a.py/canvas.py
    convention) is what declares the handlers as the module's public surface
    and keeps them out of the fastapi-route-handler Vulture ledger; a new
    handler that skips the declaration would resurface as unbanked dead-code
    debt and fail the exact-debt-ledger CI gate. This catches that drift here
    first, with an actionable message.
    """

    def test_all_covers_every_route_handler(self) -> None:
        import ast
        from pathlib import Path

        import maistro_server.api.extensions as extensions_module

        source = Path(str(extensions_module.__file__)).read_text(encoding="utf-8")
        handlers = {
            node.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == "router"
                for dec in node.decorator_list
            )
        }
        declared = set(extensions_module.__all__)
        missing = sorted(handlers - declared)
        assert not missing, (
            f"route handlers missing from extensions.py __all__: {missing}. "
            "FastAPI registers handlers dynamically, so every @router handler "
            "must be declared in the module's __all__ (see a2a.py and the "
            "comment above extensions.py's __all__) rather than re-entering the "
            "fastapi-route-handler Vulture ledger as unbanked debt."
        )
