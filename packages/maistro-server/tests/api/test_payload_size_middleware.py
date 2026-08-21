"""Tests for PayloadSizeLimitMiddleware.

Ported from stronghold's ``tests/api/test_middleware.py`` (the
``PayloadSizeLimitMiddleware`` section, lines 71-186), adapted to a minimal
standalone FastAPI app + TestClient rather than the full
``maistro_server.main.app`` — the middleware's ``max_bytes`` is a
constructor argument fixed at app-build time (mirroring how
``maistro_server.main`` wires it from ``Settings.max_request_body_bytes``),
so tests build their own tiny app per limit rather than trying to override
settings on the shared app after the fact.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse as StarletteJSON
from starlette.routing import Route

from maistro_server.api.middleware import PayloadSizeLimitMiddleware


def _payload_app(max_bytes: int = 1000) -> FastAPI:
    """Build a minimal app with PayloadSizeLimitMiddleware."""

    async def echo(request: StarletteRequest) -> StarletteJSON:
        body = await request.body()
        return StarletteJSON({"size": len(body)})

    app = FastAPI(routes=[Route("/echo", echo, methods=["POST"])])
    app.add_middleware(PayloadSizeLimitMiddleware, max_bytes=max_bytes)
    return app


class TestPayloadSizeLimitUnderLimit:
    """Requests with Content-Length under the limit pass through."""

    def test_small_request_passes(self) -> None:
        app = _payload_app(max_bytes=1000)
        with TestClient(app) as client:
            resp = client.post("/echo", content=b"hello")
            assert resp.status_code == 200
            assert resp.json()["size"] == 5


class TestPayloadSizeLimitOverLimit:
    """Requests exceeding the byte limit are rejected with 413."""

    def test_oversized_request_returns_413(self) -> None:
        app = _payload_app(max_bytes=100)
        with TestClient(app) as client:
            resp = client.post(
                "/echo",
                content=b"x" * 200,
                headers={"Content-Length": "200"},
            )
            assert resp.status_code == 413
            body = resp.json()
            assert "Payload too large" in body["error"]["message"]
            assert body["error"]["code"] == "PAYLOAD_TOO_LARGE"

    def test_exactly_at_limit_passes(self) -> None:
        app = _payload_app(max_bytes=100)
        with TestClient(app) as client:
            resp = client.post(
                "/echo",
                content=b"x" * 100,
                headers={"Content-Length": "100"},
            )
            assert resp.status_code == 200

    def test_one_byte_over_limit_returns_413(self) -> None:
        app = _payload_app(max_bytes=100)
        with TestClient(app) as client:
            resp = client.post(
                "/echo",
                content=b"x" * 101,
                headers={"Content-Length": "101"},
            )
            assert resp.status_code == 413


class TestPayloadSizeLimitNoContentLength:
    """Requests with no Content-Length header pass through (GET, empty POST)."""

    def test_get_request_passes_through(self) -> None:
        """GET requests have no body and should always pass."""

        async def healthcheck(request: StarletteRequest) -> StarletteJSON:
            return StarletteJSON({"ok": True})

        app = FastAPI(
            routes=[
                Route("/health", healthcheck, methods=["GET"]),
                Route("/echo", lambda r: StarletteJSON({"ok": True}), methods=["POST"]),
            ]
        )
        app.add_middleware(PayloadSizeLimitMiddleware, max_bytes=10)
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_post_without_content_length_passes(self) -> None:
        """POST with no Content-Length and no chunked encoding passes."""
        app = _payload_app(max_bytes=1000)
        with TestClient(app) as client:
            # Sending empty body -- no Content-Length header
            resp = client.post("/echo")
            assert resp.status_code == 200


class TestPayloadSizeLimitInvalidContentLength:
    """Invalid Content-Length values are rejected with 400."""

    def test_invalid_content_length_returns_400(self) -> None:
        app = _payload_app(max_bytes=1000)
        with TestClient(app) as client:
            resp = client.post(
                "/echo",
                content=b"hello",
                headers={"Content-Length": "not-a-number"},
            )
            assert resp.status_code == 400
            assert "Invalid Content-Length" in resp.json()["error"]["message"]

    def test_negative_content_length_returns_413(self) -> None:
        app = _payload_app(max_bytes=1000)
        with TestClient(app) as client:
            resp = client.post(
                "/echo",
                content=b"hello",
                headers={"Content-Length": "-1"},
            )
            assert resp.status_code == 413


class TestPayloadSizeLimitErrorEnvelope:
    """The engine-specific envelope shape: error.type/message/request_id."""

    def test_malformed_content_length_envelope_shape(self) -> None:
        app = _payload_app(max_bytes=1000)
        with TestClient(app) as client:
            resp = client.post(
                "/echo",
                content=b"hello",
                headers={"Content-Length": "garbage"},
            )
        error = resp.json()["error"]
        assert error["type"] == "request_error"
        assert error["message"] == "Invalid Content-Length header"
        assert isinstance(error["request_id"], str) and error["request_id"]

    def test_oversized_envelope_shape(self) -> None:
        app = _payload_app(max_bytes=10)
        with TestClient(app) as client:
            resp = client.post(
                "/echo",
                content=b"x" * 20,
                headers={"Content-Length": "20"},
            )
        error = resp.json()["error"]
        assert error["type"] == "payload_error"
        assert error["code"] == "PAYLOAD_TOO_LARGE"
        assert isinstance(error["request_id"], str) and error["request_id"]
