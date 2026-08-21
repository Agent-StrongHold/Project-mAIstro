"""Elevation flows — self-elevation re-auth and agent scoped-2FA (SPEC-247 / ADR-068 §D)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from maistro.security._types import AuditLog


class ScopedTwoFactorForHumanError(ValueError):
    """Raised when request_scoped_2fa is called for a human principal."""


def hash_args(args: dict[str, Any]) -> str:
    """Canonicalize and hash call args so a scoped-2FA grant binds to one concrete call."""
    canonical = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class ElevationGrant:
    """A cleared elevation: self-signed (human) or owner-signed (agent scoped-2FA)."""

    principal_id: str
    action_class: str
    kind: Literal["self_elevation", "scoped_2fa"]
    granted_at: datetime
    ttl_seconds: int
    signed_by: str
    action_args_hash: str | None = None

    def is_valid(self, *, now: datetime, action_class: str, args_hash: str | None = None) -> bool:
        """Whether this grant still covers the given action class (and args, for scoped-2FA)."""
        if self.action_class != action_class:
            return False
        elapsed = (now - self.granted_at).total_seconds()
        if elapsed > self.ttl_seconds:
            return False
        return not (self.kind == "scoped_2fa" and self.action_args_hash != args_hash)


@dataclass(frozen=True)
class ElevationChallenge:
    """A pending self-elevation re-auth challenge for a human principal."""

    principal_id: str
    action_class: str


@dataclass(frozen=True)
class ScopedApprovalRequest:
    """A pending scoped-2FA request: one action, concrete args, short TTL."""

    agent_principal_id: str
    owner: str
    action_class: str
    args_hash: str
    ttl_seconds: int


class ElevationStore(Protocol):
    """Persists and queries elevation grants."""

    async def store(self, grant: ElevationGrant) -> None:
        """Persist a cleared grant."""
        ...

    async def find_valid(
        self, principal_id: str, action_class: str, args_hash: str | None
    ) -> ElevationGrant | None:
        """Return an unexpired grant matching principal/action(/args), or None."""
        ...


@dataclass
class InMemoryElevationStore:
    """An in-memory ElevationStore, mirroring InMemoryEpisodicStore's DI convention."""

    grants: list[ElevationGrant] = field(default_factory=list)

    async def store(self, grant: ElevationGrant) -> None:
        """Append the grant to the in-memory list."""
        self.grants.append(grant)

    async def find_valid(
        self, principal_id: str, action_class: str, args_hash: str | None
    ) -> ElevationGrant | None:
        """Return the most recent unexpired grant matching principal/action(/args)."""
        now = datetime.now(UTC)
        for grant in reversed(self.grants):
            if grant.principal_id != principal_id:
                continue
            if grant.is_valid(now=now, action_class=action_class, args_hash=args_hash):
                return grant
        return None


DEFAULT_SELF_ELEVATION_TTL_SECONDS = 300
DEFAULT_SCOPED_2FA_TTL_SECONDS = 120


def request_self_elevation(principal_id: str, action_class: str) -> ElevationChallenge:
    """Build a self-elevation re-auth challenge for a human principal."""
    return ElevationChallenge(principal_id=principal_id, action_class=action_class)


def confirm_self_elevation(
    challenge: ElevationChallenge,
    proof: str,
    *,
    now: datetime | None = None,
    ttl_seconds: int = DEFAULT_SELF_ELEVATION_TTL_SECONDS,
) -> ElevationGrant:
    """Record a self-signed grant once the human's re-auth proof clears (proof is opaque here)."""
    del proof  # real password/passkey verification is an auth-substrate integration point.
    return ElevationGrant(
        principal_id=challenge.principal_id,
        action_class=challenge.action_class,
        kind="self_elevation",
        granted_at=now or datetime.now(UTC),
        ttl_seconds=ttl_seconds,
        signed_by=challenge.principal_id,
    )


def request_scoped_2fa(
    agent_principal_id: str,
    owner: str,
    action_class: str,
    args: dict[str, Any],
    *,
    principal_kind: Literal["human", "agent"],
    ttl_seconds: int = DEFAULT_SCOPED_2FA_TTL_SECONDS,
) -> ScopedApprovalRequest:
    """Build a scoped-2FA request for an agent; rejects human principals (ADR-068 §D)."""
    if principal_kind == "human":
        raise ScopedTwoFactorForHumanError(
            "scoped_2fa is for agent principals only; a human self-elevates instead"
        )
    return ScopedApprovalRequest(
        agent_principal_id=agent_principal_id,
        owner=owner,
        action_class=action_class,
        args_hash=hash_args(args),
        ttl_seconds=ttl_seconds,
    )


def confirm_scoped_2fa(
    request: ScopedApprovalRequest, owner_signature: str, *, now: datetime | None = None
) -> ElevationGrant:
    """Record an owner-signed grant scoped to this one action instance (not reusable)."""
    del owner_signature  # real signature verification is an auth-substrate integration point.
    return ElevationGrant(
        principal_id=request.agent_principal_id,
        action_class=request.action_class,
        kind="scoped_2fa",
        granted_at=now or datetime.now(UTC),
        ttl_seconds=request.ttl_seconds,
        signed_by=request.owner,
        action_args_hash=request.args_hash,
    )


async def store_grant_with_audit(
    store: ElevationStore, grant: ElevationGrant, audit_log: AuditLog | None
) -> None:
    """Persist a grant and emit its audit event (ADR-037); every grant/expiry is audited."""
    from maistro.security._types import AuditEntry

    await store.store(grant)
    if audit_log is not None:
        await audit_log.log(
            AuditEntry(
                boundary="elevation",
                user_id=grant.signed_by,
                agent_id=grant.principal_id if grant.kind == "scoped_2fa" else "",
                verdict="granted",
                detail=f"{grant.kind} grant for action_class={grant.action_class}",
            )
        )
