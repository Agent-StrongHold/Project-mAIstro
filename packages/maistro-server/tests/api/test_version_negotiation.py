"""ADR-076 negotiation against the live maistro-server route table.

The core middleware (``maistro.api_versioning``) owns the mechanism tests;
these prove the app wiring: every business route under the stable ``/v1``
mount negotiates, the default is advertised on ordinary responses, bad
selectors short-circuit before any handler, infrastructure paths are out of
scope, and the body-form selector leaves the request body intact for the
route (the replay must be byte-exact or task creation would see an empty
description).
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from maistro_server.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.ac("ADR-076/AC-4")
def test_ordinary_requests_are_advertised_as_version_1(client: TestClient) -> None:
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert response.headers["maistro-api-version"] == "1"
    assert response.headers["maistro-api-default"] == "1"
    assert response.headers["content-type"] == "application/json"


def test_accept_media_type_selects_the_version_on_a_business_route(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/tasks",
        content=json.dumps(
            {"description": "negotiation probe", "workspace": "/tmp/maistro-workspace/test"}
        ),
        headers={
            "Accept": "application/vnd.maistro.v1",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 202
    assert response.headers["maistro-api-version"] == "1"
    assert response.headers["content-type"] == "application/vnd.maistro.v1+json"
    assert "task_id" in response.json()


def test_query_parameter_selects_the_version(client: TestClient) -> None:
    response = client.get("/v1/models?api_version=1")
    assert response.status_code == 200
    assert response.headers["maistro-api-version"] == "1"
    assert response.headers["content-type"] == "application/json"


def test_body_field_selects_the_version_and_the_route_still_gets_its_body(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/tasks",
        json={
            "api_version": 1,
            "description": "body-form probe",
            "workspace": "/tmp/maistro-workspace/test",
        },
    )
    assert response.status_code == 202
    assert response.headers["maistro-api-version"] == "1"
    # The replay handed the route the real description — an empty or truncated
    # replay would have failed validation instead of creating a task.
    assert response.json()["task_id"]


@pytest.mark.ac("ADR-076/AC-1")
def test_selector_forms_agree_on_the_negotiated_version(client: TestClient) -> None:
    accept = client.get("/v1/models", headers={"Accept": "application/vnd.maistro.v1"})
    query = client.get("/v1/models?api_version=1")
    body = client.post("/v1/models", json={"api_version": 1})
    for response in (accept, query, body):
        assert response.headers["maistro-api-version"] == "1"


@pytest.mark.ac("ADR-076/AC-2")
def test_business_routes_have_no_path_version_twins(client: TestClient) -> None:
    """ADR-076 AC-2: the URL space is not forked per version.

    Read from the client-facing OpenAPI table, not the internal router
    objects: no path versioned differently from the stable ``/v1`` mount may
    serve the same resource (a ``/vK`` path whose suffix duplicates a ``/v1``
    route). The canvas ``/v2/canvas`` mount is that surface's own mechanism
    with no ``/v1`` twins, so it satisfies this property rather than being
    special-cased away.
    """

    paths = client.get("/openapi.json").json()["paths"]
    v1_suffixes = {p[len("/v1") :] for p in paths if p.startswith("/v1/")}
    assert v1_suffixes, "the stable /v1 mount is where business routes live"
    for path in paths:
        match = re.fullmatch(r"/v(\d+)(/.*)", path)
        if match is None or match.group(1) == "1":
            continue
        assert match.group(2) not in v1_suffixes, f"{path} duplicates a /v1 route"


def test_unsupported_version_short_circuits_as_not_acceptable(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/tasks",
        json={"description": "never created", "workspace": "/tmp/x"},
        headers={"Accept": "application/vnd.maistro.v9"},
    )
    assert response.status_code == 406
    assert "supported: 1" in response.json()["detail"]


def test_non_integer_query_selector_is_a_bad_request(client: TestClient) -> None:
    response = client.get("/v1/models?api_version=latest")
    assert response.status_code == 400


def test_non_integer_body_selector_is_a_bad_request(client: TestClient) -> None:
    response = client.post("/v1/models", json={"api_version": "v1"})
    assert response.status_code == 400


def test_infrastructure_paths_do_not_negotiate(client: TestClient) -> None:
    response = client.get("/health", headers={"Accept": "application/vnd.maistro.v9"})
    assert response.status_code == 200
    assert "maistro-api-version" not in response.headers


def test_a2a_paths_do_not_negotiate(client: TestClient) -> None:
    # A2A versioning is out of ADR-076's scope; a bad selector there must not
    # turn into a negotiation error.
    response = client.post(
        "/a2a",
        json={"jsonrpc": "2.0", "method": "ping"},
        headers={"Accept": "application/vnd.maistro.v9"},
    )
    assert response.status_code != 406
    assert "maistro-api-version" not in response.headers
