"""Tests for /v2/canvas routes (SPEC-070226-8239 Phase 1, ADR-045/ADR-076).

Evidence: the routes proxy an injected CanvasStore (app.state.canvas_store),
soft-delete via archived_at, negotiate application/vnd.canvas+json;version=2,
and use the same bearer auth dependency as every other route.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.capabilities.invocation import InMemoryInvocationStore
from maistro.config.settings import Settings, get_settings
from maistro.events.envelope import InMemoryEventStore
from maistro_server.api.canvas import router as canvas_router

# ── Fakes ─────────────────────────────────────────────────────────────


class FakeDesign:
    """Structural stand-in for maistro_canvas.types.CanvasRecord."""

    def __init__(self, *, name: str, width: int, height: int, background_color: str, org_id: str):
        self.id = uuid.uuid4().hex
        self.name = name
        self.width = width
        self.height = height
        self.background_color = background_color
        self.org_id = org_id
        self.archived_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "background_color": self.background_color,
            "org_id": self.org_id,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
        }


class FakeCanvasStore:
    """In-memory subset of the CanvasStore protocol used by the routes."""

    def __init__(self) -> None:
        self.canvases: dict[str, FakeDesign] = {}

    async def create_canvas(
        self,
        *,
        name: str,
        width: int,
        height: int,
        background_color: str = "#FFFFFF",
        org_id: str = "",
    ) -> FakeDesign:
        record = FakeDesign(
            name=name,
            width=width,
            height=height,
            background_color=background_color,
            org_id=org_id,
        )
        self.canvases[record.id] = record
        return record

    async def get_canvas(self, canvas_id: str) -> FakeDesign | None:
        return self.canvases.get(canvas_id)

    async def list_canvases(
        self, org_id: str, *, include_archived: bool = False
    ) -> list[FakeDesign]:
        return [
            c
            for c in self.canvases.values()
            if c.org_id == org_id and (include_archived or c.archived_at is None)
        ]

    async def update_canvas(self, canvas: FakeDesign) -> FakeDesign:
        self.canvases[canvas.id] = canvas
        return canvas

    async def list_layers(self, canvas_id: str) -> list[Any]:
        return []

    async def latest_composite(self, canvas_id: str) -> Any:
        return None


# ── App fixture ───────────────────────────────────────────────────────


def _make_app(store: FakeCanvasStore, api_keys: list[str] | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(canvas_router)
    app.state.canvas_store = store
    settings = Settings(api_keys=api_keys or [])
    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.fixture()
def store() -> FakeCanvasStore:
    return FakeCanvasStore()


@pytest.fixture()
def client(store: FakeCanvasStore) -> TestClient:
    return TestClient(_make_app(store))


def _create(client: TestClient, name: str = "Book cover") -> dict[str, Any]:
    resp = client.post(
        "/v2/canvas/designs",
        json={"name": name, "width": 800, "height": 600},
    )
    assert resp.status_code == 201
    return dict(resp.json())


# ── CRUD ──────────────────────────────────────────────────────────────


class TestDesignCrud:
    def test_create_returns_full_record(self, client: TestClient) -> None:
        body = _create(client)
        assert body["name"] == "Book cover"
        assert body["width"] == 800
        assert body["height"] == 600
        assert body["org_id"] == "dev"  # auth disabled -> dev principal
        assert body["archived_at"] is None

    def test_create_invalid_dimensions_422(self, client: TestClient) -> None:
        resp = client.post("/v2/canvas/designs", json={"name": "x", "width": 0, "height": 10})
        assert resp.status_code == 422

    def test_list_designs(self, client: TestClient) -> None:
        _create(client, "a")
        _create(client, "b")
        resp = client.get("/v2/canvas/designs")
        assert resp.status_code == 200
        assert {d["name"] for d in resp.json()} == {"a", "b"}

    def test_get_design_includes_layers(self, client: TestClient) -> None:
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == created["id"]
        assert body["layers"] == []

    def test_get_missing_404(self, client: TestClient) -> None:
        assert client.get("/v2/canvas/designs/nope").status_code == 404

    def test_update_partial_semantics(self, client: TestClient) -> None:
        created = _create(client)
        resp = client.put(
            f"/v2/canvas/designs/{created['id']}",
            json={"name": "renamed"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "renamed"
        # omitted field unchanged
        assert body["background_color"] == created["background_color"]

    def test_store_missing_503(self) -> None:
        app = FastAPI()
        app.include_router(canvas_router)
        app.dependency_overrides[get_settings] = lambda: Settings(api_keys=[])
        client = TestClient(app)
        assert client.get("/v2/canvas/designs").status_code == 503


class TestSoftDelete:
    def test_delete_then_get_404(self, client: TestClient, store: FakeCanvasStore) -> None:
        created = _create(client)
        resp = client.delete(f"/v2/canvas/designs/{created['id']}")
        assert resp.status_code == 200
        assert resp.json() == {"deleted": True, "id": created["id"]}
        # soft delete: record still exists in the store, marked archived
        assert store.canvases[created["id"]].archived_at is not None
        assert client.get(f"/v2/canvas/designs/{created['id']}").status_code == 404
        # and it disappears from listings
        assert created["id"] not in {d["id"] for d in client.get("/v2/canvas/designs").json()}

    def test_delete_twice_404(self, client: TestClient) -> None:
        created = _create(client)
        client.delete(f"/v2/canvas/designs/{created['id']}")
        assert client.delete(f"/v2/canvas/designs/{created['id']}").status_code == 404


# ── Governed publish/export stack (M3-B4 #94) ───────────────────────


class StubCompositor:
    """Compositor/encode double for governed export tests."""

    def __init__(self, png: bytes = b"\x89PNGfake") -> None:
        self.png = png
        self.composite_calls = 0

    async def composite(self, canvas: Any, layers: list[Any]) -> Any:
        self.composite_calls += 1
        return SimpleNamespace(image_bytes=self.png)

    async def encode(self, image_bytes: bytes, *, fmt: str = "png", quality: int = 90) -> bytes:
        return b"encoded<" + fmt.encode() + b">" + image_bytes[:4]


def _governed_app(
    store: FakeCanvasStore,
    *,
    compositor: StubCompositor | None = None,
    policy=None,
    events: list[tuple[str, dict[str, Any]]] | None = None,
    api_keys: list[str] | None = None,
) -> FastAPI:
    """Build the /v2 canvas app with a real governed export stack wired.

    Uses the production GovernedCanvasExporter over a real
    InvocationExecutionService (InMemoryInvocationStore) so the tests exercise
    the actual Binding -> Invocation boundary, plus an optional policy
    evaluator (GovernedInvocationExecutionService) for refusal tests.
    """
    from maistro.capabilities.binding import Binding
    from maistro.capabilities.governed_invocation import (
        GovernedInvocationExecutionService,
    )
    from maistro.capabilities.invocation import (
        InvocationExecutionService,
    )
    from maistro_canvas.canvas.publishing import (
        DesignExportProvider,
        GovernedCanvasExporter,
        InMemoryExportStore,
    )

    app = _make_app(store, api_keys=api_keys)
    provider = DesignExportProvider(compositor or StubCompositor())
    binding = Binding(workspace_id="ws-test", project_id="proj-test", capability="design.export")

    async def resolve(b: Any) -> Any:
        return provider

    service: Any = InvocationExecutionService(store=InMemoryInvocationStore())
    if policy is not None:
        service = GovernedInvocationExecutionService(
            invocation_service=service,
            event_store=InMemoryEventStore(),
            policy_evaluator=policy,
        )
    exporter = GovernedCanvasExporter(
        provider=provider,
        invocation_service=service,
        export_store=InMemoryExportStore(),
        binding=binding,
        resolver=resolve,
    )
    app.state.canvas_exporter = exporter
    if compositor is not None:
        app.state.canvas_compositor = compositor
    if events is not None:
        app.state.canvas_events = lambda name, payload: events.append((name, payload))
    return app


class TestNotImplementedStubs:
    def test_publish_without_governed_exporter_501(self, client: TestClient) -> None:
        created = _create(client)
        resp = client.post(f"/v2/canvas/designs/{created['id']}/publish", json={})
        assert resp.status_code == 501
        assert "governed" in resp.json()["detail"]

    def test_export_without_governed_exporter_501(self, client: TestClient) -> None:
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/png")
        assert resp.status_code == 501
        assert "ungoverned" in resp.json()["detail"]

    def test_assets_without_registry_501(self, client: TestClient) -> None:
        assert client.get("/v2/canvas/assets").status_code == 501


class TestGovernedExport:
    def test_export_png_streams_bytes_with_provenance_headers(self, store: FakeCanvasStore) -> None:
        compositor = StubCompositor(png=b"\x89PNGfake")
        app = _governed_app(store, compositor=compositor)
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/png")
        assert resp.status_code == 200
        assert resp.content == b"\x89PNGfake"
        assert resp.headers["content-type"] == "image/png"
        assert resp.headers["content-disposition"].startswith("attachment;")
        assert resp.headers["x-maistro-export-id"]
        assert resp.headers["x-maistro-invocation-id"]
        assert resp.headers["x-maistro-state-digest"]

    def test_unsupported_format_is_explicit_422_not_501(self, store: FakeCanvasStore) -> None:
        app = _governed_app(store)
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/pdf")
        assert resp.status_code == 422
        body = resp.json()["detail"]
        assert body["code"] == "EXPORT_FORMAT_UNSUPPORTED"
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/svg")
        assert resp.status_code == 422

    def test_reexport_after_edit_creates_new_version_and_keeps_history(
        self, store: FakeCanvasStore
    ) -> None:
        compositor = StubCompositor()
        app = _governed_app(store, compositor=compositor)
        client = TestClient(app)
        created = _create(client)
        base = f"/v2/canvas/designs/{created['id']}"

        first = client.get(f"{base}/export/png")
        first_id = first.headers["x-maistro-export-id"]
        first_digest = first.headers["x-maistro-state-digest"]

        # Same state again → idempotent: same version, same bytes.
        again = client.get(f"{base}/export/png")
        assert again.headers["x-maistro-export-id"] == first_id

        # A later edit (canvas row update bumps the visual record state).
        created["name"] = "Edited"
        record = store.canvases[created["id"]]
        record.name = "Edited"
        second = client.get(f"{base}/export/png")
        second_id = second.headers["x-maistro-export-id"]
        assert second_id != first_id
        assert second.headers["x-maistro-state-digest"] != first_digest

        history = client.get(f"{base}/exports").json()
        assert len(history) == 2
        # Historical version is immutable and re-downloadable byte-exactly.
        old = client.get(f"{base}/exports/{first_id}")
        assert old.status_code == 200
        assert old.content == first.content
        assert old.headers["x-maistro-state-digest"] == first_digest

    def test_provider_failure_is_truthful_502(self, store: FakeCanvasStore) -> None:
        class Exploding(StubCompositor):
            async def encode(
                self, image_bytes: bytes, *, fmt: str = "png", quality: int = 90
            ) -> bytes:
                raise ValueError("encoder exploded")

        app = _governed_app(store, compositor=Exploding())
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/webp")
        assert resp.status_code == 502
        assert "encoder exploded" in resp.json()["detail"]

    def test_policy_deny_is_403(self, store: FakeCanvasStore) -> None:
        from maistro.policy.types import Decision, PolicyVerdict

        async def deny(binding: Any, request: Any, context: Any) -> PolicyVerdict:
            return PolicyVerdict(Decision.DENY, reason="export not approved", rule="t3")

        app = _governed_app(store, compositor=StubCompositor(), policy=deny)
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/png")
        assert resp.status_code == 403
        assert "export not approved" in resp.json()["detail"]

    def test_no_composite_and_no_compositor_501(self, store: FakeCanvasStore) -> None:
        app = _governed_app(store, compositor=None)
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/png")
        assert resp.status_code == 501
        assert "no composite exists" in resp.json()["detail"]


class TestGovernedPublish:
    def test_publish_creates_version_with_provenance(self, store: FakeCanvasStore) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        compositor = StubCompositor()
        app = _governed_app(store, compositor=compositor, events=events)
        client = TestClient(app)
        created = _create(client)
        events.clear()  # drop design.created from create; assert publish only
        resp = client.post(
            f"/v2/canvas/designs/{created['id']}/publish",
            json={"format": "png", "design_project_id": "dp-42"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["published"] is True
        assert body["design_project_id"] == "dp-42"
        assert body["invocation_id"]
        assert body["binding_id"]
        assert body["run_id"]
        assert body["node_run_id"]
        assert body["attempt_id"]
        assert body["state_digest"]
        assert body["sha256"]
        assert body["download_url"].endswith(body["export_id"])
        assert [name for name, _ in events] == ["design.published"]

    def test_publish_then_download_delivers_exact_bytes(self, store: FakeCanvasStore) -> None:
        compositor = StubCompositor(png=b"\x89PNGpublish")
        app = _governed_app(store, compositor=compositor)
        client = TestClient(app)
        created = _create(client)
        body = client.post(f"/v2/canvas/designs/{created['id']}/publish", json={}).json()
        downloaded = client.get(body["download_url"])
        assert downloaded.status_code == 200
        assert downloaded.content == b"\x89PNGpublish"

    def test_export_and_publish_emit_distinct_events(self, store: FakeCanvasStore) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        compositor = StubCompositor()
        app = _governed_app(store, compositor=compositor, events=events)
        client = TestClient(app)
        created = _create(client)
        events.clear()
        client.get(f"/v2/canvas/designs/{created['id']}/export/png")
        client.post(f"/v2/canvas/designs/{created['id']}/publish", json={})
        assert [name for name, _ in events] == ["design.exported", "design.published"]
        assert all(e["design_id"] == created["id"] for _, e in events)


# ── Route failure contract (#94): every failure is truthful and typed ──


class _FormatslessExporter:
    """Duck-typed exporter that declares no ``supported_formats`` contract.

    maistro-server carries no maistro-canvas dependency: a silent exporter
    must not be handed an invented route-level refusal — format truthfulness
    belongs to the governed capability itself.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @property
    def export_store(self) -> Any:
        return self._inner.export_store

    async def export_canvas(self, *args: Any, **kwargs: Any) -> Any:
        return await self._inner.export_canvas(*args, **kwargs)


