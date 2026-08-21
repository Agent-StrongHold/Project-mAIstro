from __future__ import annotations

from typing import Any

from maistro.capabilities.providers.approval_inbox import InboxApproval
from maistro.capabilities.providers.host_health import HostHealthAction
from maistro.capabilities.slots.approval import ApprovalDecision, ApprovalRequest


class FakeHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_json(self, path: str) -> dict[str, Any]:
        return {}

    async def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((path, body))
        return {"status": "ok"}


class AutoApprove(InboxApproval):
    async def request(self, req: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(request_id=req.request_id, approved=True, actor="test")


class AutoDeny(InboxApproval):
    async def request(self, req: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(request_id=req.request_id, approved=False, actor="test")


async def test_read_action_runs_without_approval():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="auto_safe", approval=AutoDeny())
    res = await act.act("docker_logs", {"name": "x"})
    assert res.ok and http.calls


async def test_reversible_runs_when_auto_safe():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="auto_safe", approval=AutoDeny())
    res = await act.act("restart_container", {"name": "x"})
    assert res.ok and http.calls


async def test_destructive_blocked_until_approved():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="auto_safe", approval=AutoDeny())
    res = await act.act("docker_prune", {})
    assert res.ok is False and res.blocked_pending_approval and not http.calls


async def test_destructive_runs_after_approval():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="auto_safe", approval=AutoApprove())
    res = await act.act("restart_stack", {"name": "traefik"})
    assert res.ok and http.calls


async def test_detect_only_never_executes():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="detect_only", approval=AutoApprove())
    res = await act.act("restart_container", {"name": "x"})
    assert res.ok is False and not http.calls


async def test_approve_all_gates_reversible():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="approve_all", approval=AutoDeny())
    res = await act.act("restart_container", {"name": "x"})
    assert res.ok is False and res.blocked_pending_approval and not http.calls


async def test_approve_all_runs_read_free():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="approve_all", approval=AutoDeny())
    res = await act.act("docker_logs", {})
    assert res.ok and http.calls


async def test_approve_all_gates_destructive_then_runs_after_approval():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="approve_all", approval=AutoApprove())
    res = await act.act("docker_prune", {})
    assert res.ok and http.calls


async def test_action_not_in_allowlist_refused():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="auto_safe", approval=AutoApprove())
    res = await act.act("rm_rf_everything", {})
    assert res.ok is False and not http.calls


async def test_destructive_with_no_approval_provider_blocks():
    http = FakeHttp()
    act = HostHealthAction(http=http, autonomy="auto_safe", approval=None)
    res = await act.act("docker_prune", {})
    assert res.ok is False and res.blocked_pending_approval and not http.calls
