"""Tests for /v2/canvas routes (SPEC-070226-8239 Phase 1, ADR-045/ADR-076).

Evidence: the routes proxy an injected CanvasStore (app.state.canvas_store),
soft-delete via archived_at, negotiate application/vnd.canvas+json;version=2,
and use the same bearer auth dependency as every other route.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro.config.settings import Settings, get_settings
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


# ── 501 stubs ─────────────────────────────────────────────────────────


class TestNotImplementedStubs:
    def test_publish_501(self, client: TestClient) -> None:
        created = _create(client)
        resp = client.post(f"/v2/canvas/designs/{created['id']}/publish")
        assert resp.status_code == 501

    def test_export_pdf_501(self, client: TestClient) -> None:
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/pdf")
        assert resp.status_code == 501

    def test_export_png_without_compositor_501(self, client: TestClient) -> None:
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/png")
        assert resp.status_code == 501

    def test_assets_without_registry_501(self, client: TestClient) -> None:
        assert client.get("/v2/canvas/assets").status_code == 501


class TestExportWithCompositor:
    def test_export_png_streams_attachment(self, store: FakeCanvasStore) -> None:
        class FakeComposite:
            image_bytes = b"\x89PNGfake"

        class FakeCompositor:
            async def composite(self, canvas: Any, layers: list[Any]) -> FakeComposite:
                return FakeComposite()

        saved: list[Any] = []

        async def save_composite(result: Any) -> Any:
            saved.append(result)
            return result

        store.save_composite = save_composite  # type: ignore[attr-defined]
        app = _make_app(store)
        app.state.canvas_compositor = FakeCompositor()
        client = TestClient(app)
        created = _create(client)
        resp = client.get(f"/v2/canvas/designs/{created['id']}/export/png")
        assert resp.status_code == 200
        assert resp.content == b"\x89PNGfake"
        assert resp.headers["content-type"] == "image/png"
        assert resp.headers["content-disposition"].startswith("attachment;")
        assert saved  # composite cached back into the store


# ── Content negotiation (ADR-076) ─────────────────────────────────────


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