class TestRouteFailureContract:
    def test_no_declared_formats_skips_route_validation(self, store: FakeCanvasStore) -> None:
        """No ``supported_formats`` declaration → the route invents no 422."""
        app = _governed_app(store, compositor=StubCompositor())
        app.state.canvas_exporter = _FormatslessExporter(app.state.canvas_exporter)
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/png")
        assert resp.status_code == 200

    def test_capability_refuses_undeclared_format_with_its_own_422(
        self, store: FakeCanvasStore
    ) -> None:
        """The governed capability's own refusal carries the machine-readable code."""
        from maistro_canvas.canvas.publishing import SUPPORTED_EXPORT_FORMATS

        app = _governed_app(store, compositor=StubCompositor())
        app.state.canvas_exporter = _FormatslessExporter(app.state.canvas_exporter)
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/pdf")
        assert resp.status_code == 422
        body = resp.json()["detail"]
        assert body["code"] == "EXPORT_FORMAT_UNSUPPORTED"
        assert "out of scope" in body["reason"]
        assert "pdf" not in SUPPORTED_EXPORT_FORMATS

    def test_explicit_export_store_shadows_exporter_store(self, store: FakeCanvasStore) -> None:
        from maistro_canvas.canvas.publishing import InMemoryExportStore

        app = _governed_app(store, compositor=StubCompositor())
        client = TestClient(app)
        created = _create(client)
        client.get(f"/v2/canvas/designs/{created['id']}/export/png")
        app.state.canvas_exports = InMemoryExportStore()
        history = client.get(f"/v2/canvas/designs/{created['id']}/exports")
        assert history.status_code == 200
        assert history.json() == []  # the explicit store, not the exporter's

    def test_export_history_without_any_store_501(self, store: FakeCanvasStore) -> None:
        class _NoStoreExporter:
            async def export_canvas(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
                raise AssertionError("history listing must not export")

        app = _make_app(store)
        app.state.canvas_exporter = _NoStoreExporter()
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/exports")
        assert resp.status_code == 501
        assert "no export store is configured" in resp.json()["detail"]

    def test_compositor_http_error_passes_through(self, store: FakeCanvasStore) -> None:
        from fastapi import HTTPException

        class _UpstreamGone(StubCompositor):
            async def composite(self, canvas: Any, layers: list[Any]) -> Any:
                raise HTTPException(status_code=404, detail="upstream render gone")

        app = _governed_app(store, compositor=_UpstreamGone())
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/png")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "upstream render gone"

    def test_compositor_crash_is_truthful_502(self, store: FakeCanvasStore) -> None:
        class _Crashing(StubCompositor):
            async def composite(self, canvas: Any, layers: list[Any]) -> Any:
                raise RuntimeError("compositor core dumped")

        app = _governed_app(store, compositor=_Crashing())
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/png")
        assert resp.status_code == 502
        assert "Composite failed" in resp.json()["detail"]
        assert "compositor core dumped" in resp.json()["detail"]

    def test_composite_persistence_failure_is_502(self, store: FakeCanvasStore) -> None:
        class _Unsaveable(FakeCanvasStore):
            async def save_composite(self, composite: Any) -> None:
                raise OSError("composite bucket unavailable")

        app = _governed_app(_Unsaveable(), compositor=StubCompositor())
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/png")
        assert resp.status_code == 502
        assert "Composite persistence failed" in resp.json()["detail"]
        assert "composite bucket unavailable" in resp.json()["detail"]

    def test_missing_export_dependency_is_501_with_code(self, store: FakeCanvasStore) -> None:
        from maistro_canvas.export import ExporterDependencyError

        class _NoPptxExporter:
            async def export_canvas(self, *args: Any, **kwargs: Any) -> Any:
                raise ExporterDependencyError("python-pptx is not installed")

        app = _make_app(store)
        app.state.canvas_exporter = _NoPptxExporter()
        app.state.canvas_compositor = StubCompositor()  # composite succeeds; export refuses
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/pptx")
        assert resp.status_code == 501
        body = resp.json()["detail"]
        assert body["code"] == "EXPORTER_DEPENDENCY_MISSING"
        assert "python-pptx" in body["reason"]

    def test_failed_invocation_reports_invocation_identity(self, store: FakeCanvasStore) -> None:
        from maistro_canvas.canvas.publishing import ExportFailed

        class _SettledFailedExporter:
            async def export_canvas(self, *args: Any, **kwargs: Any) -> Any:
                raise ExportFailed(
                    "export invocation inv-9 ended failed: provider refused",
                    invocation_id="inv-9",
                    status="failed",
                )

        app = _make_app(store)
        app.state.canvas_exporter = _SettledFailedExporter()
        app.state.canvas_compositor = StubCompositor()  # composite succeeds; invocation failed
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/png")
        assert resp.status_code == 502
        body = resp.json()["detail"]
        assert body["code"] == "EXPORT_FAILED"
        assert body["invocation_id"] == "inv-9"
        assert body["invocation_status"] == "failed"

    def test_publish_provider_failure_is_truthful_502(self, store: FakeCanvasStore) -> None:
        class Exploding(StubCompositor):
            async def encode(
                self, image_bytes: bytes, *, fmt: str = "png", quality: int = 90
            ) -> bytes:
                raise ValueError("encoder exploded")

        app = _governed_app(store, compositor=Exploding())
        client = TestClient(app)
        created = _create(client)
        # webp routes through the provider's encode step (png streams the
        # composite as-is), so the crash actually happens under the governed
        # Invocation rather than being silently absent from the path.
        resp = client.post(f"/v2/canvas/designs/{created['id']}/publish", json={"format": "webp"})
        assert resp.status_code == 502
        assert "encoder exploded" in resp.json()["detail"]

    def test_unknown_export_version_404(self, store: FakeCanvasStore) -> None:
        app = _governed_app(store, compositor=StubCompositor())
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/exports/does-not-exist")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Export version not found"


# ── Content negotiation (canvas-local media type; ADR-076's general scheme
# ── lives in maistro.api_versioning and is tested separately) ──────────


class TestContentNegotiation:
    def test_default_is_application_json(self, client: TestClient) -> None:
        resp = client.get("/v2/canvas/designs")
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.headers["maistro-api-version"] == "2"

    def test_vendor_media_type_v2(self, client: TestClient) -> None:
        created = _create(client)
        plain = client.get(f"/v2/canvas/designs/{created['id']}")
        negotiated = client.get(
            f"/v2/canvas/designs/{created['id']}",
            headers={"Accept": "application/vnd.canvas+json;version=2"},
        )
        assert negotiated.status_code == 200
        assert negotiated.headers["content-type"].startswith(
            "application/vnd.canvas+json;version=2"
        )
        # same body either way
        assert negotiated.json() == plain.json()

    def test_vendor_media_type_without_version_defaults_to_v2(self, client: TestClient) -> None:
        resp = client.get("/v2/canvas/designs", headers={"Accept": "application/vnd.canvas+json"})
        assert resp.status_code == 200
        assert "version=2" in resp.headers["content-type"]

    def test_unsupported_version_406(self, client: TestClient) -> None:
        resp = client.get(
            "/v2/canvas/designs",
            headers={"Accept": "application/vnd.canvas+json;version=9"},
        )
        assert resp.status_code == 406


# ── Auth ──────────────────────────────────────────────────────────────


class TestAuth:
    def test_auth_required_when_keys_configured(self, store: FakeCanvasStore) -> None:
        app = _make_app(store, api_keys=["alice:secret-token"])
        client = TestClient(app)
        assert client.get("/v2/canvas/designs").status_code == 401
        assert (
            client.get("/v2/canvas/designs", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )

    def test_valid_token_scopes_to_principal(self, store: FakeCanvasStore) -> None:
        app = _make_app(store, api_keys=["alice:secret-token"])
        client = TestClient(app)
        headers = {"Authorization": "Bearer secret-token"}
        resp = client.post(
            "/v2/canvas/designs",
            json={"name": "mine", "width": 10, "height": 10},
            headers=headers,
        )
        assert resp.status_code == 201
        assert resp.json()["org_id"] == "alice"
        assert client.get("/v2/canvas/designs", headers=headers).json()[0]["name"] == "mine"


# ── Events ────────────────────────────────────────────────────────────


class TestEvents:
    def test_mutations_emit_exactly_one_event(self, store: FakeCanvasStore) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        app = _make_app(store)
        app.state.canvas_events = lambda name, payload: events.append((name, payload))
        client = TestClient(app)

        created = _create(client)
        client.put(f"/v2/canvas/designs/{created['id']}", json={"name": "x"})
        client.delete(f"/v2/canvas/designs/{created['id']}")

        assert [e[0] for e in events] == ["design.created", "design.updated", "design.deleted"]
        assert all(e[1]["design_id"] == created["id"] for e in events)

    def test_reads_emit_nothing(self, store: FakeCanvasStore) -> None:
        events: list[Any] = []
        app = _make_app(store)
        app.state.canvas_events = lambda name, payload: events.append(name)
        client = TestClient(app)
        created = _create(client)
        events.clear()
        client.get("/v2/canvas/designs")
        client.get(f"/v2/canvas/designs/{created['id']}")
        assert events == []


# ── Public surface declaration ────────────────────────────────────────


class TestPublicSurfaceDeclaration:
    """Every @router handler in canvas.py must be declared in ``__all__``.

    FastAPI registers handlers from the decorators, which static import
    scanning cannot see. The module's ``__all__`` (the a2a.py convention) is
    what declares the handlers as the module's public surface and keeps them
    out of the fastapi-route-handler Vulture ledger; a new handler that skips
    the declaration would resurface as unbanked dead-code debt and fail the
    exact-debt-ledger CI gate. This catches that drift here first, with an
    actionable message.
    """

    def test_all_covers_every_route_handler(self) -> None:
        import ast
        from pathlib import Path

        import maistro_server.api.canvas as canvas_module

        source = Path(str(canvas_module.__file__)).read_text(encoding="utf-8")
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
        declared = set(canvas_module.__all__)
        missing = sorted(handlers - declared)
        assert not missing, (
            f"route handlers missing from canvas.py __all__: {missing}. "
            "FastAPI registers handlers dynamically, so every @router handler "
            "must be declared in the module's __all__ (see a2a.py and the "
            "comment above canvas.py's __all__) rather than re-entering the "
            "fastapi-route-handler Vulture ledger as unbanked debt."
        )
