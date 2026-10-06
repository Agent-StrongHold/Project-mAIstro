"""Tests for `maistro.a2a.guest_peers` — outbound delegation to external A2A peers."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from maistro.a2a.delegation_context import DelegationContext
from maistro.a2a.guest_peers import (
    DelegationResult,
    GuestPeerManager,
    InMemoryAuditLogger,
    PeerTrust,
)
from maistro.http import set_test_transport


def _context(
    agent: str = "planner", *, delegation_key: str = "effect-1", **overrides: Any
) -> DelegationContext:
    """One canonical delegation context; tests override single fields."""
    return DelegationContext(
        caller_principal_id="actor-1",
        delegating_agent=agent,
        workspace_id="workspace-1",
        project_id="project-1",
        run_id="run-1",
        node_run_id="node-run-1",
        delegation_key=delegation_key,
        **overrides,
    )


def _patch_transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    """Route the shared client through a MockTransport for this test."""
    del monkeypatch  # kept for call-site compatibility
    set_test_transport(httpx.MockTransport(handler))


def test_register_get_list_remove_peer() -> None:
    manager = GuestPeerManager()
    peer = PeerTrust(peer_url="http://hub", peer_name="hub")
    manager.register_peer(peer)
    assert manager.get_peer("hub") == peer
    assert manager.list_peers() == [peer]
    assert manager.remove_peer("hub") is True
    assert manager.get_peer("hub") is None


def test_remove_peer_unknown_returns_false() -> None:
    manager = GuestPeerManager()
    assert manager.remove_peer("nope") is False


def test_list_peers_excludes_inactive() -> None:
    manager = GuestPeerManager()
    manager.register_peer(PeerTrust(peer_url="http://a", peer_name="a", active=True))
    manager.register_peer(PeerTrust(peer_url="http://b", peer_name="b", active=False))
    assert [p.peer_name for p in manager.list_peers()] == ["a"]


async def test_delegate_without_a_context_is_refused_before_anything_else() -> None:
    """Issue #959: no external Agent call without a canonical caller and
    Workspace scope. The transport is the last boundary, so it refuses a
    context-less delegation even when everything else would admit it."""
    audit = InMemoryAuditLogger()
    manager = GuestPeerManager(audit=audit)
    manager.register_peer(PeerTrust(peer_url="http://hub", peer_name="hub"))
    result = await manager.delegate("hub", "planner", [{"role": "user", "content": "x"}])
    assert result.status == "rejected"
    assert "canonical caller" in (result.error or "")
    assert audit.entries[-1]["detail"].startswith("refused:")


async def test_delegate_agent_mismatching_the_context_is_refused() -> None:
    """The envelope names one agent; the canonical context binds another."""
    audit = InMemoryAuditLogger()
    manager = GuestPeerManager(audit=audit)
    manager.register_peer(PeerTrust(peer_url="http://hub", peer_name="hub"))
    result = await manager.delegate(
        "hub",
        "coder",
        [{"role": "user", "content": "x"}],
        context=_context(agent="planner"),
    )
    assert result.status == "rejected"
    assert "binds" in (result.error or "")


async def test_delegate_with_incoherent_goal_binding_is_refused_at_the_boundary() -> None:
    """Goal coherence is not left to the dispatching node only: a caller that
    bypasses `AgentDelegateRemoteNode` cannot send `goal_id` without
    `goal_revision`, or `subgoal_of` without a Goal, to the peer. The receiver
    files sender-authored Goal evidence verbatim, so the transport boundary is
    the last place to refuse it."""
    audit = InMemoryAuditLogger()
    manager = GuestPeerManager(audit=audit)
    manager.register_peer(PeerTrust(peer_url="http://hub", peer_name="hub"))
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["body"] = json.loads(request.content)
        return httpx.Response(200, json={"task_id": "remote-1"})

    set_test_transport(httpx.MockTransport(handler))
    for bad in (
        _context(goal_id="goal-1"),  # a bound Goal names its revision
        _context(subgoal_of="parent-1"),  # a parent Goal only with a Goal
        _context(goal_revision=2),  # a revision is meaningless without a Goal
    ):
        refused = await manager.delegate(
            "hub",
            "planner",
            [{"role": "user", "content": "x"}],
            context=bad,
        )
        assert refused.status == "rejected", bad
        assert "incoherent Goal binding" in (refused.error or ""), bad
    assert "body" not in sent, "nothing reached the peer"
    assert audit.entries[-1]["detail"].startswith("refused:")
    assert "Goal/Subgoal" in audit.entries[-1]["detail"]


async def test_delegate_claiming_scopes_beyond_the_peer_ceiling_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #959: delegated authority cannot exceed host policy. The peer's
    declared ceiling is the only granted authority; an excess claim is a
    refusal at the boundary, not a silent narrowing."""
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["body"] = json.loads(request.content)
        return httpx.Response(200, json={"task_id": "remote-1"})

    _patch_transport(monkeypatch, handler)
    manager = GuestPeerManager()
    manager.register_peer(
        PeerTrust(peer_url="http://hub", peer_name="hub", allowed_scopes=("web.read",))
    )
    refused = await manager.delegate(
        "hub",
        "planner",
        [{"role": "user", "content": "x"}],
        context=_context(delegated_scopes=("web.read", "shell.exec")),
    )
    assert refused.status == "rejected"
    assert "shell.exec" in (refused.error or "")
    assert "body" not in sent, "nothing reached the peer"

    allowed = await manager.delegate(
        "hub",
        "planner",
        [{"role": "user", "content": "x"}],
        idempotency_key="effect-1",  # must equal context.delegation_key
        context=_context(delegated_scopes=("web.read",)),
    )
    assert allowed.status == "submitted"
    assert sent["body"]["delegation_context"]["delegated_scopes"] == ["web.read"]


