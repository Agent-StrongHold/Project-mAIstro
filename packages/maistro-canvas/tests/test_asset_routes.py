"""HTTP route tests for ADR-042. Uses FastAPI TestClient against an
``InMemoryAssetStore`` factory."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro_canvas.canvas.asset_routes import make_router
from maistro_canvas.canvas.asset_store import InMemoryAssetStore

TEST_TOKEN = "test-canvas-token"


@pytest.fixture
def store() -> InMemoryAssetStore:
    return InMemoryAssetStore()


@pytest.fixture
def client(store: InMemoryAssetStore, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("CANVAS_API_TOKEN", TEST_TOKEN)
    app = FastAPI()
    app.include_router(make_router(get_store=lambda: store))
    with TestClient(
        app,
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    ) as c:
        yield c


def _world_style() -> dict:
    return {
        "era": "modern",
        "realism": "watercolor",
        "architectural_register": "cottage",
        "vehicle_register": "1970s-pickup",
        "palette_anchors": ["sage", "cream"],
        "fauna_realism": "cute",
    }


# ─────────────────────────────────────────────────────────────────────
# AssetDefinition
# ─────────────────────────────────────────────────────────────────────


def test_register_definition_returns_201(client: TestClient) -> None:
    body = {
        "asset_id": "farmhouse",
        "kind": "structure",
        "base_prompt": "a small red farmhouse",
        "sockets": [{"name": "porch", "x": 0.5, "y": 0.6, "role": None}],
    }
    r = client.post("/v2/canvas/asset-definitions", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["asset_id"] == "farmhouse"
    assert data["kind"] == "structure"


def test_get_definition_404_when_missing(client: TestClient) -> None:
    r = client.get("/v2/canvas/asset-definitions/nope")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "ASSET_DEFINITION_NOT_FOUND"


# ─────────────────────────────────────────────────────────────────────
# Auth regression (every v2 handler must require a valid canvas token)
# ─────────────────────────────────────────────────────────────────────


def test_missing_token_is_401(store: InMemoryAssetStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every v2 route must reject unauthenticated requests, not just the
    v1 surface — this was previously a bare ``store_dep`` with no auth
    dependency at all."""
    monkeypatch.setenv("CANVAS_API_TOKEN", TEST_TOKEN)
    app = FastAPI()
    app.include_router(make_router(get_store=lambda: store))
    with TestClient(app) as c:
        r = c.get("/v2/canvas/asset-definitions/nope")
    assert r.status_code == 401, r.text


