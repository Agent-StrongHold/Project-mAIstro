"""A2A guest peers — outbound delegation to external A2A agents.

Secure external agent communication with trust relationships,
auth headers, and audit logging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from maistro.a2a.delegation_context import (
    DelegationContext,
    DelegationContextError,
    validate_goal_binding,
)
from maistro.http import shared_client

logger = logging.getLogger("maistro.a2a.guest_peers")


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

    async def _refused_dispatch(
        self, peer_name: str, agent_id: str, context: DelegationContext | None
    ) -> DelegationResult | None:
        """The admission refusal for a context-less or incoherent dispatch.

        The transport is the last boundary an external Agent call crosses, so
        it is where issue #959's gate lives: no request leaves without a
        canonical :class:`DelegationContext` (caller principal, Workspace and
        Project scope, the delegating Run/NodeRun, and the effect identity),
        and the caller named on the envelope matches the context. A refusal
        here happens before any bytes reach the peer, so it is a *rejected*
        admission — never an uncertain remote effect.
        """
        if context is None:
            await self._audit.log_delegation(
                peer_name,
                agent_id,
                "refused: external delegation without canonical caller/workspace context",
            )
            return DelegationResult(
                task_id="",
                peer_name=peer_name,
                status="rejected",
                error=(
                    "external Agent delegation requires a canonical caller and "
                    "Workspace scope (delegation context)"
                ),
            )
        if context.delegating_agent != agent_id:
            await self._audit.log_delegation(
                peer_name,
                agent_id,
                "refused: envelope agent does not match the delegation context",
            )
            return DelegationResult(
                task_id="",
                peer_name=peer_name,
                status="rejected",
                error=(
                    f"delegation names agent {agent_id!r} but its canonical context "
                    f"binds {context.delegating_agent!r}"
                ),
            )
        # The receiver files sender-authored Goal evidence verbatim, so the
        # sending boundary is the last place an incoherent Goal/Subgoal
        # binding (goal_id without goal_revision, subgoal_of without a Goal)
        # can be refused instead of admitted as if it were evidence. The
        # dispatching node validates too; this re-check closes the bypass.
        try:
            validate_goal_binding(context)
        except DelegationContextError as exc:
            await self._audit.log_delegation(
                peer_name,
                agent_id,
                "refused: incoherent Goal/Subgoal binding on the delegation context",
            )
            return DelegationResult(
                task_id="",
                peer_name=peer_name,
                status="rejected",
                error=f"delegation context has an incoherent Goal binding: {exc}",
            )
        return None

    def _narrowed_for_peer(
        self,
        peer: PeerTrust,
        peer_name: str,
        agent_id: str,
        context: DelegationContext,
    ) -> tuple[DelegationContext | None, DelegationResult | None]:
        """Narrow the scope envelope at the boundary, or refuse it.

        The dispatching node attenuates before admission; re-checking here
        means a caller that bypassed the node still cannot claim more
        authority than the peer's declared ceiling.
        """
        try:
            return context.narrowed(peer.allowed_scopes), None
        except DelegationContextError as exc:
            return None, DelegationResult(
                task_id="",
                peer_name=peer_name,
                status="rejected",
                error=str(exc),
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