async def test_delegate_peer_not_found_rejected_and_audited() -> None:
    audit = InMemoryAuditLogger()
    manager = GuestPeerManager(audit=audit)
    result = await manager.delegate(
        "ghost", "agent1", [{"role": "user", "content": "x"}], context=_context(agent="agent1")
    )
    assert result == DelegationResult(
        task_id="", peer_name="ghost", status="rejected", error="peer not found"
    )
    assert audit.entries == [
        {"peer_name": "ghost", "agent_id": "agent1", "detail": "peer not found"}
    ]


async def test_delegate_peer_inactive_rejected_and_audited() -> None:
    audit = InMemoryAuditLogger()
    manager = GuestPeerManager(audit=audit)
    manager.register_peer(PeerTrust(peer_url="http://hub", peer_name="hub", active=False))
    result = await manager.delegate(
        "hub", "agent1", [{"role": "user", "content": "x"}], context=_context(agent="agent1")
    )
    assert result.status == "rejected"
    assert result.error == "peer inactive"
    assert audit.entries[-1]["detail"] == "peer inactive"


async def test_delegate_agent_not_in_allowed_list_rejected_and_audited() -> None:
    audit = InMemoryAuditLogger()
    manager = GuestPeerManager(audit=audit)
    manager.register_peer(
        PeerTrust(peer_url="http://hub", peer_name="hub", allowed_agents=("planner",))
    )
    result = await manager.delegate(
        "hub", "coder", [{"role": "user", "content": "x"}], context=_context(agent="coder")
    )
    assert result.status == "rejected"
    assert result.error == "agent 'coder' not allowed on this peer"
    assert audit.entries[-1]["detail"] == "agent 'coder' not in allowed list"


async def test_delegate_agent_in_allowed_list_proceeds_to_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = InMemoryAuditLogger()
    manager = GuestPeerManager(audit=audit)
    manager.register_peer(
        PeerTrust(peer_url="http://hub", peer_name="hub", allowed_agents=("planner",))
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"task_id": "remote-1"})

    _patch_transport(monkeypatch, handler)
    result = await manager.delegate(
        "hub", "planner", [{"role": "user", "content": "x"}], context=_context()
    )
    assert result.status == "submitted"
    assert result.task_id == "remote-1"


async def test_delegate_success_posts_to_tasks_create_with_auth_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["calls"] = int(seen.get("calls", 0)) + 1
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["auth"] = request.headers.get("authorization")
        seen["idempotency"] = request.headers.get("idempotency-key")
        return httpx.Response(200, json={"task_id": "remote-42"})

    _patch_transport(monkeypatch, handler)
    audit = InMemoryAuditLogger()
    manager = GuestPeerManager(audit=audit)
    manager.register_peer(
        PeerTrust(
            peer_url="http://hub.example/",
            peer_name="hub",
            auth_method="api_token",
            auth_credential="secret-token",
        )
    )
    result = await manager.delegate(
        "hub",
        "planner",
        [{"role": "user", "content": "do x"}],
        idempotency_key="effect-1",
        context=_context(),
    )
    assert seen["url"] == "http://hub.example/a2a/tasks/create"
    assert seen["method"] == "POST"
    assert seen["auth"] == "Bearer secret-token"
    assert seen["idempotency"] == "effect-1"
    assert result == DelegationResult(
        task_id="remote-42",
        peer_name="hub",
        status="submitted",
        peer_url="http://hub.example/",
    )
    assert (
        await manager.delegate(
            "hub",
            "planner",
            [{"role": "user", "content": "do x"}],
            idempotency_key="effect-1",
            context=_context(),
        )
        == result
    )
    assert seen["calls"] == 1
    assert audit.entries[-1] == {
        "peer_name": "hub",
        "agent_id": "planner",
        "detail": "task_id=remote-42",
    }


