"""The truthful extension operational views over HTTP (M9-I3, #978).

These tests drive the real health service through the real router. They pin
the acceptance criteria at the API boundary: readiness is earned from
canonical evidence (never self-reported), the operator holds are durable and
distinct from health, errors carry their provenance to the operator, the
ranking views rank by measured data with absent metrics sorting last, and
the export matches the views.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.extensions.health import (
    ExtensionErrorKind,
    ExtensionErrorRecord,
    ExtensionHealthService,
    ExtensionObservation,
    InMemoryExtensionHealthStore,
    ObservationOutcome,
)
from maistro.extensions.service import ExtensionCodeLoader, ExtensionInstallService, LoadedExtension
from maistro.extensions.store import InMemoryExtensionStore
from maistro.extensions.trust import TrustPolicy
from maistro.extensions.types import ExtensionInstallRecord, ExtensionScope
from maistro.workspaces import InMemoryWorkspaceStore
from maistro_server.api import extensions as extensions_api
from maistro_server.api import workspaces as workspace_api
from maistro_server.api.auth import verify_api_key
from maistro_server.api.principal import AuthenticatedPrincipal

PAYLOAD = b"extension-health-payload"
SERVICE_CLOCK = datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC)
SCOPE = ExtensionScope(org_id="org-1", workspace_id="ws-1")


def _payload_b64(data: bytes = PAYLOAD) -> str:
    return base64.b64encode(data).decode()


def _manifest_text(
    *,
    extension_id: str = "acme.chart",
    version: str = "1.4.0",
    dependencies: list[dict[str, str]] | None = None,
) -> str:
    document: dict[str, object] = {
        "manifest_version": 1,
        "id": extension_id,
        "name": extension_id,
        "version": version,
        "publisher": "acme",
        "api_version": "1.0.0",
        "permissions": ["network.http"],
        "entry_points": [{"name": "main", "module": "mod", "attribute": "activate"}],
        "artifact": {"sha256": hashlib.sha256(PAYLOAD).hexdigest(), "size": len(PAYLOAD)},
    }
    if dependencies:
        document["dependencies"] = dependencies
    return json.dumps(document)


class RecordingLoader(ExtensionCodeLoader):
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes]] = []

    async def load(self, record: ExtensionInstallRecord, payload: bytes) -> LoadedExtension:
        self.calls.append((record.install_id, bytes(payload)))
        return LoadedExtension(extension_id=record.extension_id, version=record.version)


TRUST_POLICY = TrustPolicy(
    trusted_publishers=frozenset({"acme"}),
    require_signature=True,
    allowed_signer_keys=frozenset({"key-1"}),
)


class _Harness:
    def __init__(
        self,
        client: TestClient,
        app: FastAPI,
        install: ExtensionInstallService,
        health: ExtensionHealthService,
        health_store: InMemoryExtensionHealthStore,
        workspaces: InMemoryWorkspaceStore,
    ) -> None:
        self.client = client
        self.app = app
        self.install = install
        self.health = health
        self.health_store = health_store
        self.workspaces = workspaces

    def own_workspace(self, owner: str = "operator-1", workspace_id: str = "ws-1") -> None:
        """Make ``owner`` the workspace's canonical OWNER (ADMINISTER)."""
        asyncio.run(
            self.workspaces.create(creator_user_id=owner, name="Health", workspace_id=workspace_id)
        )

    def login(self, user_id: str = "operator-1") -> None:
        self.app.dependency_overrides[verify_api_key] = lambda: _principal(user_id)

    def install_active(self, **manifest_kwargs: object) -> str:
        """Drive one candidate to ACTIVE through the machine; its install id."""
        response = self.client.post(
            "/extensions/inspections",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "manifest_text": _manifest_text(**manifest_kwargs),  # type: ignore[arg-type]
                "payload_b64": _payload_b64(),
                "trust": {
                    "publisher_id": "acme",
                    "signature_present": True,
                    "signer_key_id": "key-1",
                    "package_sha256": hashlib.sha256(PAYLOAD).hexdigest(),
                },
            },
        )
        assert response.status_code == 201, response.text
        install_id = response.json()["install_id"]
        assert (
            self.client.post(
                f"/extensions/installations/{install_id}/authorization",
                json={
                    "org_id": "org-1",
                    "workspace_id": "ws-1",
                    "approve": True,
                    "reason": "reviewed",
                },
            ).status_code
            == 200
        )
        installed = self.client.post(
            f"/extensions/installations/{install_id}/installation",
            json={"org_id": "org-1", "workspace_id": "ws-1", "payload_b64": _payload_b64()},
        )
        assert installed.status_code == 200, installed.text
        return install_id

    def observe(
        self,
        observation_id: str,
        *,
        outcome: ObservationOutcome = ObservationOutcome.SUCCESS,
        error: ExtensionErrorRecord | None = None,
        version: str = "1.4.0",
    ) -> None:
        asyncio.run(
            self.health.record_observation(
                ExtensionObservation(
                    observation_id=observation_id,
                    at=SERVICE_CLOCK,
                    org_id="org-1",
                    workspace_id="ws-1",
                    extension_id="acme.chart",
                    version=version,
                    latency_ms=12.5,
                    outcome=outcome,
                    cost_units=0.5 if outcome is ObservationOutcome.SUCCESS else None,
                    error=error,
                )
            )
        )


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        token=f"token-{user_id}",
        roles=frozenset({"user"}),
    )


