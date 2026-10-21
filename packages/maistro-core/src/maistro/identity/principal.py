"""Canonical HTTP request principal (Workspace cutover P0.1 / ADR-068).

Every authenticated HTTP boundary must construct and pass this type instead of
a dict-shaped ``request.state.user``. Crypto identity (BIP39 seed, agent DID)
lives in sibling modules under ``maistro.identity``; this module is the
cross-service actor on an API request.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def _frozenset_str(value: object | None) -> frozenset[str]:
    if isinstance(value, (list, tuple, set, frozenset)):
        return frozenset(str(item) for item in value)
    return frozenset()


def _roles_from_user(user: Mapping[str, Any]) -> frozenset[str]:
    role = user.get("role")
    if role is not None:
        return frozenset({str(role)})
    return _frozenset_str(user.get("roles"))


def _workspace_ids_from_user(user: Mapping[str, Any]) -> frozenset[str]:
    raw = user.get("workspace_ids") or user.get("workspaces")
    return _frozenset_str(raw)


@dataclass(frozen=True, slots=True)
class Principal:
    """One principal crosses each service boundary (P0.1 / AC-P1)."""

    user_id: str
    roles: frozenset[str] = frozenset()
    scopes: frozenset[str] = frozenset()
    workspace_ids: frozenset[str] = frozenset()
    org_id: str | None = None
    team_ids: frozenset[str] = frozenset()
    username: str | None = None
    permissions: frozenset[str] = frozenset()
    elevated_permissions: frozenset[str] = frozenset()

    @property
    def primary_role(self) -> str | None:
        if not self.roles:
            return None
        return next(iter(sorted(self.roles)))

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    def actor_id(self) -> str:
        """Stable principal identifier for ownership checks and audit."""
        return self.user_id or (self.username or "")

    def audit_label(self) -> str:
        """Human-readable principal label for audit entries."""
        return self.username or self.user_id or "unverified"

    def has_permission(self, perm: str) -> bool:
        """Task-scoped elevation: perm must be granted and currently elevated."""
        if self.is_admin:
            return True
        if perm not in self.permissions:
            return False
        return perm in self.elevated_permissions

    @classmethod
    def from_legacy_dict(cls, user: Mapping[str, Any]) -> Principal:
        """Bridge hive session dicts during cutover migration."""
        user_id = str(user.get("id") or user.get("user_id") or "")
        org_id = user.get("org_id")
        username = user.get("username")
        return cls(
            user_id=user_id,
            roles=_roles_from_user(user),
            scopes=_frozenset_str(user.get("scopes")),
            workspace_ids=_workspace_ids_from_user(user),
            org_id=str(org_id) if org_id is not None else None,
            team_ids=_frozenset_str(user.get("team_ids")),
            username=str(username) if username is not None else None,
            permissions=_frozenset_str(user.get("permissions")),
            elevated_permissions=_frozenset_str(user.get("elevated_permissions")),
        )

    def to_legacy_dict(self) -> dict[str, Any]:
        """Temporary adapter for code not yet migrated off dict principals."""
        payload: dict[str, Any] = {"id": self.user_id, "roles": sorted(self.roles)}
        if self.primary_role is not None:
            payload["role"] = self.primary_role
        if self.username is not None:
            payload["username"] = self.username
        if self.scopes:
            payload["scopes"] = sorted(self.scopes)
        if self.workspace_ids:
            payload["workspace_ids"] = sorted(self.workspace_ids)
        if self.org_id is not None:
            payload["org_id"] = self.org_id
        if self.team_ids:
            payload["team_ids"] = sorted(self.team_ids)
        if self.permissions:
            payload["permissions"] = sorted(self.permissions)
        if self.elevated_permissions:
            payload["elevated_permissions"] = sorted(self.elevated_permissions)
        return payload
