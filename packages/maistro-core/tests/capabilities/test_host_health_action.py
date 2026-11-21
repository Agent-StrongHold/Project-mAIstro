from __future__ import annotations

from typing import Any

from maistro.capabilities.providers.host_health import HostHealthAction


class FakeHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_json(self, path: str) -> dict[str, Any]:
        return {}

    async def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((path, body))
        return {"status": "ok"}


async def test_read_action_runs_without_approval():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="auto_safe")
    res = await act.act("docker_logs", {"name": "x"})
    assert res.ok and http.calls


async def test_reversible_runs_when_auto_safe():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="auto_safe")
    res = await act.act("restart_container", {"name": "x"})
    assert res.ok and http.calls


async def test_destructive_blocked_without_approved_flag():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="auto_safe")
    res = await act.act("docker_prune", {})
    assert res.ok is False and res.blocked_pending_approval and not http.calls


async def test_destructive_runs_when_approved():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="auto_safe")
    res = await act.act("restart_stack", {"name": "traefik"}, approved=True)
    assert res.ok and http.calls


async def test_detect_only_never_executes():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="detect_only")
    res = await act.act("restart_container", {"name": "x"}, approved=True)
    assert res.ok is False and not http.calls


async def test_approve_all_gates_reversible_until_approved():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="approve_all")
    res = await act.act("restart_container", {"name": "x"})
    assert res.ok is False and res.blocked_pending_approval and not http.calls


async def test_approve_all_runs_read_free():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="approve_all")
    res = await act.act("docker_logs", {})
    assert res.ok and http.calls


async def test_approve_all_destructive_runs_when_approved():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="approve_all")
    res = await act.act("docker_prune", {}, approved=True)
    assert res.ok and http.calls


async def test_action_not_in_allowlist_refused():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="auto_safe")
    res = await act.act("rm_rf_everything", {}, approved=True)
    assert res.ok is False and not http.calls


async def test_needs_approval_matches_autonomy_tiers():
    act = HostHealthAction(http=FakeHttp(), autonomy="auto_safe")
    assert act.needs_approval("docker_prune", {}) is True
    assert act.needs_approval("restart_container", {"name": "x"}) is False
    gated = HostHealthAction(http=FakeHttp(), autonomy="approve_all")
    assert gated.needs_approval("restart_container", {"name": "x"}) is True
