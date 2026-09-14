"""A2A guest peers — outbound delegation to external A2A agents.

Secure external agent communication with trust relationships,
auth headers, and audit logging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from maistro.http import shared_client

logger = logging.getLogger("maistro.a2a.guest_peers")


@dataclass(frozen=True)
class PeerTrust:
    """Trust relationship with an external A2A peer."""

    peer_url: str
    peer_name: str
    auth_method: str = "api_token"
    auth_credential: str = ""
    allowed_agents: tuple[str, ...] = ()
    active: bool = True


@dataclass
class DelegationResult:
    """Result of an outbound A2A delegation."""

    task_id: str
    peer_name: str
    status: str
    result: str | None = None
    error: str | None = None


@runtime_checkable
class AuditLogger(Protocol):
    """Audit log interface for delegation events."""

    async def log_delegation(
        self,
        peer_name: str,
        agent_id: str,
        detail: str,
    ) -> None: ...


class InMemoryAuditLogger:
    """In-memory audit logger for testing."""

    def __init__(self) -> None:
        self.entries: list[dict[str, str]] = []

    async def log_delegation(
        self,
        peer_name: str,
        agent_id: str,
        detail: str,
    ) -> None:
        self.entries.append(
            {
                "peer_name": peer_name,
                "agent_id": agent_id,
                "detail": detail,
            }
        )


class DelegationMessages(list[dict[str, str]]):
    """JSON-compatible messages carrying transport idempotency metadata."""

    def __init__(self, messages: list[dict[str, str]], *, effect_key: str = "") -> None:
        super().__init__(messages)
        self.effect_key = effect_key


class GuestPeerManager:
    """Registry of trusted external A2A peers with secure delegation."""

    def __init__(self, audit: AuditLogger | None = None) -> None:
        self._peers: dict[str, PeerTrust] = {}
        self._audit = audit or InMemoryAuditLogger()
        self._delegations_by_effect: dict[tuple[str, str], DelegationResult] = {}

    def register_peer(self, peer: PeerTrust) -> None:
        self._peers[peer.peer_name] = peer

    def remove_peer(self, peer_name: str) -> bool:
        return self._peers.pop(peer_name, None) is not None

    def get_peer(self, peer_name: str) -> PeerTrust | None:
        return self._peers.get(peer_name)

    def list_peers(self) -> list[PeerTrust]:
        return [p for p in self._peers.values() if p.active]

    async def delegate(
        self,
        peer_name: str,
        agent_id: str,
        messages: list[dict[str, str]],
        *,
        idempotency_key: str = "",
    ) -> DelegationResult:
        """Delegate a task to an external A2A peer.

        The key is sent at the transport boundary so a remote admission service
        can deduplicate a request whose caller lost its lease after dispatch.
        """
        idempotency_key = idempotency_key or str(getattr(messages, "effect_key", ""))
        if idempotency_key:
            cached = self._delegations_by_effect.get((peer_name, idempotency_key))
            if cached is not None:
                return DelegationResult(
                    task_id=cached.task_id,
                    peer_name=cached.peer_name,
                    status=cached.status,
                    result=cached.result,
                    error=cached.error,
                )
        peer = self.get_peer(peer_name)
        if not peer:
            await self._audit.log_delegation(
                peer_name,
                agent_id,
                "peer not found",
            )
            return DelegationResult(
                task_id="",
                peer_name=peer_name,
                status="rejected",
                error="peer not found",
            )

        if not peer.active:
            await self._audit.log_delegation(
                peer_name,
                agent_id,
                "peer inactive",
            )
            return DelegationResult(
                task_id="",
                peer_name=peer_name,
                status="rejected",
                error="peer inactive",
            )

        if peer.allowed_agents and agent_id not in peer.allowed_agents:
            await self._audit.log_delegation(
                peer_name,
                agent_id,
                f"agent '{agent_id}' not in allowed list",
            )
            return DelegationResult(
                task_id="",
                peer_name=peer_name,
                status="rejected",
                error=f"agent '{agent_id}' not allowed on this peer",
            )

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if peer.auth_method == "api_token" and peer.auth_credential:
            headers["Authorization"] = f"Bearer {peer.auth_credential}"

        try:
            async with shared_client(timeout=30.0) as client:
                resp = await client.post(
                    f"{peer.peer_url.rstrip('/')}/a2a/tasks/create",
                    json={
                        "agent_id": agent_id,
                        "messages": messages,
                        "idempotency_key": idempotency_key,
                    },
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            await self._audit.log_delegation(
                peer_name,
                agent_id,
                f"task_id={data.get('task_id', '')}",
            )
            result = DelegationResult(
                task_id=data.get("task_id", ""),
                peer_name=peer_name,
                status="submitted",
            )
            if idempotency_key and result.task_id:
                self._delegations_by_effect[(peer_name, idempotency_key)] = result
            return result
        except Exception as exc:
            await self._audit.log_delegation(
                peer_name,
                agent_id,
                str(exc),
            )
            return DelegationResult(
                task_id="",
                peer_name=peer_name,
                status="failed",
                error=str(exc),
            )
