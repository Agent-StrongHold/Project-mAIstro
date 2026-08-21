"""PM fleet agents API tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from maistro.config.settings import Settings, get_settings
from maistro_server.main import app


@pytest.fixture
def pm_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("MAISTRO_POC_MODE", "pm")
    settings = Settings(
        api_keys=["alice:secret-alice", "bob:secret-bob"],
        require_auth=False,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_pm_agents_returns_six(pm_client: TestClient) -> None:
    response = pm_client.get(
        "/v1/maistro/agents",
        headers={"Authorization": "Bearer secret-alice"},
    )
    assert response.status_code == 200
    agents = response.json()["agents"]
    assert len(agents) == 6
    ids = {a["id"] for a in agents}
    assert ids == {
        "intake",
        "program_manager",
        "delivery",
        "risk_dependency",
        "reporting",
        "research",
    }


def test_invoke_creates_scoped_task(pm_client: TestClient) -> None:
    create = pm_client.post(
        "/v1/maistro/agents/intake/invoke",
        headers={"Authorization": "Bearer secret-alice"},
        json={"capability": "create_initiative", "payload": {"title": "Q3 Platform"}},
    )
    assert create.status_code == 202
    task_id = create.json()["task_id"]

    alice_get = pm_client.get(
        f"/tasks/{task_id}",
        headers={"Authorization": "Bearer secret-alice"},
    )
    assert alice_get.status_code == 200
    assert alice_get.json()["user_id"] == "alice"

    bob_get = pm_client.get(
        f"/tasks/{task_id}",
        headers={"Authorization": "Bearer secret-bob"},
    )
    assert bob_get.status_code == 404


def test_pm_mode_disabled_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAISTRO_POC_MODE", raising=False)
    client = TestClient(app)
    response = client.get("/v1/maistro/agents")
    assert response.status_code == 404
