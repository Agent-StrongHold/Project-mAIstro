"""Route-level coverage for routes/agents.py.

Two distinct behavioural modes gate almost every handler:
  - normal mode (default, `is_pm_poc_mode()` False): full CRUD against
    `stores.agents`.
  - PM POC mode (`is_pm_poc_mode()` True): the roster is read-only and
    derived from `list_pm_agents`; create/update/delete/forge are 403.

Both modes are exercised explicitly by monkeypatching
`routes.agents.is_pm_poc_mode` rather than the environment variable, so
tests don't leak global os.environ state between each other.
"""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import stores  # noqa: E402
from models.schemas import Agent  # noqa: E402


def _clear(store) -> None:
    for key in list(store.keys()):
        store.pop(key, None)


@pytest.fixture(autouse=True)
def _clear_agents():
    _clear(stores.agents)
    yield
    _clear(stores.agents)


def _make_agent(aid: str = "a1", name: str = "Agent One") -> Agent:
    t = datetime.now(UTC)
    return Agent(
        id=aid,
        name=name,
        description="desc",
        model="gpt-4.1",
        status="idle",
        capabilities=["x"],
        skills=[],
        current_mission=None,
        tasks_completed=0,
        avg_response_time_ms=0.0,
        last_active=t,
        created_at=t,
        config={},
    )


# --------------------------------------------------------------------------- #
# Normal (non-PM-POC) mode — full CRUD against stores.agents
# --------------------------------------------------------------------------- #


def test_list_agents_normal_mode_returns_store_contents(authed_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: False)
    stores.agents["a1"] = _make_agent()
    r = authed_client.get("/v1/agents")
    assert r.status_code == 200
    assert [a["id"] for a in r.json()] == ["a1"]


def test_get_agent_normal_mode_found(authed_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: False)
    stores.agents["a1"] = _make_agent()
    r = authed_client.get("/v1/agents/a1")
    assert r.status_code == 200
    assert r.json()["id"] == "a1"


def test_get_agent_normal_mode_missing_404(authed_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: False)
    r = authed_client.get("/v1/agents/missing")
    assert r.status_code == 404
    assert r.json()["detail"] == "agent not found"


