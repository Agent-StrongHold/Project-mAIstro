"""Pure Entra group-to-MAIstro entitlement policy for M3 #492.

This module deliberately does not authenticate users, create accounts, mutate
stores, or issue sessions.  #491 owns verified Entra identity.  This module is
the deterministic policy engine that a later product transaction can call after
identity and current group membership have both been established.

Security posture:
- JIT admission is disabled unless policy says otherwise.
- Group mappings use immutable Entra group object IDs, never display names.
- Incomplete/overage membership evidence is an error, never an empty group set.
- Multiple matching groups combine permissions by union and roles by explicit
  precedence.
- Optional role/permission ceilings are validated before policy activation.
- The result is explicitly SSO-managed state so callers can preserve unrelated
  local/manual grants during reconciliation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Mapping
from uuid import UUID

MembershipSource = Literal["token", "resolver"]


class EntraEntitlementPolicyError(ValueError):
    """The configured mapping is ambiguous, invalid, or exceeds its ceiling."""


class IncompleteGroupMembershipError(RuntimeError):
    """Current Entra group membership is not complete enough to authorize."""


def _group_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise EntraEntitlementPolicyError(
            "Entra group mappings and evidence must use group object UUIDs"
        ) from exc


def _nonempty_token(value: str, *, field: str) -> str:
    candidate = value.strip()
    if not candidate or len(candidate) > 128 or any(ord(ch) < 32 for ch in candidate):
        raise EntraEntitlementPolicyError(f"invalid {field}")
    return candidate


@dataclass(frozen=True)
class EntraGroupGrant:
    """One administrator-configured immutable group mapping."""

    role: str
    permissions: frozenset[str] = frozenset()

    def normalized(self) -> EntraGroupGrant:
        role = _nonempty_token(self.role, field="role")
        permissions = frozenset(
            _nonempty_token(permission, field="permission") for permission in self.permissions
        )
        return EntraGroupGrant(role=role, permissions=permissions)


@dataclass(frozen=True)
class EntraGroupMembership:
    """Trusted current membership evidence presented to the policy engine."""

    group_ids: tuple[str, ...]
    complete: bool
    source: MembershipSource

    @classmethod
    def complete_token(cls, group_ids: Iterable[str]) -> EntraGroupMembership:
        return cls(tuple(group_ids), True, "token")

    @classmethod
    def complete_resolver(cls, group_ids: Iterable[str]) -> EntraGroupMembership:
        return cls(tuple(group_ids), True, "resolver")

    @classmethod
    def incomplete_token(cls, group_ids: Iterable[str] = ()) -> EntraGroupMembership:
        """Represent omitted/truncated/overage claims before Graph resolution."""
        return cls(tuple(group_ids), False, "token")


@dataclass(frozen=True)
class SSOManagedEntitlements:
    """Entitlements whose provenance is Entra policy, not local administration."""

    role: str
    permissions: frozenset[str]
    matched_group_ids: tuple[str, ...]
    policy_version: str
    membership_source: MembershipSource


@dataclass(frozen=True)
class EntraAdmissionDecision:
    eligible: bool
    managed: SSOManagedEntitlements | None


@dataclass(frozen=True)
class EntraJitPolicy:
    """Validated group-gated JIT admission and managed-entitlement policy."""

    enabled: bool
    eligible_groups: Mapping[str, EntraGroupGrant]
    role_precedence: tuple[str, ...]
    policy_version: str
    max_role: str | None = None
    allowed_permissions: frozenset[str] | None = None

    def __post_init__(self) -> None:
        normalized_version = _nonempty_token(self.policy_version, field="policy_version")
        object.__setattr__(self, "policy_version", normalized_version)

        precedence = tuple(_nonempty_token(role, field="role") for role in self.role_precedence)
        if not precedence or len(set(precedence)) != len(precedence):
            raise EntraEntitlementPolicyError("role_precedence must be non-empty and unique")
        object.__setattr__(self, "role_precedence", precedence)

        normalized: dict[str, EntraGroupGrant] = {}
        for raw_group_id, raw_grant in self.eligible_groups.items():
            group_id = _group_id(raw_group_id)
            if group_id in normalized:
                raise EntraEntitlementPolicyError("duplicate Entra group object ID")
            grant = raw_grant.normalized()
            if grant.role not in precedence:
                raise EntraEntitlementPolicyError(
                    f"mapped role {grant.role!r} is absent from role_precedence"
                )
            normalized[group_id] = grant
        object.__setattr__(self, "eligible_groups", normalized)

        ceiling = self.max_role
        if ceiling is not None:
            ceiling = _nonempty_token(ceiling, field="max_role")
            if ceiling not in precedence:
                raise EntraEntitlementPolicyError("max_role is absent from role_precedence")
            object.__setattr__(self, "max_role", ceiling)

        allowed = self.allowed_permissions
        if allowed is not None:
            normalized_allowed = frozenset(
                _nonempty_token(permission, field="permission") for permission in allowed
            )
            object.__setattr__(self, "allowed_permissions", normalized_allowed)

        self._validate_ceiling()

    def _validate_ceiling(self) -> None:
        if self.max_role is not None:
            max_index = self.role_precedence.index(self.max_role)
            too_powerful = sorted(
                group_id
                for group_id, grant in self.eligible_groups.items()
                if self.role_precedence.index(grant.role) > max_index
            )
            if too_powerful:
                raise EntraEntitlementPolicyError(
                    "group mapping grants a role above the configured SSO ceiling"
                )

        if self.allowed_permissions is not None:
            excess = sorted(
                permission
                for grant in self.eligible_groups.values()
                for permission in grant.permissions
                if permission not in self.allowed_permissions
            )
            if excess:
                raise EntraEntitlementPolicyError(
                    "group mapping grants permission outside the configured SSO ceiling"
                )

    def evaluate(self, membership: EntraGroupMembership) -> EntraAdmissionDecision:
        """Return deterministic admission + SSO-managed entitlements.

        Callers MUST resolve an overage/incomplete token through the configured
        authoritative membership resolver before calling again.  We refuse to
        reinterpret incomplete evidence as an empty set because that would make
        directory/API failure change authorization semantics silently.
        """
        if not membership.complete:
            raise IncompleteGroupMembershipError(
                "Entra group membership is incomplete; authoritative resolution is required"
            )
        if not self.enabled:
            return EntraAdmissionDecision(eligible=False, managed=None)

        groups = tuple(sorted({_group_id(group_id) for group_id in membership.group_ids}))
        matched = tuple(group_id for group_id in groups if group_id in self.eligible_groups)
        if not matched:
            return EntraAdmissionDecision(eligible=False, managed=None)

        grants = [self.eligible_groups[group_id] for group_id in matched]
        selected_role = max(
            (grant.role for grant in grants),
            key=self.role_precedence.index,
        )
        permissions = frozenset(
            permission for grant in grants for permission in grant.permissions
        )
        return EntraAdmissionDecision(
            eligible=True,
            managed=SSOManagedEntitlements(
                role=selected_role,
                permissions=permissions,
                matched_group_ids=matched,
                policy_version=self.policy_version,
                membership_source=membership.source,
            ),
        )


__all__ = [
    "EntraAdmissionDecision",
    "EntraEntitlementPolicyError",
    "EntraGroupGrant",
    "EntraGroupMembership",
    "EntraJitPolicy",
    "IncompleteGroupMembershipError",
    "SSOManagedEntitlements",
]
