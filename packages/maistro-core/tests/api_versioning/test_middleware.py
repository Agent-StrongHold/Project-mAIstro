"""ADR-076 negotiation semantics at the mechanism level.

The middleware is shared by maistro-server and hive-conductor, so the
contract lives here: selector forms and their precedence, the advertised
default, 406/400 on bad selectors, the Accept-conditional media-type
rewrite (and the canvas vendor-type carve-out), deprecation signalling,
and the body cache-and-replay that keeps downstream consumers seeing the
same bytes.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from starlette.testclient import TestClient

from maistro.api_versioning import (
    API_VERSIONS,
    DEFAULT_API_VERSION,
    ApiVersion,
    VersionNegotiationMiddleware,
    negotiated_api_version,
)

PATHS_SKIPPED = ("/health", "/metrics", "/docs", "/openapi.json", "/a2a")


def _client(
    versions: dict[int, ApiVersion] | None = None,
    default_version: int = 1,
    skip_prefixes: tuple[str, ...] = PATHS_SKIPPED,
    body_cache_cap_bytes: int = 1_048_576,
    handler: Any = None,
) -> TestClient:
    """A minimal ASGI app (one echo route) behind the negotiation middleware."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if handler is not None:
            await handler(scope, receive, send)
            return
        path = scope["path"]
        body = b""
        if scope["method"] in ("POST", "PUT", "PATCH"):
            while True:
                message = await receive()
                if message["type"] == "http.request":
                    body += message.get("body", b"")
                if not message.get("more_body"):
                    break
        payload = json.dumps({"path": path, "body": body.decode("latin-1")}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": payload})

    wrapped: Any = VersionNegotiationMiddleware(
        app,
        versions=versions,
        default_version=default_version,
        skip_prefixes=skip_prefixes,
        body_cache_cap_bytes=body_cache_cap_bytes,
    )

    # Expose the wrapped stack through FastAPI-free Starlette routing so the
    # TestClient can drive it; a bare Mount keeps this mechanism-level.
    from starlette.applications import Starlette
    from starlette.routing import Mount

    return TestClient(Starlette(routes=[Mount("/", app=wrapped)]))


@pytest.mark.ac("ADR-076/AC-4")
@pytest.mark.contract("boundary")
def test_no_selector_serves_the_default_and_advertises_it() -> None:
    response = _client().get("/v1/tasks")
    assert response.status_code == 200
    assert response.headers["maistro-api-version"] == "1"
    assert response.headers["maistro-api-default"] == "1"
    # A silent client keeps plain JSON; the version lives in headers.
    assert response.headers["content-type"] == "application/json"


@pytest.mark.ac("ADR-076/AC-3")
@pytest.mark.contract("boundary")
def test_additive_change_ships_within_version_1_without_breaking_silent_clients() -> None:
    """AC-3 exercised by this change itself: negotiation shipped within version 1.

    The version table still advertises exactly one, non-deprecated version, and
    a client that predates the negotiation layer entirely (no Accept media
    type, no query/body selector) keeps the exact pre-change response shape:
    200, plain ``application/json``, no deprecation signalling.
    """

    assert set(API_VERSIONS) == {1}
    assert DEFAULT_API_VERSION == 1
    assert not API_VERSIONS[1].deprecated
    response = _client().get("/v1/tasks")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert "deprecation" not in response.headers


@pytest.mark.contract("boundary")
def test_accept_media_type_selects_the_version_and_rewrites_the_content_type() -> None:
    response = _client().get("/v1/tasks", headers={"Accept": "application/vnd.maistro.v1"})
    assert response.status_code == 200
    assert response.headers["maistro-api-version"] == "1"
    assert response.headers["content-type"] == "application/vnd.maistro.v1+json"


def test_accept_media_type_with_json_suffix_and_parameters() -> None:
    response = _client().get(
        "/v1/tasks",
        headers={"Accept": "application/vnd.maistro.v1+json;q=0.9, application/json"},
    )
    assert response.status_code == 200
    assert response.headers["maistro-api-version"] == "1"
    assert response.headers["content-type"].startswith("application/vnd.maistro.v1+json")


@pytest.mark.contract("boundary")
def test_query_parameter_selects_the_version_without_rewriting_the_content_type() -> None:
    response = _client().get("/v1/tasks?api_version=1")
    assert response.status_code == 200
    assert response.headers["maistro-api-version"] == "1"
    assert response.headers["content-type"] == "application/json"


@pytest.mark.contract("boundary")
def test_body_field_selects_the_version_and_the_handler_still_sees_the_body() -> None:
    response = _client().post("/v1/tasks", json={"api_version": 1, "title": "hello"})
    assert response.status_code == 200
    assert response.headers["maistro-api-version"] == "1"
    assert response.headers["content-type"] == "application/json"
    # The replay handed the route the same bytes a client sent.
    assert json.loads(json.loads(response.text)["body"]) == {
        "api_version": 1,
        "title": "hello",
    }


@pytest.mark.ac("ADR-076/AC-1")
@pytest.mark.ac("ADR-076/AC-2")
@pytest.mark.contract("boundary")
def test_all_selector_forms_resolve_to_the_same_version() -> None:
    client = _client()
    header_form = client.get("/v1/tasks", headers={"Accept": "application/vnd.maistro.v1"})
    query_form = client.get("/v1/tasks?api_version=1")
    body_form = client.post("/v1/tasks", json={"api_version": 1})
    for response in (header_form, query_form, body_form):
        assert response.status_code == 200
        assert response.headers["maistro-api-version"] == "1"


@pytest.mark.contract("boundary")
def test_precedence_accept_over_query_over_body() -> None:
    assert negotiated_api_version(
        "application/vnd.maistro.v1", b"api_version=1", b"{}", API_VERSIONS, 1
    ) == (1, None, "accept")
    assert negotiated_api_version(
        None, b"api_version=1", b'{"api_version": 1}', API_VERSIONS, 1
    ) == (1, None, "query")
    assert negotiated_api_version(None, b"", b'{"api_version": 1}', API_VERSIONS, 1) == (
        1,
        None,
        "body",
    )
    # None of the forms being present means "no selector", not "the default".
    assert negotiated_api_version(None, b"", b"{}", API_VERSIONS, 1) == (None, None, None)


@pytest.mark.contract("boundary")
def test_unsupported_accept_version_is_not_acceptable() -> None:
    response = _client().get("/v1/tasks", headers={"Accept": "application/vnd.maistro.v9"})
    assert response.status_code == 406
    assert "supported: 1" in response.json()["detail"]


def test_unsupported_query_version_is_not_acceptable() -> None:
    response = _client().get("/v1/tasks?api_version=2")
    assert response.status_code == 406
    assert "supported: 1" in response.json()["detail"]


def test_non_integer_query_selector_is_a_bad_request() -> None:
    response = _client().get("/v1/tasks?api_version=one")
    assert response.status_code == 400


def test_non_integer_body_selector_is_a_bad_request() -> None:
    response = _client().post("/v1/tasks", json={"api_version": "soon"})
    assert response.status_code == 400


def test_malformed_maistro_media_type_is_not_acceptable() -> None:
    response = _client().get("/v1/tasks", headers={"Accept": "application/vnd.maistro.vnext"})
    assert response.status_code == 406


@pytest.mark.contract("boundary")
def test_vendor_content_type_is_not_rewritten() -> None:
    """Canvas's media type is that surface's mechanism, not this one."""

    async def vendor_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/vnd.canvas+json;version=2")],
            }
        )
        await send({"type": "http.response.body", "body": b"{}"})

    wrapped: Any = VersionNegotiationMiddleware(
        vendor_app, versions=API_VERSIONS, default_version=1, skip_prefixes=()
    )
    from starlette.applications import Starlette
    from starlette.routing import Mount

    response = TestClient(Starlette(routes=[Mount("/", app=wrapped)])).get(
        "/v2/canvas/designs", headers={"Accept": "application/vnd.maistro.v1"}
    )
    assert response.status_code == 200
    assert response.headers["maistro-api-version"] == "1"
    assert response.headers["content-type"] == "application/vnd.canvas+json;version=2"