def test_wrong_token_is_401(store: InMemoryAssetStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", TEST_TOKEN)
    app = FastAPI()
    app.include_router(make_router(get_store=lambda: store))
    with TestClient(app, headers={"Authorization": "Bearer wrong-token"}) as c:
        r = c.get("/v2/canvas/asset-definitions/nope")
    assert r.status_code == 401, r.text


def test_unconfigured_token_fails_closed_503(
    store: InMemoryAssetStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CANVAS_API_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(make_router(get_store=lambda: store))
    with TestClient(app, headers={"Authorization": "Bearer anything"}) as c:
        r = c.get("/v2/canvas/asset-definitions/nope")
    assert r.status_code == 503, r.text


def test_register_then_get_definition_round_trip(client: TestClient) -> None:
    body = {
        "asset_id": "cap",
        "kind": "prop",
        "base_prompt": "a baseball cap",
    }
    client.post("/v2/canvas/asset-definitions", json=body)
    r = client.get("/v2/canvas/asset-definitions/cap")
    assert r.status_code == 200
    assert r.json()["base_prompt"] == "a baseball cap"


def test_register_definition_idempotent(client: TestClient) -> None:
    body = {"asset_id": "x", "kind": "prop", "base_prompt": "y"}
    a = client.post("/v2/canvas/asset-definitions", json=body)
    b = client.post("/v2/canvas/asset-definitions", json=body)
    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json() == b.json()


def test_register_definition_diverging_returns_400(client: TestClient) -> None:
    a = {"asset_id": "x", "kind": "prop", "base_prompt": "y"}
    b = {"asset_id": "x", "kind": "prop", "base_prompt": "different"}
    client.post("/v2/canvas/asset-definitions", json=a)
    r = client.post("/v2/canvas/asset-definitions", json=b)
    assert r.status_code == 400


def test_list_definitions_filters_by_kind(client: TestClient) -> None:
    client.post(
        "/v2/canvas/asset-definitions",
        json={"asset_id": "h1", "kind": "structure", "base_prompt": "x"},
    )
    client.post(
        "/v2/canvas/asset-definitions",
        json={"asset_id": "v1", "kind": "vehicle", "base_prompt": "x"},
    )
    r = client.get("/v2/canvas/asset-definitions?kind=structure")
    assert r.status_code == 200
    assert {d["asset_id"] for d in r.json()} == {"h1"}


def test_update_definition_404_when_missing(client: TestClient) -> None:
    r = client.put(
        "/v2/canvas/asset-definitions/ghost",
        json={"asset_id": "ghost", "kind": "prop", "base_prompt": "x"},
    )
    assert r.status_code == 404


def test_update_definition_409_on_id_mismatch(client: TestClient) -> None:
    client.post(
        "/v2/canvas/asset-definitions",
        json={"asset_id": "x", "kind": "prop", "base_prompt": "x"},
    )
    r = client.put(
        "/v2/canvas/asset-definitions/x",
        json={"asset_id": "y", "kind": "prop", "base_prompt": "x"},
    )
    assert r.status_code == 409


# ─────────────────────────────────────────────────────────────────────
# AssetSheet
# ─────────────────────────────────────────────────────────────────────


def test_upsert_and_get_sheet(client: TestClient) -> None:
    # Sheets reference asset_definitions; create the definition first.
    client.post(
        "/v2/canvas/asset-definitions",
        json={"asset_id": "char", "kind": "character", "base_prompt": "x"},
    )
    r = client.put(
        "/v2/canvas/asset-sheets/char",
        json={
            "asset_id": "char",
            "refs": ["/r1.png", "/r2.png", "/r3.png"],
            "sheet_image": "/sheet.png",
            "revision": 1,
            "generation_params": {},
        },
    )
    assert r.status_code == 200
    g = client.get("/v2/canvas/asset-sheets/char")
    assert g.status_code == 200
    assert g.json()["sheet_image"] == "/sheet.png"


def test_regenerate_sheet_bumps_revision(client: TestClient) -> None:
    client.post(
        "/v2/canvas/asset-definitions",
        json={"asset_id": "char", "kind": "character", "base_prompt": "x"},
    )
    r1 = client.post(
        "/v2/canvas/asset-sheets/char/regenerate",
        json={
            "sheet_image": "/v1.png",
            "refs": ["/r1.png", "/r2.png", "/r3.png"],
        },
    )
    assert r1.status_code == 200
    assert r1.json()["revision"] == 1
    r2 = client.post(
        "/v2/canvas/asset-sheets/char/regenerate",
        json={"sheet_image": "/v2.png"},
    )
    assert r2.status_code == 200
    assert r2.json()["revision"] == 2


def test_regenerate_sheet_404_when_no_prior_and_no_refs(client: TestClient) -> None:
    client.post(
        "/v2/canvas/asset-definitions",
        json={"asset_id": "char", "kind": "character", "base_prompt": "x"},
    )
    r = client.post(
        "/v2/canvas/asset-sheets/char/regenerate",
        json={"sheet_image": "/v.png"},
    )
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────
# AssetInstance
# ─────────────────────────────────────────────────────────────────────


def _seed_def(client: TestClient, asset_id: str = "a", kind: str = "structure") -> None:
    client.post(
        "/v2/canvas/asset-definitions",
        json={"asset_id": asset_id, "kind": kind, "base_prompt": "x"},
    )


def test_upsert_and_get_instance(client: TestClient) -> None:
    _seed_def(client)
    body = {
        "instance_id": "i1",
        "canvas_id": "c1",
        "definition": "a",
        "anchor": "ground_contact",
    }
    r = client.post("/v2/canvas/asset-instances", json=body)
    assert r.status_code == 200
    g = client.get("/v2/canvas/asset-instances/i1")
    assert g.status_code == 200
    assert g.json()["definition"] == "a"
    assert g.json()["anchor"] == "ground_contact"


def test_upsert_instance_with_inline_definition(client: TestClient) -> None:
    body = {
        "instance_id": "cloud",
        "canvas_id": "c1",
        "definition": {
            "asset_id": "",
            "kind": "fx",
            "base_prompt": "a wispy cloud",
        },
        "anchor": "floating",
    }
    r = client.post("/v2/canvas/asset-instances", json=body)
    assert r.status_code == 200
    out = r.json()
    assert isinstance(out["definition"], dict)
    assert out["definition"]["kind"] == "fx"


def test_list_instances_scopes_to_canvas(client: TestClient) -> None:
    _seed_def(client)
    client.post(
        "/v2/canvas/asset-instances",
        json={"instance_id": "x", "canvas_id": "c1", "definition": "a"},
    )
    client.post(
        "/v2/canvas/asset-instances",
        json={"instance_id": "y", "canvas_id": "c2", "definition": "a"},
    )
    r = client.get("/v2/canvas/canvases/c1/instances")
    assert r.status_code == 200
    assert {i["instance_id"] for i in r.json()} == {"x"}


def test_delete_instance_returns_204(client: TestClient) -> None:
    _seed_def(client)
    client.post(
        "/v2/canvas/asset-instances",
        json={"instance_id": "x", "canvas_id": "c1", "definition": "a"},
    )
    r = client.delete("/v2/canvas/asset-instances/x")
    assert r.status_code == 204
    g = client.get("/v2/canvas/asset-instances/x")
    assert g.status_code == 404


# ─────────────────────────────────────────────────────────────────────
# ChildProfile
# ─────────────────────────────────────────────────────────────────────


def test_upsert_and_get_profile(client: TestClient) -> None:
    body = {
        "profile_id": "p_sarah",
        "name": "Sarah",
        "pronouns": "she/her",
        "likeness_refs": ["/a.jpg"],
        "accommodations": ["headphones"],
    }
    r = client.put("/v2/canvas/child-profiles/p_sarah", json=body)
    assert r.status_code == 200
    g = client.get("/v2/canvas/child-profiles/p_sarah")
    assert g.status_code == 200
    assert g.json()["name"] == "Sarah"


def test_upsert_profile_409_on_id_mismatch(client: TestClient) -> None:
    r = client.put(
        "/v2/canvas/child-profiles/p_a",
        json={"profile_id": "p_b", "name": "X"},
    )
    assert r.status_code == 409


# ─────────────────────────────────────────────────────────────────────
# Book
# ─────────────────────────────────────────────────────────────────────


def test_create_and_get_book(client: TestClient) -> None:
    body = {
        "book_id": "b1",
        "title": "Test Book",
        "world_style": _world_style(),
    }
    r = client.post("/v2/canvas/books", json=body)
    assert r.status_code == 201
    g = client.get("/v2/canvas/books/b1")
    assert g.status_code == 200
    assert g.json()["title"] == "Test Book"


def test_create_book_rejects_inverted_page_range(client: TestClient) -> None:
    body = {
        "book_id": "b1",
        "title": "Bad",
        "world_style": _world_style(),
        "style_volumes": [
            {"page_range": [9, 7], "partial_world_style": None, "partial_render_style": None}
        ],
    }
    r = client.post("/v2/canvas/books", json=body)
    assert r.status_code == 400


def test_update_book_409_on_id_mismatch(client: TestClient) -> None:
    body_a = {"book_id": "a", "title": "A", "world_style": _world_style()}
    client.post("/v2/canvas/books", json=body_a)
    r = client.put(
        "/v2/canvas/books/a",
        json={"book_id": "b", "title": "B", "world_style": _world_style()},
    )
    assert r.status_code == 409


# ─────────────────────────────────────────────────────────────────────
# Render plan
# ─────────────────────────────────────────────────────────────────────


def test_plan_endpoint_returns_render_plan(client: TestClient) -> None:
    _seed_def(client)
    client.post(
        "/v2/canvas/asset-instances",
        json={"instance_id": "x", "canvas_id": "c1", "definition": "a"},
    )
    r = client.post(
        "/v2/canvas/canvases/c1/plan",
        json={"world_style": _world_style()},
    )
    assert r.status_code == 200
    plan = r.json()
    assert plan["canvas_id"] == "c1"
    assert len(plan["rendered"]) == 1
    assert plan["rendered"][0]["instance_id"] == "x"


def test_plan_endpoint_uses_book_world_style(client: TestClient) -> None:
    _seed_def(client)
    client.post(
        "/v2/canvas/asset-instances",
        json={"instance_id": "x", "canvas_id": "c1", "definition": "a"},
    )
    client.post(
        "/v2/canvas/books",
        json={"book_id": "b1", "title": "T", "world_style": _world_style()},
    )
    r = client.post(
        "/v2/canvas/canvases/c1/plan",
        json={"book_id": "b1"},
    )
    assert r.status_code == 200


def test_plan_endpoint_400_when_no_world_style(client: TestClient) -> None:
    _seed_def(client)
    client.post(
        "/v2/canvas/asset-instances",
        json={"instance_id": "x", "canvas_id": "c1", "definition": "a"},
    )
    r = client.post("/v2/canvas/canvases/c1/plan", json={})
    assert r.status_code == 400


def test_plan_endpoint_422_on_occlusion_cycle(client: TestClient) -> None:
    _seed_def(client)
    client.post(
        "/v2/canvas/asset-instances",
        json={
            "instance_id": "A",
            "canvas_id": "c1",
            "definition": "a",
            "occlusion": {"in_front_of": ["B"], "behind": []},
        },
    )
    client.post(
        "/v2/canvas/asset-instances",
        json={
            "instance_id": "B",
            "canvas_id": "c1",
            "definition": "a",
            "occlusion": {"in_front_of": ["A"], "behind": []},
        },
    )
    r = client.post(
        "/v2/canvas/canvases/c1/plan",
        json={"world_style": _world_style()},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "OCCLUSION_CYCLE"


def test_plan_endpoint_is_pure(client: TestClient) -> None:
    _seed_def(client)
    client.post(
        "/v2/canvas/asset-instances",
        json={"instance_id": "x", "canvas_id": "c1", "definition": "a"},
    )
    body = {"world_style": _world_style()}
    a = client.post("/v2/canvas/canvases/c1/plan", json=body).json()
    b = client.post("/v2/canvas/canvases/c1/plan", json=body).json()
    assert a == b
