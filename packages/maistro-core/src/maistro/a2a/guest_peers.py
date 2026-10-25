"""A2A guest peers — outbound delegation to external A2A agents.

Secure external agent communication with trust relationships,
auth headers, and audit logging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import quote

from maistro.a2a.delegation_context import (
    DelegationContext,
    DelegationContextError,
    validate_goal_binding,
)
from maistro.a2a.inbound import InboundWarden, default_warden, scan_inbound
from maistro.http import shared_client

logger = logging.getLogger("maistro.a2a.guest_peers")
_WARDEN_UNSET = object()


@dataclass(frozen=True)
class PeerTrust:
    """Trust relationship with an external A2A peer.

    ``allowed_scopes`` is the host's capability ceiling for this peer (issue
    #959): the maximum authority any delegation to it may claim. The empty
    tuple is fail-closed — a delegation that claims any scope against a peer
    with no declared ceiling is refused, because an unconfigured ceiling
    granted nothing. ``trust_tier`` is the operator-declared trust tier the
    peer's capability Provider reports.
    """

    peer_url: str
    peer_name: str
    auth_method: str = "api_token"
    auth_credential: str = ""
    allowed_agents: tuple[str, ...] = ()
    allowed_scopes: tuple[str, ...] = ()
    trust_tier: str = "t2"
    active: bool = True
    # A peer must explicitly promise durable idempotent admission before a
    # recovery worker may safely retry an uncertain POST.
    supports_idempotency: bool = False


@dataclass
class DelegationResult:
    """Result of an outbound A2A delegation.

    ``peer_url``/``agent_version``/``protocol_version`` are the remote
    endpoint provenance the dispatch recorded (issue #959): which endpoint
    accepted the work and, when the peer reports it, which Agent/protocol
    version answered. They travel beside — never instead of — the canonical
    child Run identity.
    """

    task_id: str
    peer_name: str
    status: str
    result: str | None = None
    error: str | None = None
    peer_url: str = ""
    agent_version: str = ""
    protocol_version: str = ""


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


class GuestPeerManager:
    """Registry of trusted external A2A peers with secure delegation."""

    def __init__(
        self,
        audit: AuditLogger | None = None,
        *,
        warden: InboundWarden | None | object = _WARDEN_UNSET,
    ) -> None:
        self._peers: dict[str, PeerTrust] = {}
        self._audit = audit or InMemoryAuditLogger()
        # A peer response is untrusted even after transport authentication. The
        # default is the canonical detector; an explicitly unavailable policy
        # is handled fail-closed by scan_inbound.
        self._warden = (
            default_warden() if warden is _WARDEN_UNSET else cast(InboundWarden | None, warden)
        )
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

    async def poll_result(self, peer_name: str, task_id: str) -> DelegationResult | None:
        """Read a terminal result from a peer, or ``None`` while it runs.

        Cross-instance delegation has no in-process task receipt to callback
        into. The recovery tick therefore uses the peer's task-status resource
        as its timer waker. A transport error is deliberately not a failed
        delegation: the task may still be running, so the next tick must be
        allowed to try again.
        """
        if not task_id:
            return None
        peer = self.get_peer(peer_name)
        if peer is None or not peer.active:
            return None

        headers: dict[str, str] = {"Accept": "application/json"}
        if peer.auth_method == "api_token" and peer.auth_credential:
            headers["Authorization"] = f"Bearer {peer.auth_credential}"
        try:
            async with shared_client(timeout=30.0) as client:
                response = await client.get(
                    f"{peer.peer_url.rstrip('/')}/a2a/tasks/{quote(task_id, safe='')}",
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
        except Exception:
            logger.warning(
                "could not poll A2A task %s from peer %s",
                task_id,
                peer_name,
                exc_info=True,
            )
            return None

        data = payload.get("task", payload) if isinstance(payload, dict) else {}
        status = str(data.get("status") or "").lower()
        if status not in {"completed", "failed", "cancelled", "timed_out"}:
            return None
        result = data.get("result")
        return DelegationResult(
            task_id=task_id,
            peer_name=peer_name,
            status=status,
            result=result if isinstance(result, str) or result is None else str(result),
            error=data.get("error"),
        )

    async def delegate(
        self,
        peer_name: str,
        agent_id: str,
        messages: list[dict[str, str]],
        *,
        idempotency_key: str | None = None,
        context: DelegationContext | None = None,
    ) -> DelegationResult:
        """Delegate a task to an external A2A peer.

        The key is sent at the transport boundary so a remote admission service
        can deduplicate a request whose caller lost its lease after dispatch.
        """
        refused = await self._refused_dispatch(peer_name, agent_id, context)
        if refused is not None:
            return refused
        assert context is not None  # refused above when absent

        # One canonical key: the transport Idempotency-Key (what the receiver
        # claims its Run by) must be the context's ``delegation_key`` (the
        # persisted evidence), or recovery and provenance would name different
        # logical effects. Derive it from the validated context; never accept
        # a divergent caller-supplied key.
        if idempotency_key is None:
            idempotency_key = context.delegation_key
        elif idempotency_key != context.delegation_key:
            await self._audit.log_delegation(
                peer_name, agent_id, "refused: idempotency_key != context.delegation_key"
            )
            return DelegationResult(
                task_id="",
                peer_name=peer_name,
                status="rejected",
                error="idempotency_key does not match context.delegation_key",
            )

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
        narrowed, scope_refusal = self._narrowed_for_peer(peer, peer_name, agent_id, context)
        if scope_refusal is not None:
            await self._audit.log_delegation(peer_name, agent_id, f"refused: {scope_refusal.error}")
            return scope_refusal
        assert narrowed is not None  # a refusal returned above otherwise
        return await self._post_delegation_task(
            peer, agent_id, messages, narrowed, idempotency_key=idempotency_key
        )

    async def _post_delegation_task(
        self,
        peer: PeerTrust,
        agent_id: str,
        messages: list[dict[str, str]],
        narrowed: DelegationContext,
        *,
        idempotency_key: str | None,
    ) -> DelegationResult:
        """The one physical POST of an admitted delegation, then its receipt.

        The body carries the canonical delegation context (issue #959) beside
        the idempotency key; the response may report remote Agent/protocol
        versions, which travel as provenance on the result. Any transport
        failure is returned as an uncertain `failed` outcome -- the peer's
        acceptance is unknown, never assumed absent.
        """
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
                        # The receiver contract is the canonical A2A admission
                        # endpoint's `A2ATaskCreate.idempotency_key`; a durable
                        # receiver dedupes the physical POST by this key.
                        "idempotency_key": idempotency_key,
                        # The canonical caller/scope/Goal/Run binding (issue
                        # #959). Evidence for the receiving admission; the
                        # receiver's own guards remain its authorization.
                        "delegation_context": narrowed.as_payload(),
                    },
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            # A peer response is untrusted even after transport authentication
            # (issue #1137): Warden scans the exact representation before it
            # can reach trusted context; an unavailable policy fails closed.
            verdict = await scan_inbound(self._warden, data)
            if not verdict.clean:
                await self._audit.log_delegation(
                    peer.peer_name,
                    agent_id,
                    "warden refused a2a response",
                )
                return DelegationResult(
                    task_id="",
                    peer_name=peer.peer_name,
                    status="rejected",
                    error="inbound A2A response refused by Warden",
                    peer_url=peer.peer_url,
                )

        except Exception as exc:
            await self._audit.log_delegation(peer.peer_name, agent_id, str(exc))
            return DelegationResult(
                task_id="",
                peer_name=peer.peer_name,
                status="failed",
                error=str(exc),
                peer_url=peer.peer_url,
            )

        await self._audit.log_delegation(
            peer.peer_name,
            agent_id,
            f"task_id={data.get('task_id', '')}",
        )
        submitted = DelegationResult(
            task_id=data.get("task_id", ""),
            peer_name=peer.peer_name,
            status="submitted",
            peer_url=peer.peer_url,
            # Remote Agent provenance, when the peer reports it. Absent
            # stays absent; the canonical identity is unaffected either way.
            agent_version=str(data.get("agent_version") or ""),
            protocol_version=str(data.get("protocol_version") or ""),
        )
        if idempotency_key and submitted.task_id:
            self._idempotent_receipts[(peer.peer_name, idempotency_key)] = submitted
        return submitted
