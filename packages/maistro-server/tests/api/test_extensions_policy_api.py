"""The extension policy, audit, and tenant-state HTTP surface (#971, M9-G3).

These tests drive the real router: setting the organization layer must gate
the install lifecycle over HTTP (including the acceptance order "org deny
overrides a Workspace enable request"), workspace policy writes require
canonical Workspace ADMINISTER authority, the decision explanation is a
side-effect-free dry run, the audit trail is readable for inspection, and
tenant-scoped configuration never crosses Workspaces.
"""

from __future__ import annotations

import asyncio
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
    ExtensionPolicyEngine,
    InMemoryExtensionStore,
    TrustPolicy,
)
from maistro.extensions.service import (
    ExtensionCodeLoader,
    ExtensionInstallService,
    LoadedExtension,
)
from maistro.workspaces import InMemoryWorkspaceStore
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
            "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
            "size": len(PAYLOAD),
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


class _Harness:
    """The router over the real service + policy engine + workspace store."""

    def __init__(self, client: TestClient, service: ExtensionInstallService) -> None:
        self.client = client
        self.service = service

    def inspect(
        self,
        *,
        org_id: str = "org-1",
        workspace_id: str = "ws-a",
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
        workspace_id: str = "ws-a",
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


def _own_workspace(workspaces: InMemoryWorkspaceStore, owner: str, workspace_id: str) -> None:
    """Ensure ``owner`` holds the workspace the authority checks resolve on.

    Idempotent: the harness fixture pre-creates ws-a/ws-b owned by
    ``operator-1``, so a test that states its ownership premise explicitly
    must not fail on the already-existing row.
    """
    if asyncio.run(workspaces.get(workspace_id)) is not None:
        return
    asyncio.run(
        workspaces.create(creator_user_id=owner, name="Extensions", workspace_id=workspace_id)
    )


@pytest.fixture
async def harness() -> AsyncIterator[tuple[_Harness, InMemoryWorkspaceStore, RecordingLoader]]:
    loader = RecordingLoader()
    engine = ExtensionPolicyEngine()
    service = ExtensionInstallService(
        InMemoryExtensionStore(),
        loader=loader,
        trust_policy=TRUST_POLICY,
        platform_api_version="1.0.0",
        clock=lambda: datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC),
        authorization_ttl=timedelta(minutes=15),
        policy_engine=engine,
    )
    workspaces = InMemoryWorkspaceStore()
    await workspaces.create(creator_user_id="operator-1", name="Extensions", workspace_id="ws-a")
    await workspaces.create(creator_user_id="operator-1", name="Extensions", workspace_id="ws-b")
    app = FastAPI()
    app.state.container = SimpleNamespace(
        ensure_extension_install_service=lambda: service,
        ensure_extension_policy_engine=lambda: engine,
    )
    app.include_router(extensions_api.router)
    workspace_api.configure_workspace_store(workspaces)
    app.dependency_overrides[verify_api_key] = lambda: _principal("operator-1")
    client = TestClient(app)
    try:
        yield _Harness(client, service), workspaces, loader
    finally:
        client.close()
        app.dependency_overrides.clear()
        workspace_api.configure_workspace_store(None)


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestOrgPolicyGatesTheLifecycle:
    def test_org_deny_rejects_inspection_over_http(self, harness) -> None:
        h, _workspaces, loader = harness
        put = h.client.put(
            "/extensions/policy/orgs/org-1",
            json={
                "denied_extensions": ["acme.chart_tools"],
                "approved_publishers": ["acme"],
            },
        )
        assert put.status_code == 200, put.text
        assert put.json()["denied_extensions"] == ["acme.chart_tools"]

        inspected = h.inspect()
        assert inspected.status_code == 201, inspected.text
        assert inspected.json()["state"] == "rejected"
        assert "organization deny-list" in inspected.json()["failure_reason"]
        assert loader.calls == []

    def test_org_deny_overrides_workspace_enable_request(self, harness) -> None:
        """Inspect while allowed, then the org denies: the Workspace enable
        request is overridden at authorization, over HTTP."""
        h, _workspaces, loader = harness
        ws_policy = h.client.put(
            "/extensions/policy/orgs/org-1/workspaces/ws-a",
            json={"enabled_extensions": ["acme.chart_tools"]},
        )
        assert ws_policy.status_code == 200, ws_policy.text

        inspected = h.inspect()
        assert inspected.status_code == 201, inspected.text
        install_id = inspected.json()["install_id"]
        assert inspected.json()["state"] == "awaiting_authorization"

        denied = h.client.put(
            "/extensions/policy/orgs/org-1",
            json={"denied_extensions": ["acme.chart_tools"]},
        )
        assert denied.status_code == 200, denied.text

        decided = h.authorize(install_id, approve=True, reason="workspace requests it")
        assert decided.status_code == 200, decided.text
        body = decided.json()
        assert body["state"] == "denied"
        assert "extension policy overrides this enablement" in body["failure_reason"]
        assert loader.calls == []

    def test_pin_enforced_over_http(self, harness) -> None:
        h, _workspaces, loader = harness
        pinned = h.client.put(
            "/extensions/policy/orgs/org-1",
            json={"pins": {"acme.chart_tools": {"publisher_id": "acme", "version": "1.2.3"}}},
        )
        assert pinned.status_code == 200, pinned.text
        inspected = h.inspect(version="1.4.0")
        assert inspected.status_code == 201, inspected.text
        assert inspected.json()["state"] == "rejected"
        assert "organization pin requires version 1.2.3" in inspected.json()["failure_reason"]
        assert loader.calls == []

    def test_version_pin_pinned_ok_installs(self, harness) -> None:
        h, _workspaces, loader = harness
        h.client.put(
            "/extensions/policy/orgs/org-1",
            json={
                "pins": {"acme.chart_tools": {"publisher_id": "acme", "version": "1.4.0"}},
                "approved_publishers": ["acme"],
            },
        )
        h.client.put(
            "/extensions/policy/orgs/org-1/workspaces/ws-a",
            json={"enabled_extensions": ["acme.chart_tools"]},
        )
        inspected = h.inspect()
        assert inspected.json()["state"] == "awaiting_authorization"
        decided = h.authorize(inspected.json()["install_id"])
        assert decided.json()["state"] == "authorized"
        installed = h.client.post(
            f"/extensions/installations/{inspected.json()['install_id']}/installation",
            json={"org_id": "org-1", "workspace_id": "ws-a", "payload_b64": _payload_b64()},
        )
        assert installed.status_code == 200, installed.text
        assert installed.json()["state"] == "active"
        assert len(loader.calls) == 1

    def test_malformed_policy_body_is_422(self, harness) -> None:
        h, _workspaces, _loader = harness
        response = h.client.put(
            "/extensions/policy/orgs/org-1/workspaces/ws-a",
            json={"permission_ceilings": {"acme.chart_tools": ["NOT A TOKEN"]}},
        )
        assert response.status_code == 422, response.text


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestPolicyInspectionAndAudit:
    def test_org_inspection_reports_layer_and_inheritance(self, harness) -> None:
        h, _workspaces, _loader = harness
        h.client.put(
            "/extensions/policy/orgs/org-1",
            json={"allowed_extensions": ["acme.chart_tools"]},
        )
        view = h.client.get("/extensions/policy/orgs/org-1")
        assert view.status_code == 200, view.text
        body = view.json()
        assert body["org"]["allowed_extensions"] == ["acme.chart_tools"]
        assert body["org"]["org_id"] == "org-1"
        assert body["workspace"] is None
        assert len(body["inheritance"]) == 7
        assert any("deny-list" in rule for rule in body["inheritance"])

    def test_unconfigured_org_inspection_is_an_explained_empty_layer(self, harness) -> None:
        h, _workspaces, _loader = harness
        view = h.client.get("/extensions/policy/orgs/org-unknown")
        assert view.status_code == 200
        assert view.json()["org"] is None
        assert len(view.json()["inheritance"]) == 7

    def test_workspace_inspection_requires_workspace_authority(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-a")
        # operator-1 owns ws-a: inspection works and shows both layers.
        h.client.put(
            "/extensions/policy/orgs/org-1/workspaces/ws-a",
            json={"enabled_extensions": ["acme.chart_tools"]},
        )
        view = h.client.get("/extensions/policy/orgs/org-1/workspaces/ws-a")
        assert view.status_code == 200, view.text
        assert view.json()["workspace"]["enabled_extensions"] == ["acme.chart_tools"]
        assert view.json()["org"] is None

        # A workspace operator-1 has no membership in: not found, no leak.
        foreign = h.client.get("/extensions/policy/orgs/org-1/workspaces/ws-stranger")
        assert foreign.status_code == 404

    def test_workspace_policy_write_requires_workspace_authority(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-a")
        foreign = h.client.put(
            "/extensions/policy/orgs/org-1/workspaces/ws-stranger",
            json={"enabled_extensions": ["acme.chart_tools"]},
        )
        assert foreign.status_code == 404

    def test_explain_is_a_dry_run_with_full_trace_and_no_audit_row(self, harness) -> None:
        h, _workspaces, _loader = harness
        h.client.put(
            "/extensions/policy/orgs/org-1",
            json={"denied_extensions": ["acme.chart_tools"]},
        )
        h.client.put(
            "/extensions/policy/orgs/org-1/workspaces/ws-a",
            json={"enabled_extensions": ["acme.chart_tools"]},
        )
        before = h.client.get("/extensions/policy/orgs/org-1/audit").json()
        explained = h.client.post(
            "/extensions/policy/orgs/org-1/workspaces/ws-a/decisions",
            json={
                "extension_id": "acme.chart_tools",
                "version": "1.4.0",
                "publisher": "acme",
                "permissions": ["network.http"],
            },
        )
        assert explained.status_code == 200, explained.text
        body = explained.json()
        assert body["verdict"] == "deny"
        assert body["allowed"] is False
        assert "organization deny-list" in body["explanation"]
        rules = [outcome["rule"] for outcome in body["trace"]]
        assert rules[0] == "org.deny-list"
        assert "workspace.skipped" in rules
        # The dry run wrote nothing: the audit trail gained no decision row.
        after = h.client.get("/extensions/policy/orgs/org-1/audit").json()
        assert len(after) == len(before)

    def test_audit_trails_policy_changes_and_decisions(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-a")
        h.client.put("/extensions/policy/orgs/org-1", json={"approved_publishers": ["acme"]})
        inspected = h.inspect()
        h.authorize(inspected.json()["install_id"])
        audit = h.client.get("/extensions/policy/orgs/org-1/audit")
        assert audit.status_code == 200, audit.text
        kinds = [event["kind"] for event in audit.json()]
        # This test sets only the org layer; the policy change and BOTH
        # enforcement decisions it gated (inspection, authorization) are on
        # the trail — every evaluation is evidence.
        assert kinds == ["org-policy-set", "decision", "decision"]
        decision = audit.json()[-1]
        assert decision["actor"] == "operator-1"
        assert "acme.chart_tools@1.4.0: allow" in decision["detail"]

    def test_audit_filters_by_workspace(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-a")
        h.client.put("/extensions/policy/orgs/org-1", json={})
        h.client.put(
            "/extensions/policy/orgs/org-1/workspaces/ws-a",
            json={"enabled_extensions": []},
        )
        ws_only = h.client.get(
            "/extensions/policy/orgs/org-1/audit", params={"workspace_id": "ws-a"}
        )
        assert [event["kind"] for event in ws_only.json()] == ["workspace-policy-set"]


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestTenantScopedConfigurationSurface:
    def _activate(self, h: _Harness, *, workspace_id: str = "ws-a") -> None:
        inspected = h.inspect(workspace_id=workspace_id)
        assert inspected.json()["state"] == "awaiting_authorization", inspected.text
        decided = h.authorize(inspected.json()["install_id"], workspace_id=workspace_id)
        assert decided.json()["state"] == "authorized", decided.text
        installed = h.client.post(
            f"/extensions/installations/{inspected.json()['install_id']}/installation",
            json={
                "org_id": "org-1",
                "workspace_id": workspace_id,
                "payload_b64": _payload_b64(),
            },
        )
        assert installed.json()["state"] == "active", installed.text

    def test_config_round_trip_in_one_workspace(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-a")
        self._activate(h)
        put = h.client.put(
            "/extensions/state",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-a",
                "extension_id": "acme.chart_tools",
                "key": "api_key",
                "value": "secret-1",
            },
        )
        assert put.status_code == 200, put.text
        got = h.client.get(
            "/extensions/state",
            params={
                "org_id": "org-1",
                "workspace_id": "ws-a",
                "extension_id": "acme.chart_tools",
                "key": "api_key",
            },
        )
        assert got.status_code == 200, got.text
        assert got.json()["value"] == "secret-1"

    def test_other_workspace_observes_404_never_the_value(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-a")
        _own_workspace(workspaces, "operator-1", "ws-b")
        self._activate(h, workspace_id="ws-a")
        h.client.put(
            "/extensions/state",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-a",
                "extension_id": "acme.chart_tools",
                "key": "api_key",
                "value": "secret-1",
            },
        )
        # ws-b has no active install: binding is refused with the scope-blind
        # 404, before any key lookup could leak existence.
        foreign = h.client.get(
            "/extensions/state",
            params={
                "org_id": "org-1",
                "workspace_id": "ws-b",
                "extension_id": "acme.chart_tools",
                "key": "api_key",
            },
        )
        assert foreign.status_code == 404
        # And a same-key write in ws-b stores under ws-b's tenant key only.
        inspected = h.inspect(workspace_id="ws-b")
        h.authorize(inspected.json()["install_id"], workspace_id="ws-b")
        h.client.post(
            f"/extensions/installations/{inspected.json()['install_id']}/installation",
            json={"org_id": "org-1", "workspace_id": "ws-b", "payload_b64": _payload_b64()},
        )
        own_b = h.client.get(
            "/extensions/state",
            params={
                "org_id": "org-1",
                "workspace_id": "ws-b",
                "extension_id": "acme.chart_tools",
                "key": "api_key",
            },
        )
        assert own_b.status_code == 404

    def test_state_write_requires_workspace_authority(self, harness) -> None:
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-a")
        self._activate(h)
        foreign = h.client.put(
            "/extensions/state",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-stranger",
                "extension_id": "acme.chart_tools",
                "key": "api_key",
                "value": "x",
            },
        )
        assert foreign.status_code == 404

    def test_policy_refused_activation_maps_to_403_with_record_unchanged(self, harness) -> None:
        """A pin landing between authorization and activation refuses the
        install route with 403 — and the operator's approval stands: the
        record keeps its AUTHORIZED state, nothing was activated."""
        h, _workspaces, loader = harness
        inspected = h.inspect()
        install_id = inspected.json()["install_id"]
        assert inspected.json()["state"] == "awaiting_authorization"
        decided = h.authorize(install_id)
        assert decided.json()["state"] == "authorized"

        pinned = h.client.put(
            "/extensions/policy/orgs/org-1",
            json={"pins": {"acme.chart_tools": {"publisher_id": "acme", "version": "1.2.3"}}},
        )
        assert pinned.status_code == 200, pinned.text

        installed = h.client.post(
            f"/extensions/installations/{install_id}/installation",
            json={"org_id": "org-1", "workspace_id": "ws-a", "payload_b64": _payload_b64()},
        )
        assert installed.status_code == 403, installed.text
        assert "organization pin requires version 1.2.3" in installed.text
        assert loader.calls == []
        record = h.client.get(
            f"/extensions/installations/{install_id}",
            params={"org_id": "org-1", "workspace_id": "ws-a"},
        )
        assert record.json()["state"] == "authorized", record.text

    def test_state_read_requires_workspace_authority(self, harness) -> None:
        """The acceptance boundary: the extension is ACTIVE in ws-a with a
        config value set, and a principal who is a member of neither ws-a nor
        any workspace cannot read the value by naming the scope — the
        scope-blind 404, not the secret (#971: observation is tenant-scoped
        at the API, not just the store)."""
        h, workspaces, _loader = harness
        _own_workspace(workspaces, "operator-1", "ws-a")
        self._activate(h)
        put = h.client.put(
            "/extensions/state",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-a",
                "extension_id": "acme.chart_tools",
                "key": "api_key",
                "value": "secret-1",
            },
        )
        assert put.status_code == 200, put.text
        params = {
            "org_id": "org-1",
            "workspace_id": "ws-a",
            "extension_id": "acme.chart_tools",
            "key": "api_key",
        }
        # The owner reads the value back.
        own = h.client.get("/extensions/state", params=params)
        assert own.status_code == 200, own.text
        assert own.json()["value"] == "secret-1"

        # A non-member principal gets the scope-blind 404 — never the value.
        app = h.client.app
        original = app.dependency_overrides[verify_api_key]
        app.dependency_overrides[verify_api_key] = lambda: _principal("stranger-1")
        try:
            foreign = h.client.get("/extensions/state", params=params)
        finally:
            app.dependency_overrides[verify_api_key] = original
        assert foreign.status_code == 404
        assert "secret-1" not in foreign.text


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
class TestPolicyRoutesAreAuthenticated:
    """Every new route is authenticated, reads included — the same contract
    the install-lifecycle routes state and the 401 regressions pin."""

    _AUTH: ClassVar[dict[str, str]] = {"Authorization": "Bearer s3cret"}

    @staticmethod
    def _client() -> TestClient:
        engine = ExtensionPolicyEngine()
        service = ExtensionInstallService(
            InMemoryExtensionStore(),
            loader=RecordingLoader(),
            trust_policy=TRUST_POLICY,
            platform_api_version="1.0.0",
            policy_engine=engine,
        )
        app = FastAPI()
        app.state.container = SimpleNamespace(
            ensure_extension_install_service=lambda: service,
            ensure_extension_policy_engine=lambda: engine,
        )
        app.include_router(extensions_api.router)
        app.dependency_overrides[get_settings] = lambda: Settings(api_keys=["ops:s3cret"])
        return TestClient(app)

    def test_policy_reads_and_writes_reject_missing_credentials(self) -> None:
        client = self._client()
        probes = [
            ("get", "/extensions/policy/orgs/org-1", None),
            ("put", "/extensions/policy/orgs/org-1", {"denied_extensions": []}),
            (
                "put",
                "/extensions/policy/orgs/org-1/workspaces/ws-a",
                {"enabled_extensions": []},
            ),
            ("get", "/extensions/policy/orgs/org-1/workspaces/ws-a", None),
            ("get", "/extensions/policy/orgs/org-1/audit", None),
            (
                "post",
                "/extensions/policy/orgs/org-1/workspaces/ws-a/decisions",
                {
                    "extension_id": "acme.chart_tools",
                    "version": "1.4.0",
                    "publisher": "acme",
                },
            ),
            ("get", "/extensions/state", None),
            (
                "put",
                "/extensions/state",
                {
                    "org_id": "org-1",
                    "workspace_id": "ws-a",
                    "extension_id": "e",
                    "key": "k",
                    "value": "v",
                },
            ),
        ]
        for method, path, body in probes:
            response = client.request(method, path, json=body)
            assert response.status_code == 401, (path, response.status_code, response.text)

    def test_policy_routes_accept_valid_credentials(self) -> None:
        client = self._client()
        assert client.get("/extensions/policy/orgs/org-1", headers=self._AUTH).status_code == 200
        assert (
            client.get("/extensions/policy/orgs/org-1/audit", headers=self._AUTH).status_code == 200
        )
        put = client.put(
            "/extensions/policy/orgs/org-1",
            headers=self._AUTH,
            json={"approved_publishers": ["acme"]},
        )
        assert put.status_code == 200, put.text
        assert put.json()["approved_publishers"] == ["acme"]

    def test_policy_engine_dependency_503s_without_a_container(self) -> None:
        """The dependency fails closed when no host wired a container at all:
        503, not an AttributeError."""
        app = FastAPI()
        app.include_router(extensions_api.router)
        app.dependency_overrides[verify_api_key] = lambda: _principal("operator-1")
        client = TestClient(app)
        try:
            response = client.get("/extensions/policy/orgs/org-1")
        finally:
            client.close()
            app.dependency_overrides.clear()
        assert response.status_code == 503
        assert "No extension policy engine is configured" in response.text
