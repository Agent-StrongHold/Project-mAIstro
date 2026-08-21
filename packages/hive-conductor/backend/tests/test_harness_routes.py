"""/v1/harness API: inbound harness-session routes (SPEC-208 §5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import routes.harness as harness_mod
from services.engine import get_engine

from maistro.capabilities import HarnessSessionManager
from maistro.capabilities.slots.harness_runner import SLOT_NAME
from maistro.capabilities.types import ProviderHealth
from maistro.security._types import WardenVerdict


class _FakeHarness:
    def __init__(self, *, healthy: bool = True) -> None:
        self._healthy = healthy

    @property
    def name(self) -> str:
        return "fake"

    @property
    def slot(self) -> str:
        return SLOT_NAME

    @property
    def trust_tier(self) -> str:
        return "t2"

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=self._healthy)

    async def start_session(self, agent_spec: Any, *, workdir: str) -> str:
        return "sess-http"

    async def send(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {"role": "assistant", "content": "pong", "actions": []}

    async def stream(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "token", "text": "hi"}

    async def stop(self, session_id: str) -> None:
        return None


class _StubWarden:
    def __init__(self, block_on: str | None = None) -> None:
        self.block_on = block_on

    async def scan(self, content: str, boundary: str) -> WardenVerdict:
        if self.block_on is not None and self.block_on in content:
            return WardenVerdict(clean=False, blocked=True, flags=("injection",))
        return WardenVerdict(clean=True)


def _install_harness(*, warden: Any, healthy: bool = True, enabled: bool = True) -> None:
    reg = get_engine().capabilities
    reg.register(_FakeHarness(healthy=healthy))
    reg.activate(SLOT_NAME, "fake")
    reg.set_enabled(SLOT_NAME, enabled)
    harness_mod._manager = HarnessSessionManager(reg, warden=warden)


def test_start_returns_503_when_no_active_harness(admin_client):
    reg = get_engine().capabilities
    reg.set_enabled(SLOT_NAME, False)  # force SAFE_NOOP fallback
    harness_mod._manager = HarnessSessionManager(reg, warden=_StubWarden())
    try:
        r = admin_client.post("/v1/harness/sessions", json={"description": "x"})
        assert r.status_code == 503
    finally:
        reg.set_enabled(SLOT_NAME, True)


def test_full_session_lifecycle(admin_client):
    _install_harness(warden=_StubWarden(block_on="EVIL"))

    r = admin_client.post("/v1/harness/sessions", json={"description": "do it", "role": "coder"})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    assert sid == "sess-http"

    r = admin_client.post(
        f"/v1/harness/sessions/{sid}/send",
        json={"messages": [{"role": "user", "content": "ping"}]},
    )
    assert r.status_code == 200 and r.json()["content"] == "pong"

    # Warden refuses a malicious payload → 400.
    r = admin_client.post(
        f"/v1/harness/sessions/{sid}/send",
        json={"messages": [{"role": "user", "content": "do EVIL"}]},
    )
    assert r.status_code == 400 and "warden" in r.json()["detail"]

    # SSE stream yields the harness event then closes.
    r = admin_client.get(f"/v1/harness/sessions/{sid}/stream")
    assert r.status_code == 200 and "hi" in r.text

    r = admin_client.delete(f"/v1/harness/sessions/{sid}")
    assert r.status_code == 200 and r.json()["stopped"] is True


def test_send_unknown_session_returns_404(admin_client):
    _install_harness(warden=_StubWarden())
    r = admin_client.post("/v1/harness/sessions/ghost/send", json={"messages": []})
    assert r.status_code == 404


# --- Authorization -------------------------------------------------------
#
# These assert the control fires on the input that motivated it, which is the
# check the original gap was missing. /v1/harness was mounted in main.py but
# absent from middleware.auth._PROTECTED_OPS, so it inherited only the blanket
# "/v1/ requires a session" rule. Authentication was never the hole; the hole
# was that *any* authenticated principal cleared it. `authed_client` logs in as
# role="user" with permissions=[] — the weakest account the app can mint — and
# starting a harness session is arbitrary code execution against an
# operator-supplied workdir. Each test below fails if the route is dropped from
# the scope table again, which a route-behaviour test would not notice.


def test_start_session_rejects_principal_without_harness_scope(authed_client):
    _install_harness(warden=_StubWarden())
    r = authed_client.post("/v1/harness/sessions", json={"description": "own you"})
    assert r.status_code == 403, (
        f"zero-permission user reached harness start (got {r.status_code}); "
        "/v1/harness is missing from _PROTECTED_OPS"
    )
    assert "harness.execute" in r.json()["detail"]


def test_send_turn_rejects_principal_without_harness_scope(authed_client):
    _install_harness(warden=_StubWarden())
    r = authed_client.post(
        "/v1/harness/sessions/sess-http/send",
        json={"messages": [{"role": "user", "content": "ping"}]},
    )
    # 403 before the 404 an unknown session would otherwise produce: the scope
    # check runs in middleware, ahead of the handler.
    assert r.status_code == 403
    assert "harness.execute" in r.json()["detail"]


def test_stop_session_rejects_principal_without_harness_scope(authed_client):
    _install_harness(warden=_StubWarden())
    r = authed_client.delete("/v1/harness/sessions/sess-http")
    assert r.status_code == 403


def test_harness_scope_is_not_satisfied_by_agents_write(authed_client):
    """harness.execute must be its own scope, not an alias of agents.write.

    Editing an agent's configuration and executing code as that agent are
    different privileges; if the harness route were gated behind agents.write,
    every operator who could edit a roster entry would silently also hold
    code execution.
    """
    from middleware.auth import _PROTECTED_OPS

    assert _PROTECTED_OPS["POST"]["/v1/harness"] == "harness.execute"
    assert _PROTECTED_OPS["POST"]["/v1/harness"] != _PROTECTED_OPS["POST"]["/v1/agents"]
