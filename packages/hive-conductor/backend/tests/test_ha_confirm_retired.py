"""The process-local Home Assistant confirmation store is retired (#48).

`services.ha_tools` used to hold approvals in module-level dicts, answered via
`/v1/confirms/{id}/respond` -- a route any authenticated user could reach and
that wrote Home Assistant state. Nothing in production ever produced a confirm
or imported the module, so it is deleted, and the owner decision on #48 is one
approval model: human-required work is a waiting human NodeRun answered
through `/v1/hitl`. These tests pin that the parallel routes stay unmounted.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from starlette.testclient import TestClient

_RETIRED = [
    ("GET", "/v1/confirms"),
    ("GET", "/v1/confirms/pending"),
    ("POST", "/v1/confirms/x/respond"),
]


def _client(monkeypatch: pytest.MonkeyPatch, static_dir: Path) -> TestClient:
    main = importlib.import_module("main")
    monkeypatch.setattr(main, "STATIC_DIR", static_dir)
    client = TestClient(main.create_app())
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200
    return client


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    # No SPA catch-all: an unregistered path must answer 404, not the fallback.
    return _client(monkeypatch, tmp_path / "no-dist")


@pytest.fixture
def shipped_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    # The Docker image always ships `frontend/dist`, so production registers
    # the GET-only SPA catch-all. It answers GET under /v1/ with a JSON 404;
    # any other method matches its path with the wrong method: 405.
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>")
    return _client(monkeypatch, dist)


@pytest.mark.parametrize(("method", "path"), _RETIRED)
def test_confirm_routes_are_not_mounted(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, json={"response": "approved"})

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [(method, path, 404 if method == "GET" else 405) for method, path in _RETIRED],
)
def test_confirm_routes_are_not_served_with_the_shipped_spa(
    shipped_client: TestClient, method: str, path: str, status: int
) -> None:
    response = shipped_client.request(method, path, json={"response": "approved"})

    assert response.status_code == status
    assert response.json() == {"detail": "Not Found" if status == 404 else "Method Not Allowed"}


def test_no_route_is_registered_under_confirms() -> None:
    main = importlib.import_module("main")

    paths = [getattr(route, "path", "") for route in main.create_app().routes]

    assert not [path for path in paths if path.startswith("/v1/confirms")]
