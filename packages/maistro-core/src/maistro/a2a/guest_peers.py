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
    # A peer must explicitly promise durable idempotent admission before a
    # recovery worker may safely retry an uncertain POST.
    supports_idempotency: bool = False


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
        # This is a process-local receipt cache only. The key is still sent to
        # the peer so a peer that supports idempotent admission remains safe
        # across replicas; a cache must never be mistaken for remote truth.
        self._idempotent_receipts: dict[tuple[str, str], DelegationResult] = {}

    def register_peer(self, peer: PeerTrust) -> None:
        self._peers[peer.peer_name] = peer

    def remove_peer(self, peer_name: str) -> bool:
        return self._peers.pop(peer_name, None) is not None

    def get_peer(self, peer_name: str) -> PeerTrust | None:
        return self._peers.get(peer_name)

    def list_peers(self) -> list[PeerTrust]:
        return [p for p in self._peers.values() if p.active]

    @staticmethod
    def _peer_auth_headers(peer: PeerTrust) -> dict[str, str]:
        """The authentication a request to this peer must carry.

        `delegate` and `reconcile` authenticate identically. A reconciliation
        GET sent without the peer's configured credential gets 401 from a
        protected peer, which reads as an uncertain transport rather than a
        refused request -- so a receipt the peer is holding becomes
        unrecoverable and the delegated work can never resume.
        """
        if peer.auth_method == "api_token" and peer.auth_credential:
            return {"Authorization": f"Bearer {peer.auth_credential}"}
        return {}

    async def reconcile(self, peer_name: str, idempotency_key: str) -> DelegationResult:
        """Recover a receipt without re-submitting uncertain remote work."""
        cached = self._idempotent_receipts.get((peer_name, idempotency_key))
        if cached is not None:
            return cached
        peer = self.get_peer(peer_name)
        if peer is None or not peer.active:
            return DelegationResult("", peer_name, "uncertain", error="peer cannot reconcile")
        if not peer.supports_idempotency:
            return DelegationResult(
                "", peer_name, "uncertain", error="peer does not support idempotent reconciliation"
            )
        try:
            async with shared_client(timeout=30.0) as client:
                response = await client.get(
                    f"{peer.peer_url.rstrip('/')}/a2a/tasks/by-idempotency-key/{idempotency_key}",
                    headers=self._peer_auth_headers(peer),
                )
                if response.status_code == 404:
                    return DelegationResult("", peer_name, "not_found")
                response.raise_for_status()
                task_id = response.json().get("task_id", "")
            submitted = DelegationResult(task_id=task_id, peer_name=peer_name, status="submitted")
            # Memoize the recovery, not just the dispatch: the reconciliation
            # poll re-enters on every tick, and a receipt for a delegation key
            # is immutable, so re-asking the peer per tick buys nothing.
            self._idempotent_receipts[(peer_name, idempotency_key)] = submitted
            return submitted
        except Exception as exc:
            return DelegationResult("", peer_name, "uncertain", error=str(exc))

    def _admission_rejection(self, peer: PeerTrust | None, agent_id: str) -> tuple[str, str] | None:
        """The (audit detail, result error) this peer/agent pair is refused for.

        One guard for the three structural refusals -- unknown peer, inactive
        peer, agent outside the allow list -- so `delegate` reads as cache
        check, admission, transport, in that order.
        """
        if peer is None:
            return "peer not found", "peer not found"
        if not peer.active:
            return "peer inactive", "peer inactive"
        if peer.allowed_agents and agent_id not in peer.allowed_agents:
            return (
                f"agent '{agent_id}' not in allowed list",
                f"agent '{agent_id}' not allowed on this peer",
            )
        return None

    async def delegate(
        self,
        peer_name: str,
        agent_id: str,
        messages: list[dict[str, str]],
        *,
        idempotency_key: str | None = None,
    ) -> DelegationResult:
        """Delegate a task to an external A2A peer.

        The key is sent at the transport boundary so a remote admission service
        can deduplicate a request whose caller lost its lease after dispatch.
        """
        idempotency_key = idempotency_key or str(getattr(messages, "effect_key", ""))
        if idempotency_key:
            cached = self._idempotent_receipts.get((peer_name, idempotency_key))
            if cached is not None:
                return cached

        peer = self.get_peer(peer_name)
        rejection = self._admission_rejection(peer, agent_id)
        if rejection is not None:
            audit_detail, error = rejection
            await self._audit.log_delegation(peer_name, agent_id, audit_detail)
            return DelegationResult(
                task_id="",
                peer_name=peer_name,
                status="rejected",
                error=error,
            )
        assert peer is not None  # an admitted peer exists by construction

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            **self._peer_auth_headers(peer),
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

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
            submitted = DelegationResult(
                task_id=data.get("task_id", ""),
                peer_name=peer_name,
                status="submitted",
            )
            if idempotency_key and submitted.task_id:
                self._idempotent_receipts[(peer_name, idempotency_key)] = submitted
            return submitted
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
