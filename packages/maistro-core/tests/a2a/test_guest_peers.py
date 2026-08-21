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
