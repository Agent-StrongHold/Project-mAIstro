"""/v1/capabilities API: list, discover, toggle, and the approval-gate flow (SPEC-184/187)."""

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

    uid = f"caproute-{task_id}"
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


# --- listing ------------------------------------------------------------


def test_list_capabilities_shows_canonical_slots() -> None:
    c = _login()
    r = c.get("/v1/capabilities")
    assert r.status_code == 200, r.text
    slots = {s["slot"]: s for s in r.json()["slots"]}
    assert {"infra_monitor", "infra_action", "approval"} <= set(slots)
    # approval ships the inbox baseline.
    assert any(p["name"] == "inbox" for p in slots["approval"]["providers"])


# --- toggle / activate (gated) ------------------------------------------


def test_patch_capability_requires_config_write() -> None:
    c = _login()  # plain user, no config.write + no elevation
    r = c.patch("/v1/capabilities/approval", json={"enabled": False})
    assert r.status_code == 403


def test_patch_capability_activates_and_persists() -> None:
    c = _config_writer("cap-route-1")
    r = c.patch("/v1/capabilities/approval", json={"active_provider": "inbox", "enabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["active_provider"] == "inbox"

    # Persisted into settings so it survives a restart.
    from services import settings_store

    assert settings_store.current().capabilities["approval"].active_provider == "inbox"


def test_patch_unknown_slot_404() -> None:
    c = _config_writer("cap-route-2")
    r = c.patch("/v1/capabilities/not_a_slot", json={"enabled": True})
    assert r.status_code == 404


def test_patch_uninstalled_provider_400() -> None:
    c = _config_writer("cap-route-3")
    r = c.patch("/v1/capabilities/infra_action", json={"active_provider": "host_health"})
    assert r.status_code == 400  # host_health not wired in test mode


def test_discover_returns_registered_count() -> None:
    c = _config_writer("cap-route-4")
    r = c.post("/v1/capabilities/discover", json={})
    assert r.status_code == 200, r.text
    assert "registered" in r.json()
    assert isinstance(r.json()["slots"], list)


# --- approval inbox -----------------------------------------------------


def test_list_approvals_empty_by_default() -> None:
    c = _login()
    r = c.get("/v1/capabilities/approvals")
    assert r.status_code == 200
    assert r.json()["pending"] == []


def test_resolve_unknown_approval_404() -> None:
    c = _config_writer("cap-route-5")
    r = c.post("/v1/capabilities/approvals/does-not-exist", json={"approved": True})
    assert r.status_code == 404


# --- the headline acceptance criterion ---------------------------------


async def test_destructive_action_blocks_until_approved_then_completes() -> None:
    """A destructive infra_action is held pending approval, surfaces in the
    approvals inbox, and only completes once resolved through the API."""
    from routes import capabilities as cap_routes
    from services.engine import get_engine

    from maistro.capabilities.bootstrap import default_capability_registry
    from maistro.capabilities.http_client import HttpxAsyncHttp
    from maistro.capabilities.providers.host_health import HostHealthAction

    reg = default_capability_registry()
    inbox = reg.provider("approval", "inbox")
    http = HttpxAsyncHttp(
        "http://h:8150",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"status": "ok", "detail": "restarted"})
        ),
    )
    action = HostHealthAction(http, autonomy="auto_safe", approval=inbox)
    reg.register(action)
    reg.activate("infra_action", "host_health")

    engine = get_engine()
    saved = engine._capabilities
    engine._capabilities = reg
    try:
        task = asyncio.create_task(action.act("restart_stack", {}))  # DESTRUCTIVE tier

        # The action is parked awaiting approval; it shows up in the inbox.
        for _ in range(100):
            if cap_routes.list_approvals()["pending"]:
                break
            await asyncio.sleep(0.005)
        pending = cap_routes.list_approvals()["pending"]
        assert len(pending) == 1
        assert pending[0]["tier"] == "destructive"
        assert not task.done()  # still blocked

        out = cap_routes.resolve_approval(
            pending[0]["request_id"],
            cap_routes.ResolveApprovalBody(approved=True, actor="tester"),
        )
        assert out["resolved"] is True

        result = await asyncio.wait_for(task, timeout=1.0)
        assert result.ok is True
        assert cap_routes.list_approvals()["pending"] == []
    finally:
        engine._capabilities = saved


async def test_destructive_action_denied_does_not_execute() -> None:
    from routes import capabilities as cap_routes
    from services.engine import get_engine

    from maistro.capabilities.bootstrap import default_capability_registry
    from maistro.capabilities.http_client import HttpxAsyncHttp
    from maistro.capabilities.providers.host_health import HostHealthAction

    reg = default_capability_registry()
    inbox = reg.provider("approval", "inbox")
    executed: list[str] = []

    def _handler(req: httpx.Request) -> httpx.Response:
        executed.append(str(req.url))
        return httpx.Response(200, json={"status": "ok"})

    http = HttpxAsyncHttp("http://h:8150", transport=httpx.MockTransport(_handler))
    action = HostHealthAction(http, autonomy="auto_safe", approval=inbox)
    reg.register(action)

    engine = get_engine()
    saved = engine._capabilities
    engine._capabilities = reg
    try:
        task = asyncio.create_task(action.act("docker_prune", {}))  # DESTRUCTIVE
        for _ in range(100):
            if cap_routes.list_approvals()["pending"]:
                break
            await asyncio.sleep(0.005)
        rid = cap_routes.list_approvals()["pending"][0]["request_id"]
        cap_routes.resolve_approval(rid, cap_routes.ResolveApprovalBody(approved=False))
        result = await asyncio.wait_for(task, timeout=1.0)
        assert result.ok is False
        assert result.blocked_pending_approval is True
        assert executed == []  # the host action was never sent
    finally:
        engine._capabilities = saved
