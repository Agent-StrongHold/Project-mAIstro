"""/v1/capabilities/self-repair API (SPEC-188)."""

from __future__ import annotations

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
    from services.engine import get_engine

    from maistro.capabilities.bootstrap import default_capability_registry
    from maistro.capabilities.http_client import HttpxAsyncHttp
    from maistro.capabilities.providers.host_health import HostHealthAction, HostHealthMonitor
    from maistro.capabilities.providers.self_repair import RuleBasedRepair

    def handler(request: httpx.Request) -> httpx.Response:
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
    reg.register(RuleBasedRepair(infra_monitor=mon, infra_action=act, autonomy="auto_safe"))

    engine = get_engine()
    saved = engine._capabilities
    engine._capabilities = reg
    return engine, saved


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


def test_run_executes_cycle_and_proposals_reflect_it() -> None:
    engine, saved = _wire_self_repair()
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
