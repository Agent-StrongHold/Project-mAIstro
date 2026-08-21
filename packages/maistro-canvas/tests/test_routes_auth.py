"""Smoke tests for the canvas v1 REST API (routes.py).

Regression coverage for two defects that made the entire v1 surface
non-functional:

  1. ``auth`` was a bare annotation (``auth: AuthDep``) with no
     ``= Depends(get_current_user)``, so FastAPI treated it as a
     required query parameter and every request returned 422.
  2. ``get_current_user`` returned a plain dict with no ``org_id``,
     but 19 handler sites do ``auth.org_id`` (attribute access),
     which raised ``AttributeError`` (500) once the 422 was fixed.

These tests assert an authenticated request reaches the handler
(2xx, never 422) and never raises ``AttributeError``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maistro_canvas.canvas.routes import make_canvas_router
from maistro_canvas.types import CanvasRecord


class _FakeStore:
    """Minimal in-memory CanvasStore for route smoke tests."""

    def __init__(self) -> None:
        self._canvases: dict[str, CanvasRecord] = {}
        self._seq = 0

    async def create_canvas(
        self,
        *,
        name: str,
        width: int,
        height: int,
        background_color: str = "#FFFFFF",
        org_id: str = "",
    ) -> CanvasRecord:
        self._seq += 1
        cid = f"canvas-{self._seq}"
        rec = CanvasRecord(
            id=cid,
            name=name,
            width=width,
            height=height,
            background_color=background_color,
            org_id=org_id,
        )
        self._canvases[cid] = rec
        return rec

    async def get_canvas(self, canvas_id: str) -> CanvasRecord | None:
        return self._canvases.get(canvas_id)

    async def list_canvases(
        self,
        org_id: str,
        *,
        include_archived: bool = False,
    ) -> list[CanvasRecord]:
        return [
            c
            for c in self._canvases.values()
            if c.org_id == org_id and (include_archived or not c.is_archived())
        ]

    async def list_layers(self, canvas_id: str) -> list[Any]:
        return []


class _FakeExecutor:
    pass


class _FakeCompositor:
    pass


TEST_TOKEN = "test-canvas-token"


def _make_app() -> FastAPI:
    store = _FakeStore()
    app = FastAPI()
    app.include_router(
        make_canvas_router(
            store=store,  # type: ignore[arg-type]
            executor=_FakeExecutor(),  # type: ignore[arg-type]
            compositor=_FakeCompositor(),  # type: ignore[arg-type]
        ),
        prefix="/api/canvas",
    )
    return app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("CANVAS_API_TOKEN", TEST_TOKEN)
    with TestClient(
        _make_app(),
        raise_server_exceptions=True,
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    ) as c:
        yield c


@pytest.fixture
def unconfigured_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("CANVAS_API_TOKEN", raising=False)
    with TestClient(_make_app(), raise_server_exceptions=True) as c:
        yield c


def test_list_canvases_authenticated_is_2xx(client: TestClient) -> None:
    """GET on the collection must reach the handler (not a 422 query error)."""
    r = client.get("/api/canvas")
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_create_canvas_authenticated_uses_org_id(client: TestClient) -> None:
    """POST must reach the handler and resolve auth.org_id without AttributeError."""
    r = client.post("/api/canvas", json={"name": "My Canvas", "width": 1024, "height": 1024})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "My Canvas"
    # org_id must be populated from auth, proving auth.org_id resolved.
    assert "org_id" in body


def test_missing_token_is_401(client: TestClient) -> None:
    """A request without credentials must be rejected, never served as admin."""
    r = client.get("/api/canvas", headers={"Authorization": ""})
    assert r.status_code == 401, r.text


def test_wrong_token_is_401(client: TestClient) -> None:
    r = client.get("/api/canvas", headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401, r.text


def test_bearer_scheme_is_case_insensitive(client: TestClient) -> None:
    """RFC 7235: the auth scheme token compares case-insensitively."""
    for scheme in ("bearer", "BEARER", "BeArEr"):
        r = client.get("/api/canvas", headers={"Authorization": f"{scheme} {TEST_TOKEN}"})
        assert r.status_code == 200, (scheme, r.text)


def test_x_canvas_token_header_is_accepted(client: TestClient) -> None:
    """The frontend's alternate X-Canvas-Token header must also authenticate."""
    r = client.get(
        "/api/canvas",
        headers={"Authorization": "", "X-Canvas-Token": TEST_TOKEN},
    )
    assert r.status_code == 200, r.text


def test_unconfigured_token_fails_closed_503(unconfigured_client: TestClient) -> None:
    """CANVAS_API_TOKEN unset → 503, not silent admin access (audit 3.2)."""
    r = unconfigured_client.get("/api/canvas", headers={"Authorization": "Bearer anything"})
    assert r.status_code == 503, r.text


def test_authenticated_user_is_not_admin(client: TestClient) -> None:
    """The standalone principal must be a scoped user, not an implicit admin."""
    import asyncio

    from maistro_canvas.auth import get_current_user

    user = asyncio.run(get_current_user(authorization=f"Bearer {TEST_TOKEN}", x_canvas_token=None))
    assert "admin" not in user.roles


def test_create_then_list_round_trip(client: TestClient) -> None:
    """Edge case: a created canvas is visible in the org-scoped listing,
    proving the same org_id flows through create and list."""
    created = client.post("/api/canvas", json={"name": "Round Trip"})
    assert created.status_code == 201, created.text
    listed = client.get("/api/canvas")
    assert listed.status_code == 200, listed.text
    names = [c["name"] for c in listed.json()]
    assert "Round Trip" in names
