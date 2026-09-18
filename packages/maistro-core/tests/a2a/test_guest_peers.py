"""Tests for `maistro.a2a.guest_peers` — outbound delegation to external A2A peers."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from maistro.a2a.guest_peers import (
    DelegationResult,
    GuestPeerManager,
    InMemoryAuditLogger,
    PeerTrust,
)
from maistro.http import set_test_transport


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


async def test_delegate_peer_not_found_rejected_and_audited() -> None:
    audit = InMemoryAuditLogger()
    manager = GuestPeerManager(audit=audit)
    result = await manager.delegate("ghost", "agent1", [{"role": "user", "content": "x"}])
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
    result = await manager.delegate("hub", "agent1", [{"role": "user", "content": "x"}])
    assert result.status == "rejected"
    assert result.error == "peer inactive"
    assert audit.entries[-1]["detail"] == "peer inactive"


async def test_delegate_agent_not_in_allowed_list_rejected_and_audited() -> None:
    audit = InMemoryAuditLogger()
    manager = GuestPeerManager(audit=audit)
    manager.register_peer(
        PeerTrust(peer_url="http://hub", peer_name="hub", allowed_agents=("planner",))
    )
    result = await manager.delegate("hub", "coder", [{"role": "user", "content": "x"}])
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
    result = await manager.delegate("hub", "planner", [{"role": "user", "content": "x"}])
    assert result.status == "submitted"
    assert result.task_id == "remote-1"


async def test_delegate_success_posts_to_tasks_create_with_auth_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["auth"] = request.headers.get("authorization")
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
    result = await manager.delegate("hub", "planner", [{"role": "user", "content": "do x"}])
    assert seen["url"] == "http://hub.example/a2a/tasks/create"
    assert seen["method"] == "POST"
    assert seen["auth"] == "Bearer secret-token"
    assert result == DelegationResult(task_id="remote-42", peer_name="hub", status="submitted")
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
    await manager.delegate("hub", "planner", [{"role": "user", "content": "x"}])
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
    await manager.delegate("hub", "planner", [{"role": "user", "content": "x"}])
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
    result = await manager.delegate("hub", "planner", [{"role": "user", "content": "x"}])
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
    result = await manager.delegate("hub", "planner", [{"role": "user", "content": "x"}])
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
    result = await manager.delegate("hub", "planner", [{"role": "user", "content": "x"}])
    assert result.status == "submitted"
    assert result.task_id == ""


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
        "hub", "planner", [{"role": "user", "content": "x"}], idempotency_key="key-1"
    )
    second = await manager.delegate(
        "hub", "planner", [{"role": "user", "content": "x"}], idempotency_key="key-1"
    )
    assert posts["n"] == 1
    assert second == first
