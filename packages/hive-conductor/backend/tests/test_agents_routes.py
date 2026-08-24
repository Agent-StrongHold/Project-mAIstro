"""Route-level coverage for routes/agents.py.

There used to be two behavioural modes here, and almost every handler branched
between them: normal mode did full CRUD against `stores.agents`, while PM POC
mode made the roster read-only, derived it from `list_pm_agents`, and answered
403 to create/update/delete/forge. #129 retired the second, so the tests that
pinned it are gone with it -- along with `POST /{agent_id}/invoke`, whose only
gate it was.

What replaces it is not a third mode. `workspace_id` selects a workspace's own
materialized roster and its absence selects the global one; every handler here
has exactly one behaviour left, which is why nothing below monkeypatches
anything to choose between them.
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
# Full CRUD against stores.agents
# --------------------------------------------------------------------------- #


def test_list_agents_normal_mode_returns_store_contents(authed_client: Any, monkeypatch) -> None:
    stores.agents["a1"] = _make_agent()
    r = authed_client.get("/v1/agents")
    assert r.status_code == 200
    assert [a["id"] for a in r.json()] == ["a1"]


def test_get_agent_normal_mode_found(authed_client: Any, monkeypatch) -> None:
    stores.agents["a1"] = _make_agent()
    r = authed_client.get("/v1/agents/a1")
    assert r.status_code == 200
    assert r.json()["id"] == "a1"


def test_get_agent_normal_mode_missing_404(authed_client: Any, monkeypatch) -> None:
    r = authed_client.get("/v1/agents/missing")
    assert r.status_code == 404
    assert r.json()["detail"] == "agent not found"


def test_create_agent_normal_mode(admin_client: Any, monkeypatch) -> None:
    r = admin_client.post(
        "/v1/agents",
        json={"name": "New Agent", "description": "d", "model": "gpt-4.1", "capabilities": ["c"]},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "New Agent"
    assert body["status"] == "idle"
    assert body["id"] in stores.agents


def test_update_agent_normal_mode(admin_client: Any, monkeypatch) -> None:
    stores.agents["a1"] = _make_agent()
    r = admin_client.put("/v1/agents/a1", json={"name": "Renamed"})
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"
    assert stores.agents["a1"].name == "Renamed"


def test_update_agent_normal_mode_missing_404(admin_client: Any, monkeypatch) -> None:
    r = admin_client.put("/v1/agents/missing", json={"name": "x"})
    assert r.status_code == 404


def test_delete_agent_normal_mode(admin_client: Any, monkeypatch) -> None:
    stores.agents["a1"] = _make_agent()
    r = admin_client.delete("/v1/agents/a1")
    assert r.status_code == 204
    assert "a1" not in stores.agents


def test_delete_agent_normal_mode_missing_404(admin_client: Any, monkeypatch) -> None:
    r = admin_client.delete("/v1/agents/missing")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# /scan
# --------------------------------------------------------------------------- #


def test_scan_agent_normal_mode_found(admin_client: Any, monkeypatch) -> None:
    stores.agents["a1"] = _make_agent()
    r = admin_client.post("/v1/agents/a1/scan")
    assert r.status_code == 200
    assert r.json() == {"findings": [], "status": "clean"}


def test_scan_agent_normal_mode_missing_404(admin_client: Any, monkeypatch) -> None:
    r = admin_client.post("/v1/agents/missing/scan")
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# /forge
# --------------------------------------------------------------------------- #


def test_forge_agent_normal_mode(admin_client: Any, monkeypatch) -> None:
    r = admin_client.post("/v1/agents/forge", json={"description": "do stuff"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"].startswith("forge-")
    assert body["config"]["strategy"] == "react"
    assert body["config"]["role"] == "worker"
    assert body["id"] in stores.agents


def test_forge_agent_custom_strategy(admin_client: Any, monkeypatch) -> None:
    r = admin_client.post(
        "/v1/agents/forge", json={"description": "do stuff", "strategy": "plan-execute"}
    )
    assert r.json()["config"]["strategy"] == "plan-execute"