async def test_delegate_no_auth_header_when_credential_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"task_id": "remote-1"})

    _patch_transport(monkeypatch, handler)
    manager = GuestPeerManager()
    manager.register_peer(PeerTrust(peer_url="http://hub", peer_name="hub", auth_credential=""))
    await manager.delegate("hub", "planner", [{"role": "user", "content": "x"}], context=_context())
    assert seen["auth"] is None


async def test_delegate_non_api_token_auth_method_skips_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"task_id": "remote-1"})

    _patch_transport(monkeypatch, handler)
    manager = GuestPeerManager()
    manager.register_peer(
        PeerTrust(
            peer_url="http://hub",
            peer_name="hub",
            auth_method="mtls",
            auth_credential="irrelevant",
        )
    )
    await manager.delegate("hub", "planner", [{"role": "user", "content": "x"}], context=_context())
    assert seen["auth"] is None


async def test_delegate_http_error_status_returns_failed_and_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    _patch_transport(monkeypatch, handler)
    audit = InMemoryAuditLogger()
    manager = GuestPeerManager(audit=audit)
    manager.register_peer(PeerTrust(peer_url="http://hub", peer_name="hub"))
    result = await manager.delegate(
        "hub", "planner", [{"role": "user", "content": "x"}], context=_context()
    )
    assert result.status == "failed"
    assert result.task_id == ""
    assert result.error is not None
    assert audit.entries[-1]["peer_name"] == "hub"
    assert audit.entries[-1]["agent_id"] == "planner"


async def test_delegate_request_exception_returns_failed_and_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_transport(monkeypatch, handler)
    audit = InMemoryAuditLogger()
    manager = GuestPeerManager(audit=audit)
    manager.register_peer(PeerTrust(peer_url="http://hub", peer_name="hub"))
    result = await manager.delegate(
        "hub", "planner", [{"role": "user", "content": "x"}], context=_context()
    )
    assert result.status == "failed"
    assert result.task_id == ""
    assert "connection refused" in (result.error or "")
    assert audit.entries[-1]["detail"] == result.error