def test_skip_prefix_bypasses_negotiation_entirely() -> None:
    response = _client().get("/health", headers={"Accept": "application/vnd.maistro.v9"})
    assert response.status_code == 200
    assert "maistro-api-version" not in response.headers


@pytest.mark.ac("ADR-076/AC-5")
@pytest.mark.contract("boundary")
def test_deprecated_version_signals_deprecation_sunset_and_link() -> None:
    versions = {
        1: ApiVersion(
            number=1,
            deprecated=True,
            sunset="Wed, 30 Sep 2026 00:00:00 GMT",
            migration_link="https://docs.example/migrate-v1-to-v2",
        ),
        2: ApiVersion(number=2),
    }
    response = _client(versions=versions, default_version=2).get(
        "/v1/tasks", headers={"Accept": "application/vnd.maistro.v1"}
    )
    assert response.status_code == 200
    assert response.headers["deprecation"] == "true"
    assert response.headers["sunset"] == "Wed, 30 Sep 2026 00:00:00 GMT"
    assert response.headers["link"] == '<https://docs.example/migrate-v1-to-v2>; rel="deprecation"'
    assert response.headers["maistro-api-version"] == "1"


def test_body_over_the_cache_cap_still_reaches_the_handler_intact() -> None:
    payload = {"blob": "x" * 64}
    response = _client(body_cache_cap_bytes=16).post("/v1/tasks", json=payload)
    assert response.status_code == 200
    # Body form did not resolve (no selector), the default served, and the
    # route got every byte.
    assert response.headers["maistro-api-version"] == "1"
    assert response.headers["content-type"] == "application/json"
    assert json.loads(json.loads(response.text)["body"]) == payload


def test_non_json_body_is_never_a_selector() -> None:
    response = _client().post(
        "/v1/tasks",
        content=b"api_version=1",
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 200
    assert response.headers["maistro-api-version"] == "1"


async def test_non_http_scope_passes_through_untouched() -> None:
    seen: dict[str, Any] = {}

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        seen["scope"] = scope

    wrapped: Any = VersionNegotiationMiddleware(app)
    scope = {"type": "websocket", "path": "/v1/ws", "headers": []}

    async def receive() -> dict[str, Any]:  # pragma: no cover - never awaited
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:  # pragma: no cover
        return None

    await wrapped(scope, receive, send)
    assert seen["scope"] is scope
