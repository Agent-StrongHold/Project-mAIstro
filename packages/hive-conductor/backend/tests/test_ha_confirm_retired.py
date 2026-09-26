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


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    main = importlib.import_module("main")
    # No SPA catch-all: an unregistered path must answer 404, not the fallback.
    monkeypatch.setattr(main, "STATIC_DIR", tmp_path / "no-dist")
    client = TestClient(main.create_app())
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200
    return client


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/confirms"),
        ("GET", "/v1/confirms/pending"),
        ("POST", "/v1/confirms/x/respond"),
    ],
)
def test_confirm_routes_are_not_mounted(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, json={"response": "approved"})

    assert response.status_code == 404