async def test_reconcile_sends_the_peers_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recovery must authenticate exactly like dispatch.

    A reconciliation GET without the peer's configured credential gets 401 from
    a protected peer; `raise_for_status` turns that into an uncertain result,
    so a receipt the peer is holding can never be recovered and the delegated
    work can never resume (review round, PR #1270).
    """
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"task_id": "remote-7"})

    _patch_transport(monkeypatch, handler)
    manager = GuestPeerManager()
    manager.register_peer(
        PeerTrust(
            peer_url="http://hub.example/",
            peer_name="hub",
            auth_method="api_token",
            auth_credential="secret-token",
            supports_idempotency=True,
        )
    )
    result = await manager.reconcile("hub", "key-1")
    assert seen["url"] == "http://hub.example/a2a/tasks/by-idempotency-key/key-1"
    assert seen["method"] == "GET"
    assert seen["auth"] == "Bearer secret-token"
    assert result == DelegationResult(task_id="remote-7", peer_name="hub", status="submitted")


async def test_reconcile_skips_auth_header_when_credential_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(404)

    _patch_transport(monkeypatch, handler)
    manager = GuestPeerManager()
    manager.register_peer(
        PeerTrust(peer_url="http://hub", peer_name="hub", supports_idempotency=True)
    )
    result = await manager.reconcile("hub", "key-1")
    assert seen["auth"] is None
    assert result == DelegationResult(task_id="", peer_name="hub", status="not_found")


async def test_delegate_missing_task_id_in_response_defaults_to_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    _patch_transport(monkeypatch, handler)
    manager = GuestPeerManager()
    manager.register_peer(PeerTrust(peer_url="http://hub", peer_name="hub"))
    result = await manager.delegate(
        "hub", "planner", [{"role": "user", "content": "x"}], context=_context()
    )
    assert result.status == "submitted"
    assert result.task_id == ""


async def test_empty_dispatch_receipt_does_not_mask_peer_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        payload = {} if request.method == "POST" else {"task_id": "recovered-task"}
        return httpx.Response(200, json=payload)

    _patch_transport(monkeypatch, handler)
    manager = GuestPeerManager()
    manager.register_peer(
        PeerTrust(peer_url="http://hub", peer_name="hub", supports_idempotency=True)
    )
    submitted = await manager.delegate("hub", "planner", [], context=_context())
    assert submitted.task_id == ""
    recovered = await manager.reconcile("hub", "effect-1")
    assert recovered.task_id == "recovered-task"
    assert await manager.reconcile("hub", "effect-1") == recovered
    assert methods == ["POST", "GET"], "an empty receipt must not suppress recovery"


async def test_audit_log_default_is_in_memory_audit_logger() -> None:
    manager = GuestPeerManager()
    assert isinstance(manager._audit, InMemoryAuditLogger)


async def test_in_memory_audit_logger_records_entries() -> None:
    logger = InMemoryAuditLogger()
    await logger.log_delegation("hub", "agent1", "some detail")
    assert logger.entries == [{"peer_name": "hub", "agent_id": "agent1", "detail": "some detail"}]


async def test_reconcile_returns_the_cached_receipt_without_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A receipt already recovered is served from the cache: the poll the
    reconciliation pause owns re-enters every tick, and re-asking the peer
    for an answer already in hand would be a request per tick."""
    gets = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        gets["n"] += 1
        return httpx.Response(200, json={"task_id": "remote-3"})

    _patch_transport(monkeypatch, handler)
    manager = GuestPeerManager()
    manager.register_peer(
        PeerTrust(peer_url="http://hub", peer_name="hub", supports_idempotency=True)
    )
    first = await manager.reconcile("hub", "key-1")
    second = await manager.reconcile("hub", "key-1")
    assert gets["n"] == 1
    assert (
        second == first == DelegationResult(task_id="remote-3", peer_name="hub", status="submitted")
    )


async def test_reconcile_an_unknown_peer_is_uncertain(monkeypatch: pytest.MonkeyPatch) -> None:
    del monkeypatch  # no transport is reached
    manager = GuestPeerManager()
    result = await manager.reconcile("ghost", "key-1")
    assert result == DelegationResult(
        task_id="", peer_name="ghost", status="uncertain", error="peer cannot reconcile"
    )


async def test_reconcile_transport_error_is_uncertain(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ConnectError("peer unreachable")

    _patch_transport(monkeypatch, handler)
    manager = GuestPeerManager()
    manager.register_peer(
        PeerTrust(peer_url="http://hub", peer_name="hub", supports_idempotency=True)
    )
    result = await manager.reconcile("hub", "key-1")
    assert result.status == "uncertain"
    assert "peer unreachable" in (result.error or "")


async def test_delegate_returns_the_cached_receipt_for_the_same_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts["n"] += 1
            return httpx.Response(200, json={"task_id": "remote-5"})
        return httpx.Response(405)

    _patch_transport(monkeypatch, handler)
    manager = GuestPeerManager()
    manager.register_peer(PeerTrust(peer_url="http://hub", peer_name="hub"))
    first = await manager.delegate(
        "hub",
        "planner",
        [{"role": "user", "content": "x"}],
        idempotency_key="key-1",
        context=_context(delegation_key="key-1"),
    )
    second = await manager.delegate(
        "hub",
        "planner",
        [{"role": "user", "content": "x"}],
        idempotency_key="key-1",
        context=_context(delegation_key="key-1"),
    )
    assert posts["n"] == 1
    assert second == first


async def test_delegate_derives_transport_key_from_context_delegation_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["idempotency"] = request.headers.get("idempotency-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"task_id": "remote-6"})

    _patch_transport(monkeypatch, handler)
    manager = GuestPeerManager()
    manager.register_peer(PeerTrust(peer_url="http://hub", peer_name="hub"))
    result = await manager.delegate(
        "hub",
        "planner",
        [{"role": "user", "content": "x"}],
        context=_context(),
    )
    assert result.status == "submitted"
    assert seen["idempotency"] == seen["body"]["delegation_context"]["delegation_key"]
    assert seen["idempotency"] == "effect-1"


async def test_delegate_rejects_idempotency_key_diverging_from_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["body"] = json.loads(request.content)
        return httpx.Response(200, json={"task_id": "remote-7"})

    _patch_transport(monkeypatch, handler)
    audit = InMemoryAuditLogger()
    manager = GuestPeerManager(audit=audit)
    manager.register_peer(PeerTrust(peer_url="http://hub", peer_name="hub"))
    refused = await manager.delegate(
        "hub",
        "planner",
        [{"role": "user", "content": "x"}],
        idempotency_key="other-key",
        context=_context(),
    )
    assert refused.status == "rejected"
    assert "idempotency_key" in (refused.error or "")
    assert "body" not in sent, "nothing reached the peer"
    assert "refused" in audit.entries[-1]["detail"]
