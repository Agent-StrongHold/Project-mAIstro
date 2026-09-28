"""/v1/capabilities/self-repair API (SPEC-188)."""

from __future__ import annotations

import asyncio

import httpx
from fastapi.testclient import TestClient
from main import app


def _login(username: str = "testuser", password: str = "testpass") -> TestClient:
    c = TestClient(app)
    r = c.post("/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c


def _config_writer(task_id: str) -> TestClient:
    from datetime import UTC, datetime

    import stores

    from maistro.security.passwords import hash_password

    uid = f"srroute-{task_id}"
    stores.users[uid] = stores.users._model_class(
        id=uid,
        username=uid,
        password_hash=hash_password("pw"),
        role="user",
        is_active=True,
        permissions=["config.write"],
        created_at=datetime.now(UTC),
    )
    c = TestClient(app)
    assert c.post("/v1/auth/login", json={"username": uid, "password": "pw"}).status_code == 200
    e = c.post(
        "/v1/auth/elevate",
        json={"password": "pw", "permissions": ["config.write"], "task_id": task_id},
    )
    assert e.status_code == 200, e.text
    return c


def _wire_self_repair():
    """Swap the engine registry for one with a host_health-backed self_repair provider."""
    calls: list[str] = []
    from config import Settings
    from services.capabilities_wiring import _register_self_repair
    from services.engine import get_engine

    from maistro.capabilities.bootstrap import default_capability_registry
    from maistro.capabilities.effect_context import binding_scope_policy, new_effect_context
    from maistro.capabilities.http_client import HttpxAsyncHttp
    from maistro.capabilities.providers.host_health import HostHealthAction, HostHealthMonitor

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/full":
            return httpx.Response(
                200,
                json={
                    "timestamp": "t",
                    "docker": {
                        "unhealthy": ["litellm"],
                        "containers": [
                            {"name": "litellm", "status": "Up 2h (unhealthy)", "healthy": False}
                        ],
                    },
                },
            )
        return httpx.Response(200, json={"status": "ok", "detail": "done"})

    http = HttpxAsyncHttp("http://h:8150", transport=httpx.MockTransport(handler))
    reg = default_capability_registry()
    inbox = reg.provider("approval", "inbox")
    mon = HostHealthMonitor(http)
    act = HostHealthAction(http, autonomy="auto_safe", approval=inbox)
    reg.register(mon)
    reg.register(act)

    effects = new_effect_context(policy_evaluator=binding_scope_policy)
    _register_self_repair(reg, Settings(infra_autonomy="auto_safe"), effects)

    engine = get_engine()
    saved = engine._capabilities
    engine._capabilities = reg
    return engine, saved, calls, effects


def test_proposals_empty_when_no_provider() -> None:
    c = _login()
    r = c.get("/v1/capabilities/self-repair/proposals")
    assert r.status_code == 200
    assert r.json()["proposals"] == []


def test_run_requires_config_write() -> None:
    c = _login()  # plain user
    r = c.post("/v1/capabilities/self-repair/run")
    assert r.status_code == 403


def test_run_503_when_no_provider() -> None:
    c = _config_writer("sr-noprov")
    r = c.post("/v1/capabilities/self-repair/run")
    assert r.status_code == 503


def test_disable_infra_action_after_repair_initialization_blocks_effect() -> None:
    engine, saved, calls, _effects = _wire_self_repair()
    try:
        engine.capabilities.set_enabled("infra_action", False)
        c = _config_writer("sr-disabled")

        response = c.post("/v1/capabilities/self-repair/run")

        assert response.status_code == 200, response.text
        assert "/full" in calls
        assert not any(path.startswith("/action/") for path in calls)
        proposal = response.json()["proposals"][0]
        assert proposal["decision"] == "failed"
        assert "unavailable" in proposal["detail"]
    finally:
        engine._capabilities = saved


def test_revoke_infra_action_after_repair_initialization_blocks_effect() -> None:
    engine, saved, calls, effects = _wire_self_repair()
    try:
        asyncio.run(effects.bindings.revoke("builtin:self-repair:infra-action"))
        c = _config_writer("sr-revoked")

        response = c.post("/v1/capabilities/self-repair/run")

        assert response.status_code == 200, response.text
        assert "/full" in calls
        assert not any(path.startswith("/action/") for path in calls)
        proposal = response.json()["proposals"][0]
        assert proposal["decision"] == "failed"
        assert "unavailable" in proposal["detail"]
    finally:
        engine._capabilities = saved


def test_run_executes_cycle_and_proposals_reflect_it() -> None:
    engine, saved, _calls, _effects = _wire_self_repair()
    try:
        c = _config_writer("sr-run")
        r = c.post("/v1/capabilities/self-repair/run")
        assert r.status_code == 200, r.text
        body = r.json()
        # docker container down → restart_container proposal, auto-run (reversible/auto_safe)
        resources = [p["resource"] for p in body["proposals"]]
        assert "docker:litellm" in resources
        prop = next(p for p in body["proposals"] if p["resource"] == "docker:litellm")
        assert prop["action"] == "restart_container"
        assert prop["decision"] == "acted"

        # GET reflects the last cycle.
        g = c.get("/v1/capabilities/self-repair/proposals")
        assert any(p["resource"] == "docker:litellm" for p in g.json()["proposals"])
    finally:
        engine._capabilities = saved