@pytest.fixture
async def harness() -> AsyncIterator[_Harness]:
    install_store = InMemoryExtensionStore()
    health_store = InMemoryExtensionHealthStore()
    install = ExtensionInstallService(
        install_store,
        loader=RecordingLoader(),
        trust_policy=TRUST_POLICY,
        platform_api_version="1.0.0",
        clock=lambda: SERVICE_CLOCK,
        authorization_ttl=timedelta(minutes=15),
    )
    health = ExtensionHealthService(install_store, health_store, platform_api_version="1.0.0")
    workspaces = InMemoryWorkspaceStore()
    app = FastAPI()
    app.state.container = SimpleNamespace(
        ensure_extension_install_service=lambda: install,
        ensure_extension_health_service=lambda: health,
    )
    app.include_router(extensions_api.router)
    workspace_api.configure_workspace_store(workspaces)
    client = TestClient(app)
    try:
        yield _Harness(client, app, install, health, health_store, workspaces)
    finally:
        client.close()
        app.dependency_overrides.clear()
        workspace_api.configure_workspace_store(None)


def _dependency_error() -> ExtensionErrorRecord:
    return ExtensionErrorRecord(
        error_id="err-provider",
        at=SERVICE_CLOCK,
        org_id="org-1",
        workspace_id="ws-1",
        extension_id="acme.chart",
        version="1.4.0",
        kind=ExtensionErrorKind.DEPENDENCY,
        code="provider_unreachable",
        message="the provider refused the connection",
        dependency="acme.provider",
        dependency_version="2.0.0",
    )


class TestUnwiredContainer:
    def test_health_views_answer_503_without_a_health_service(self) -> None:
        """A deployment whose container has no extension health wiring gets a
        truthful 503, not an improvised empty view."""
        install = ExtensionInstallService(
            InMemoryExtensionStore(),
            loader=RecordingLoader(),
            trust_policy=TRUST_POLICY,
        )
        app = FastAPI()
        app.state.container = SimpleNamespace(ensure_extension_install_service=lambda: install)
        app.include_router(extensions_api.router)
        client = TestClient(app)
        try:
            response = client.get("/extensions/health?org_id=org-1&workspace_id=ws-1")
            assert response.status_code == 503
        finally:
            client.close()
            app.dependency_overrides.clear()


