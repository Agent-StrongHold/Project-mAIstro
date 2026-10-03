"""`GET /design/packs` — the domain pack selector listing (M7-A4, #793).

The acceptance criterion this file pins: "Design Studio can list packs
without a pack-specific route becoming the product identity." Two properties
follow, and both are asserted:

- One listing route, one uniform entry shape. There is no
  `/design/packs/{pack_id}` route and no route naming a specific pack —
  product/game/book are bundles of one loop, not products of the API.
- `canvas` appears only under `execute_backends` (a binding), never as a
  `pack_id`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from main import app
from services import design_service

PATH = "/v1/design/packs"
PACK_IDS = {"product", "game", "book"}


@pytest.fixture
async def client(monkeypatch):
    """An authenticated client over a really-started design service.

    Mirrors the `/design/systems` fixture: `start_design_service` is called
    for real and the app lifespan is not run (it re-initialises stores and
    drops the seeded test user). The packs route itself needs no engine —
    starting the service proves the selector works in the same wiring the
    other design routes get.
    """
    monkeypatch.setattr(design_service, "_get_async_session_factory", lambda: None)
    monkeypatch.setattr(design_service, "_engine_singleton", None)
    monkeypatch.setattr(design_service, "_status", design_service.DesignServiceStatus())

    class _Settings:
        open_design_url = None
        open_design_api_key = None

    await design_service.start_design_service(_Settings())

    c = TestClient(app)
    response = c.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert response.status_code == 200, f"login failed: {response.text}"
    return c


class TestTheSelectorListing:
    def test_it_lists_exactly_the_three_shipped_packs(self, client) -> None:
        body = client.get(PATH)
        assert body.status_code == 200
        entries = body.json()
        assert {entry["pack_id"] for entry in entries} == PACK_IDS

    def test_every_entry_carries_one_uniform_shape(self, client) -> None:
        entries = client.get(PATH).json()
        assert entries, "the selector must never render an empty catalog silently"
        shapes = {tuple(sorted(entry)) for entry in entries}
        assert shapes == {("artifact_kinds", "execute_backends", "name", "pack_id", "summary")}


class TestNoPackBecomesAProduct:
    @staticmethod
    def _pack_paths() -> list[str]:
        # The OpenAPI schema is the flattened, fully-qualified truth of every
        # route the app serves — no walking FastAPI's deferred include tree.
        return sorted(
            path for path in app.openapi()["paths"] if path.startswith("/v1/design/packs")
        )

    def test_no_pack_specific_route_exists(self) -> None:
        # Exactly one route for packs — the listing. No {pack_id} parameter
        # route, and no path that names a specific pack.
        assert self._pack_paths() == ["/v1/design/packs"]

    def test_no_path_names_a_specific_pack(self) -> None:
        for path in self._pack_paths():
            assert "{" not in path, f"parameterized pack route: {path}"
            for pack_id in PACK_IDS:
                assert path != f"/v1/design/packs/{pack_id}"

    def test_canvas_is_a_binding_not_a_pack(self, client) -> None:
        entries = client.get(PATH).json()
        by_id = {entry["pack_id"]: entry for entry in entries}
        assert "canvas" not in by_id  # canvas is never a pack
        assert "canvas" in by_id["product"]["execute_backends"]
        assert "canvas" not in by_id["book"]["execute_backends"]
