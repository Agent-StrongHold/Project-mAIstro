"""Coverage for observability/middleware.py."""

from __future__ import annotations

import re

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from maistro.observability.correlation import (
    bind_execution_context,
    current_execution_context,
)
from maistro.observability.middleware import REQUEST_ID_MAX_LENGTH, RequestIDMiddleware


async def _handler(request: Request) -> PlainTextResponse:
    return PlainTextResponse(request.state.request_id)


def _make_app() -> Starlette:
    app = Starlette(routes=[Route("/", _handler)])
    app.add_middleware(RequestIDMiddleware)
    return app


def test_dispatch_generates_request_id_when_header_absent() -> None:
    client = TestClient(_make_app())
    response = client.get("/")
    next_response = client.get("/")

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    request_id = response.headers["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{12}", request_id)
    assert response.text == request_id
    assert next_response.headers["X-Request-ID"] != request_id


@pytest.mark.parametrize(
    "request_id",
    [
        "custom-id-123",
        "550e8400-e29b-41d4-a716-446655440000",
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "build.v1_request-42",
        "a" * REQUEST_ID_MAX_LENGTH,
    ],
)
def test_dispatch_reuses_valid_request_id_from_header(request_id: str) -> None:
    client = TestClient(_make_app())
    response = client.get("/", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id
    assert response.text == request_id


def test_one_character_request_id_is_preserved() -> None:
    client = TestClient(_make_app())
    response = client.get("/", headers={"X-Request-ID": "a"})

    assert response.headers["X-Request-ID"] == "a"
    assert response.text == "a"


async def _dispatch_with_raw_request_ids(*raw_request_ids: bytes) -> PlainTextResponse:
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-request-id", value) for value in raw_request_ids],
            "method": "GET",
            "path": "/",
        }
    )
    middleware = RequestIDMiddleware(Starlette())

    async def downstream(inner_request: Request) -> PlainTextResponse:
        context_id = current_execution_context().request_id
        return PlainTextResponse(f"{context_id}|{inner_request.state.request_id}")

    response = await middleware.dispatch(request, downstream)
    assert isinstance(response, PlainTextResponse)
    return response


def _assert_generated_and_propagated(response: PlainTextResponse) -> str:
    effective_id = response.headers["X-Request-ID"]
    context_id, state_id = bytes(response.body).decode("utf-8").split("|")
    assert re.fullmatch(r"[0-9a-f]{12}", effective_id)
    assert context_id == state_id == effective_id
    return effective_id


def _assert_rejected_values_absent(
    response: PlainTextResponse,
    *raw_request_ids: bytes,
) -> None:
    body = bytes(response.body).decode("utf-8")
    header_values = [value.decode("latin-1") for _, value in response.raw_headers]
    for raw_request_id in raw_request_ids:
        asgi_header_value = raw_request_id.decode("latin-1")
        assert asgi_header_value not in body
        assert all(asgi_header_value not in value for value in header_values)


@pytest.mark.parametrize(
    "untrusted_id",
    [
        b"a" * (REQUEST_ID_MAX_LENGTH + 1),
        b"request id",
        b"caf\xc3\xa9",
        b"request/id!",
    ],
    ids=["oversized", "whitespace", "unicode", "punctuation"],
)
async def test_invalid_request_id_is_replaced_before_propagation(
    untrusted_id: bytes,
) -> None:
    response = await _dispatch_with_raw_request_ids(untrusted_id)

    _assert_generated_and_propagated(response)
    _assert_rejected_values_absent(response, untrusted_id)


async def test_empty_request_id_is_replaced() -> None:
    response = await _dispatch_with_raw_request_ids(b"")

    _assert_generated_and_propagated(response)


@pytest.mark.parametrize(
    "untrusted_id",
    [
        b"request\x00id",
        b"request\x1fid",
        b"request\r\nforged-log",
        b"request\x7fid",
    ],
    ids=["nul", "unit-separator", "crlf", "delete"],
)
async def test_nul_and_control_bytes_are_rejected(untrusted_id: bytes) -> None:
    response = await _dispatch_with_raw_request_ids(untrusted_id)

    _assert_generated_and_propagated(response)
    _assert_rejected_values_absent(response, untrusted_id)


@pytest.mark.parametrize(
    "delimiter",
    [b"=", b";", b"]", b'"'],
    ids=["equals", "semicolon", "bracket", "quote"],
)
async def test_log_and_header_delimiters_are_rejected(delimiter: bytes) -> None:
    untrusted_id = b"request" + delimiter + b"id"
    response = await _dispatch_with_raw_request_ids(untrusted_id)

    _assert_generated_and_propagated(response)
    _assert_rejected_values_absent(response, untrusted_id)


async def test_duplicate_request_id_headers_generate_server_id() -> None:
    duplicate_ids = (b"first-request", b"second-request")
    response = await _dispatch_with_raw_request_ids(*duplicate_ids)

    _assert_generated_and_propagated(response)
    _assert_rejected_values_absent(response, *duplicate_ids)


async def test_punctuation_only_request_id_is_rejected() -> None:
    untrusted_id = b"._-"
    response = await _dispatch_with_raw_request_ids(untrusted_id)

    _assert_generated_and_propagated(response)
    _assert_rejected_values_absent(response, untrusted_id)


# ─── The request id reaches the canonical execution context (#707) ────────────


async def _context_handler(request: Request) -> PlainTextResponse:
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
    local event raised under the request named no request."""
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