class TestAuthenticationAndScope:
    def test_health_views_require_authentication(self, harness: _Harness) -> None:
        """/extensions/health is an operator surface: reads are authenticated,
        exactly like the install-lifecycle reads they extend."""
        harness.own_workspace()
        harness.login()
        harness.install_active()

        # Test settings run auth-disabled (no api_keys), which yields the dev
        # principal; pin the contract these routes sit behind by making the
        # auth dependency refuse, the way a configured deployment would.
        def _deny() -> AuthenticatedPrincipal:
            from fastapi import HTTPException
            from fastapi import status as fastapi_status

            raise HTTPException(
                status_code=fastapi_status.HTTP_401_UNAUTHORIZED,
                detail="Missing authorization header",
            )

        harness.app.dependency_overrides[verify_api_key] = _deny
        for method, url in (
            ("get", "/extensions/health?org_id=org-1&workspace_id=ws-1"),
            ("get", "/extensions/health/acme.chart?org_id=org-1&workspace_id=ws-1"),
            ("get", "/extensions/usage?org_id=org-1&workspace_id=ws-1"),
            ("get", "/extensions/telemetry/export?org_id=org-1&workspace_id=ws-1"),
            ("post", "/extensions/health/acme.chart/operator"),
        ):
            kwargs = {"json": {}} if method == "post" else {}
            response = getattr(harness.client, method)(url, **kwargs)
            assert response.status_code in (401, 403), (url, response.status_code)

    def test_operator_decision_requires_workspace_administer(self, harness: _Harness) -> None:
        """A Workspace-scoped hold requires canonical ADMINISTER membership —
        quarantine-by-non-admin is refused before any decision is recorded."""
        harness.own_workspace(owner="owner-1")
        harness.login("intruder-1")
        response = harness.client.post(
            "/extensions/health/acme.chart/operator",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "action": "quarantine",
                "reason": "not mine to decide",
            },
        )
        # 404, not 403: a non-member cannot even confirm the workspace exists
        # (the install-lifecycle routes' containment behavior).
        assert response.status_code == 404
        recorded = asyncio.run(harness.health_store.decisions(SCOPE))
        assert recorded == ()

    def test_operator_decision_requires_a_reason(self, harness: _Harness) -> None:
        """A decision without a recorded reason is not auditable evidence and
        is refused by validation."""
        harness.login()
        response = harness.client.post(
            "/extensions/health/acme.chart/operator",
            json={"org_id": "org-1", "workspace_id": "ws-1", "action": "quarantine", "reason": ""},
        )
        assert response.status_code == 422


class TestHealthViews:
    def test_active_healthy_extension_reports_ready(self, harness: _Harness) -> None:
        """The baseline view: ACTIVE + clean recorded evidence → ready."""
        harness.own_workspace()
        harness.login()
        harness.install_active()
        harness.observe("obs-1")

        response = harness.client.get("/extensions/health?org_id=org-1&workspace_id=ws-1")

        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["ready"] is True
        assert row["live"] is True
        assert row["summary"] == "ready"
        assert row["healthy"] == "healthy"
        assert row["not_ready_reasons"] == []

    def test_quarantine_through_the_api_flips_the_view(self, harness: _Harness) -> None:
        """Acceptance: a durable operator hold shows up as QUARANTINED — not
        ready, distinct from unhealthy — and the decision is on the record
        with actor and reason."""
        harness.own_workspace()
        harness.login()
        harness.install_active()
        harness.observe("obs-1")

        decision = harness.client.post(
            "/extensions/health/acme.chart/operator",
            json={
                "org_id": "org-1",
                "workspace_id": "ws-1",
                "action": "quarantine",
                "reason": "suspected misbehavior",
            },
        )
        assert decision.status_code == 200
        body = decision.json()
        assert body["action"] == "quarantine"
        assert body["state"] == "quarantined"
        assert body["actor"] == "operator-1"
        assert body["reason"] == "suspected misbehavior"

        overview = harness.client.get("/extensions/health?org_id=org-1&workspace_id=ws-1").json()
        assert overview[0]["summary"] == "quarantined"
        assert overview[0]["ready"] is False
        assert overview[0]["healthy"] == "healthy"

    def test_transient_dependency_failure_degrades_the_view(self, harness: _Harness) -> None:
        """Acceptance: a dependency-kind failure recorded by the host shows
        DEGRADED with the dependency provenance in the detail view — clearly
        distinct from the operator holds."""
        harness.own_workspace()
        harness.login()
        harness.install_active()
        harness.observe("obs-1")
        harness.observe("obs-2", outcome=ObservationOutcome.FAILURE, error=_dependency_error())

        detail = harness.client.get("/extensions/health/acme.chart?org_id=org-1&workspace_id=ws-1")

        assert detail.status_code == 200
        body = detail.json()
        assert body["status"]["summary"] == "degraded"
        assert body["status"]["healthy"] == "degraded"
        assert body["status"]["live"] is True
        assert body["status"]["ready"] is False
        kinds = [error["kind"] for error in body["recent_errors"]]
        assert kinds == ["dependency"]
        assert body["recent_errors"][0]["dependency"] == "acme.provider"
        assert body["recent_errors"][0]["version"] == "1.4.0"
        assert body["slo"]["budget_exhausted"] is True

    def test_detail_of_unknown_extension_is_404(self, harness: _Harness) -> None:
        """An extension the scope never recorded has no status; the detail
        view answers 404 rather than fabricating one."""
        harness.login()
        response = harness.client.get(
            "/extensions/health/acme.ghost?org_id=org-1&workspace_id=ws-1"
        )
        assert response.status_code == 404

    def test_detail_can_project_a_historical_version(self, harness: _Harness) -> None:
        """Acceptance: a superseded version stays identifiable — its detail
        says SUPERSEDED, never ready, while the active version stays ready.
        The detail's SLO and failures are the requested version's own
        evidence, not the active version's."""
        harness.own_workspace()
        harness.login()
        harness.install_active(version="1.4.0")
        harness.observe(
            "obs-old",
            version="1.4.0",
            outcome=ObservationOutcome.FAILURE,
            error=_dependency_error(),
        )
        harness.install_active(version="1.5.0")
        harness.observe("obs-new", version="1.5.0")

        old = harness.client.get(
            "/extensions/health/acme.chart?org_id=org-1&workspace_id=ws-1&version=1.4.0"
        ).json()
        assert old["status"]["summary"] == "superseded"
        assert old["status"]["ready"] is False
        assert old["slo"]["window_observations"] == 1
        assert old["slo"]["observed_success_rate"] == 0.0
        assert [error["version"] for error in old["recent_errors"]] == ["1.4.0"]

        current = harness.client.get(
            "/extensions/health/acme.chart?org_id=org-1&workspace_id=ws-1"
        ).json()
        assert current["status"]["version"] == "1.5.0"
        assert current["status"]["ready"] is True
        assert current["slo"]["window_observations"] == 1
        assert current["slo"]["observed_success_rate"] == 1.0
        # Without an explicit version the failures span all versions (the
        # historical default); only the requested-version view narrows them.
        assert [error["version"] for error in current["recent_errors"]] == ["1.4.0"]


