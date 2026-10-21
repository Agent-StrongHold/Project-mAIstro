"""Host-authorized delegated authority (ADR-068 / issue #845).

Agent manifests describe a requested roster, but they are not authority.  This
module is the durable-policy seam Sentinel consults before an agent can invoke
another agent.  A grant is bound to the complete execution identity and exact
effect so it cannot be copied to a different run or action.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from maistro.security.sentinel.authz_types import Principal


@dataclass(frozen=True)
class DelegationRequest:
    """One host-authorized delegation attempt."""

    principal: Principal
    owner_id: str
    delegating_agent_id: str
    target_agent_id: str
    goal_id: str
    run_id: str
    invocation_id: str
    scope: str
    action: str
    requested_actions: frozenset[str]
    artifact: str
    requested_at: datetime


@dataclass(frozen=True)
class DelegationGrant:
    """A host-created grant; no AgentIdentity field can create one."""

    grant_id: str
    principal_id: str
    owner_id: str
    delegating_agent_id: str
    target_agent_id: str
    goal_id: str
    run_id: str
    invocation_id: str
    scope: str
    action: str
    actions: frozenset[str]
    artifact: str
    expires_at: datetime
    granted_by: str
    provenance: str


@dataclass(frozen=True)
class DelegationDecision:
    """The effective, host-authorized envelope for a delegation."""

    allowed: bool
    effective_actions: frozenset[str] = frozenset()
    grant_id: str = ""
    expires_at: datetime | None = None
    provenance: str = ""
    reason: str = ""


@runtime_checkable
class DelegationAuthority(Protocol):
    """The single policy decision point for delegated authority.

    ``authorize`` is async because a durable authority reads host policy from
    the canonical backend; an in-memory implementation is equally valid.
    """

    async def authorize(
        self, request: DelegationRequest, *, now: datetime
    ) -> DelegationDecision: ...


def grant_matches(grant: DelegationGrant, request: DelegationRequest) -> bool:
    """Whether one host grant authorizes this exact delegation.

    The grant must bind the principal, owner, delegating and target agent,
    Goal/Run/Invocation, scope, exact action and exact artifact, and carry the
    provenance of who issued it.
    """
    # A grant without provenance of who issued it cannot authorize (#845).
    if grant.granted_by == "":
        return False
    checks = (
        grant.principal_id == request.principal.id,
        grant.owner_id == request.owner_id,
        grant.delegating_agent_id == request.delegating_agent_id,
        grant.target_agent_id == request.target_agent_id,
        grant.goal_id == request.goal_id,
        grant.run_id == request.run_id,
        grant.invocation_id == request.invocation_id,
        grant.scope == request.scope,
        grant.action == request.action,
        grant.artifact == request.artifact,
    )
    return all(checks)


def decide(
    grants: Iterable[DelegationGrant], request: DelegationRequest, *, now: datetime
) -> DelegationDecision:
    """Resolve the effective envelope for a delegation from host grants.

    Shared by every authority implementation so an in-memory seam and a durable
    store decide identically. The newest matching, unexpired grant wins; a
    target may advertise more capabilities than the host grants, so the
    effective envelope is the intersection, never the advertised set.
    """
    if request.principal.kind != "agent":
        return DelegationDecision(False, reason="delegation principal must be an agent")
    if request.principal.owner != request.owner_id:
        return DelegationDecision(False, reason="delegation owner does not match principal")
    for grant in reversed(list(grants)):
        if now >= grant.expires_at:
            continue
        if not grant_matches(grant, request):
            continue
        return DelegationDecision(
            True,
            effective_actions=frozenset(request.requested_actions & grant.actions),
            grant_id=grant.grant_id,
            expires_at=grant.expires_at,
            provenance=grant.provenance,
        )
    return DelegationDecision(False, reason="no host grant matches this delegation")


@dataclass
class InMemoryDelegationAuthority:
    """Host-owned policy store for tests and ephemeral deployments.

    Production replaces this object with a durable implementation without
    changing Agent or Graph execution. The only mutating API is intentionally
    named ``add_host_grant`` to make the trust boundary explicit: the host
    provisions grants, and no agent, manifest, or request field can.
    """

    grants: list[DelegationGrant] = field(default_factory=list)

    def add_host_grant(self, grant: DelegationGrant) -> None:
        self.grants.append(grant)

    async def authorize(self, request: DelegationRequest, *, now: datetime) -> DelegationDecision:
        return decide(self.grants, request, now=now)


def utc_now() -> datetime:
    """Small seam for callers that need one consistent decision timestamp."""
    return datetime.now(UTC)


__all__ = [
    "DelegationAuthority",
    "DelegationDecision",
    "DelegationGrant",
    "DelegationRequest",
    "InMemoryDelegationAuthority",
    "decide",
    "grant_matches",
    "utc_now",
]
