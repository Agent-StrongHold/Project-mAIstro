"""Coverage for observability/middleware.py."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from maistro.observability.correlation import (
    bind_execution_context,
    current_execution_context,
)
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


# ─── The request id reaches the canonical execution context (#707) ────────────


async def _context_handler(request: object) -> PlainTextResponse:
    ctx = current_execution_context()
    return PlainTextResponse(f"{ctx.request_id}|{getattr(request.state, 'request_id', '')}")


def _context_app() -> Starlette:
    app = Starlette(routes=[Route("/", _context_handler)])
    app.add_middleware(RequestIDMiddleware)
    return app


@pytest.mark.ac("SPEC-083026-20b2/AC-8")
def test_the_handler_runs_under_the_requests_execution_context() -> None:
    """The binding used to go straight into structlog's contextvars, which
    correlated log lines and nothing else. A handler could not read it, so a
    span or event raised under the request named no request."""
    client = TestClient(_context_app())
    body = client.get("/", headers={"X-Request-ID": "req-abc"}).text
    assert body == "req-abc|req-abc"


@pytest.mark.ac("SPEC-083026-20b2/AC-8")
def test_the_context_does_not_outlive_the_request() -> None:
    client = TestClient(_context_app())
    client.get("/", headers={"X-Request-ID": "req-abc"})
    assert current_execution_context().request_id == ""


@pytest.mark.ac("SPEC-083026-20b2/AC-8")
def test_a_binding_made_outside_the_request_survives_it() -> None:
    """`clear_contextvars()` went with the rewrite: it wiped bindings an outer
    middleware had deliberately made, and there was never a previous request's
    context left to clear -- Starlette gives each request its own."""
    with bind_execution_context(workspace_id="ws-1"):
        client = TestClient(_context_app())
        assert client.get("/", headers={"X-Request-ID": "req-abc"}).text == "req-abc|req-abc"
        assert current_execution_context().workspace_id == "ws-1"