class TestRankingAndExport:
    def test_usage_ranking_orders_by_cost_with_unmeasured_last(self, harness: _Harness) -> None:
        """Acceptance: ranking by cost uses measured data; the unmeasured
        extension sorts last instead of reading as free. Versions keep their
        identity with an explicit active flag."""
        harness.own_workspace()
        harness.login()
        harness.install_active(version="1.4.0")
        harness.observe("obs-cost", version="1.4.0")
        harness.install_active(extension_id="acme.free", version="1.0.0")
        # acme.free has telemetry without any recorded cost.
        asyncio.run(
            harness.health.record_observation(
                ExtensionObservation(
                    observation_id="obs-free",
                    at=SERVICE_CLOCK,
                    org_id="org-1",
                    workspace_id="ws-1",
                    extension_id="acme.free",
                    version="1.0.0",
                    latency_ms=5.0,
                    outcome=ObservationOutcome.SUCCESS,
                    cost_units=None,
                    error=None,
                )
            )
        )

        ranked = harness.client.get("/extensions/usage?org_id=org-1&workspace_id=ws-1&by=cost")

        assert ranked.status_code == 200
        rows = ranked.json()
        assert [row["extension_id"] for row in rows] == ["acme.chart", "acme.free"]
        assert rows[0]["cost_units_total"] == pytest.approx(0.5)
        assert rows[1]["cost_units_total"] is None
        assert all(row["active"] is True for row in rows)

    def test_usage_ranking_rejects_unknown_metric(self, harness: _Harness) -> None:
        """An ordering the platform does not define is a 422, not a silent
        default ordering."""
        harness.login()
        response = harness.client.get("/extensions/usage?org_id=org-1&workspace_id=ws-1&by=revenue")
        assert response.status_code == 422

    def test_export_matches_the_views(self, harness: _Harness) -> None:
        """The export carries the same objects the views serve: statuses,
        digests, errors with provenance, and the operator decisions."""
        harness.own_workspace()
        harness.login()
        harness.install_active()
        harness.observe("obs-1")
        harness.observe("obs-2", outcome=ObservationOutcome.FAILURE, error=_dependency_error())
        assert (
            harness.client.post(
                "/extensions/health/acme.chart/operator",
                json={
                    "org_id": "org-1",
                    "workspace_id": "ws-1",
                    "action": "disable",
                    "reason": "drain",
                },
            ).status_code
            == 200
        )

        exported = harness.client.get("/extensions/telemetry/export?org_id=org-1&workspace_id=ws-1")

        assert exported.status_code == 200
        body = exported.json()
        assert len(body["statuses"]) == 1
        assert body["statuses"][0]["summary"] == "disabled"
        assert len(body["usage"]) == 1
        assert body["usage"][0]["failures"] == 1
        assert body["errors"][0]["dependency"] == "acme.provider"
        assert len(body["operator_decisions"]) == 1
        assert body["operator_decisions"][0]["reason"] == "drain"
