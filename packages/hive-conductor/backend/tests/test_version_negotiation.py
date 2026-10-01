"""ADR-076 negotiation against the live hive-conductor route table.

The middleware is shared with maistro-server (``maistro.api_versioning`` owns
the mechanism tests); these prove the conductor wiring: the stable ``/v1``
mount negotiates, the default is advertised on ordinary and authenticated-out
responses alike, an unsupported selector short-circuits before auth, and the
security-headers outermost layer still wraps negotiation rejections.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_ordinary_requests_are_advertised_as_version_1(client: TestClient) -> None:
    response = client.get("/v1/setup/status")
    assert response.status_code == 200
    assert response.headers["maistro-api-version"] == "1"
    assert response.headers["maistro-api-default"] == "1"
    assert response.headers["content-type"] == "application/json"


def test_accept_media_type_selects_the_version_on_a_business_route(
    client: TestClient,
) -> None:
    response = client.get("/v1/setup/status", headers={"Accept": "application/vnd.maistro.v1"})
    assert response.status_code == 200
    assert response.headers["maistro-api-version"] == "1"
    assert response.headers["content-type"] == "application/vnd.maistro.v1+json"


def test_query_parameter_selects_the_version(client: TestClient) -> None:
    response = client.get("/v1/setup/status?api_version=1")
    assert response.status_code == 200
    assert response.headers["maistro-api-version"] == "1"
    assert response.headers["content-type"] == "application/json"


def test_body_field_selects_the_version_and_login_still_sees_its_payload(
    client: TestClient,
) -> None:
    # /v1/auth/login is public and reads the JSON body; a lossy replay would
    # surface as a 422 before auth ever answered 401.
    response = client.post(
        "/v1/auth/login",
        json={"api_version": 1, "username": "nobody", "password": "wrong"},
    )
    assert response.status_code in (401, 403)
    assert response.headers["maistro-api-version"] == "1"


def test_selector_forms_agree_on_the_negotiated_version(client: TestClient) -> None:
    accept = client.get("/v1/setup/status", headers={"Accept": "application/vnd.maistro.v1"})
    query = client.get("/v1/setup/status?api_version=1")
    for response in (accept, query):
        assert response.headers["maistro-api-version"] == "1"


def test_unsupported_version_short_circuits_before_auth(client: TestClient) -> None:
    # /v1/backlog requires a session; the 406 must answer before auth does.
    response = client.get("/v1/backlog", headers={"Accept": "application/vnd.maistro.v9"})
    assert response.status_code == 406
    assert "supported: 1" in response.json()["detail"]


def test_negotiation_rejections_still_carry_security_headers(
    client: TestClient,
) -> None:
    # SecurityHeaders stays the outermost layer, so even a 406 carries the
    # header set.
    response = client.get("/v1/backlog", headers={"Accept": "application/vnd.maistro.v9"})
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_non_integer_query_selector_is_a_bad_request(client: TestClient) -> None:
    response = client.get("/v1/setup/status?api_version=latest")
    assert response.status_code == 400


def test_infrastructure_paths_do_not_negotiate(client: TestClient) -> None:
    response = client.get("/health", headers={"Accept": "application/vnd.maistro.v9"})
    assert response.status_code == 200
    assert "maistro-api-version" not in response.headers
