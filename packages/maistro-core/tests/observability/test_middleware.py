"""Coverage for observability/middleware.py."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from maistro.observability.middleware import RequestIDMiddleware


async def _handler(request: object) -> PlainTextResponse:
    return PlainTextResponse("ok")


def _make_app() -> Starlette:
    app = Starlette(routes=[Route("/", _handler)])
    app.add_middleware(RequestIDMiddleware)
    return app


def test_dispatch_generates_request_id_when_header_absent() -> None:
    client = TestClient(_make_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) == 12


def test_dispatch_reuses_request_id_from_header() -> None:
    client = TestClient(_make_app())
    response = client.get("/", headers={"X-Request-ID": "custom-id-123"})
    assert response.headers["X-Request-ID"] == "custom-id-123"
