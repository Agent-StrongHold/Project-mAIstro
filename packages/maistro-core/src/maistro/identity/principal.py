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

    @property
    def primary_role(self) -> str | None:
        if not self.roles:
            return None
        return next(iter(sorted(self.roles)))

    @classmethod
    def from_legacy_dict(cls, user: Mapping[str, Any]) -> Principal:
        """Bridge hive ``request.state.user`` dicts during cutover migration."""
        user_id = str(user.get("id") or user.get("user_id") or "")
        org_id = user.get("org_id")
        return cls(
            user_id=user_id,
            roles=_roles_from_user(user),
            scopes=_frozenset_str(user.get("scopes")),
            workspace_ids=_workspace_ids_from_user(user),
            org_id=str(org_id) if org_id is not None else None,
            team_ids=_frozenset_str(user.get("team_ids")),
        )

    def to_legacy_dict(self) -> dict[str, Any]:
        """Temporary adapter for code not yet migrated off dict principals."""
        payload: dict[str, Any] = {"id": self.user_id, "roles": sorted(self.roles)}
        if self.primary_role is not None:
            payload["role"] = self.primary_role
        if self.scopes:
            payload["scopes"] = sorted(self.scopes)
        if self.workspace_ids:
            payload["workspace_ids"] = sorted(self.workspace_ids)
        if self.org_id is not None:
            payload["org_id"] = self.org_id
        if self.team_ids:
            payload["team_ids"] = sorted(self.team_ids)
        return payload