def test_create_agent_normal_mode(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: False)
    r = admin_client.post(
        "/v1/agents",
        json={"name": "New Agent", "description": "d", "model": "gpt-4.1", "capabilities": ["c"]},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "New Agent"
    assert body["status"] == "idle"
    assert body["id"] in stores.agents


def test_create_agent_pm_poc_mode_403(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: True)
    r = admin_client.post("/v1/agents", json={"name": "x"})
    assert r.status_code == 403
    assert r.json()["detail"] == "PM fleet is read-only in POC mode"


def test_update_agent_normal_mode(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: False)
    stores.agents["a1"] = _make_agent()
    r = admin_client.put("/v1/agents/a1", json={"name": "Renamed"})
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"
    assert stores.agents["a1"].name == "Renamed"


def test_update_agent_normal_mode_missing_404(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: False)
    r = admin_client.put("/v1/agents/missing", json={"name": "x"})
    assert r.status_code == 404


def test_update_agent_pm_poc_mode_403(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: True)
    r = admin_client.put("/v1/agents/a1", json={"name": "x"})
    assert r.status_code == 403


def test_delete_agent_normal_mode(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: False)
    stores.agents["a1"] = _make_agent()
    r = admin_client.delete("/v1/agents/a1")
    assert r.status_code == 204
    assert "a1" not in stores.agents


def test_delete_agent_normal_mode_missing_404(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: False)
    r = admin_client.delete("/v1/agents/missing")
    assert r.status_code == 404


def test_delete_agent_pm_poc_mode_403(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: True)
    r = admin_client.delete("/v1/agents/a1")
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# /scan
# --------------------------------------------------------------------------- #


def test_scan_agent_normal_mode_found(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: False)
    stores.agents["a1"] = _make_agent()
    r = admin_client.post("/v1/agents/a1/scan")
    assert r.status_code == 200
    assert r.json() == {"findings": [], "status": "clean"}


def test_scan_agent_normal_mode_missing_404(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: False)
    r = admin_client.post("/v1/agents/missing/scan")
    assert r.status_code == 404


def test_scan_agent_pm_poc_mode_found(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: True)
    monkeypatch.setattr(
        "maistro.agents.pm_fleet.get_pm_def",
        lambda aid: {"id": aid},
    )
    r = admin_client.post("/v1/agents/pm-1/scan")
    assert r.status_code == 200
    assert r.json() == {"findings": [], "status": "clean"}


def test_scan_agent_pm_poc_mode_missing_404(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: True)
    monkeypatch.setattr("maistro.agents.pm_fleet.get_pm_def", lambda aid: None)
    r = admin_client.post("/v1/agents/no-such-pm/scan")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# /forge
# --------------------------------------------------------------------------- #


def test_forge_agent_normal_mode(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: False)
    r = admin_client.post("/v1/agents/forge", json={"description": "do stuff"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"].startswith("forge-")
    assert body["config"]["strategy"] == "react"
    assert body["config"]["role"] == "worker"
    assert body["id"] in stores.agents


def test_forge_agent_custom_strategy(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: False)
    r = admin_client.post(
        "/v1/agents/forge", json={"description": "do stuff", "strategy": "plan-execute"}
    )
    assert r.json()["config"]["strategy"] == "plan-execute"


def test_forge_agent_pm_poc_mode_403(admin_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: True)
    r = admin_client.post("/v1/agents/forge", json={"description": "x"})
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# PM POC mode list/get — derived from list_pm_agents
# --------------------------------------------------------------------------- #


def test_list_agents_pm_poc_mode_delegates(authed_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: True)

    sentinel_agent = _make_agent(aid="pm-1", name="PM One")
    monkeypatch.setattr("routes.agents.get_engine", lambda: _FakeEngine([]))
    monkeypatch.setattr("routes.agents.list_pm_agents", lambda tasks, user_id="": [sentinel_agent])

    r = authed_client.get("/v1/agents")
    assert r.status_code == 200
    assert [a["id"] for a in r.json()] == ["pm-1"]


def test_get_agent_pm_poc_mode_found(authed_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: True)
    sentinel_agent = _make_agent(aid="pm-1", name="PM One")
    monkeypatch.setattr("routes.agents.get_engine", lambda: _FakeEngine([]))
    monkeypatch.setattr("routes.agents.list_pm_agents", lambda tasks, user_id="": [sentinel_agent])

    r = authed_client.get("/v1/agents/pm-1")
    assert r.status_code == 200
    assert r.json()["id"] == "pm-1"


def test_get_agent_pm_poc_mode_missing_404(authed_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: True)
    monkeypatch.setattr("routes.agents.get_engine", lambda: _FakeEngine([]))
    monkeypatch.setattr("routes.agents.list_pm_agents", lambda tasks, user_id="": [])

    r = authed_client.get("/v1/agents/no-such-pm")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# /invoke
# --------------------------------------------------------------------------- #


def test_invoke_agent_not_pm_poc_mode_404(authed_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: False)
    r = authed_client.post("/v1/agents/a1/invoke", json={"capability": "poll_jira"})
    assert r.status_code == 404
    assert r.json()["detail"] == "Agent invoke only available in PM POC mode"


def test_invoke_agent_gated_capability_403(authed_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: True)
    r = authed_client.post("/v1/agents/a1/invoke", json={"capability": "create_epic"})
    assert r.status_code == 403
    assert "create_epic" in r.json()["detail"]
    assert "epic" in r.json()["detail"]


def test_invoke_agent_autonomous_capability_executes(authed_client: Any, monkeypatch) -> None:
    monkeypatch.setattr("routes.agents.is_pm_poc_mode", lambda: True)

    async def fake_execute(capability, payload, uid):
        assert capability == "poll_jira"
        assert payload == {"sprint": 1}
        return {"issues": []}

    monkeypatch.setattr("services.chat_completion._execute_tool", fake_execute)
    logged: list[dict] = []
    monkeypatch.setattr(
        "routes.agents.log_audit",
        lambda action, actor, target=None, detail=None, severity="info": logged.append(
            {"action": action, "actor": actor, "target": target, "detail": detail}
        ),
    )

    r = authed_client.post(
        "/v1/agents/a1/invoke", json={"capability": "poll_jira", "payload": {"sprint": 1}}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["capability"] == "poll_jira"
    assert body["result"] == {"issues": []}
    assert logged[0]["action"] == "agent_invoke"
    assert logged[0]["target"] == "a1"
    assert logged[0]["detail"]["result_keys"] == ["issues"]


class _FakeEngine:
    def __init__(self, tasks: list) -> None:
        self._tasks = tasks

    def list_tasks(self, user_id: str = "") -> list:
        return self._tasks
