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
        role = user.get("role")
        roles: frozenset[str]
        if role is not None:
            roles = frozenset({str(role)})
        else:
            raw_roles = user.get("roles")
            if isinstance(raw_roles, (list, tuple, set, frozenset)):
                roles = frozenset(str(item) for item in raw_roles)
            else:
                roles = frozenset()
        raw_scopes = user.get("scopes")
        scopes = (
            frozenset(str(item) for item in raw_scopes)
            if isinstance(raw_scopes, (list, tuple, set, frozenset))
            else frozenset()
        )
        raw_workspaces = user.get("workspace_ids") or user.get("workspaces")
        workspace_ids = (
            frozenset(str(item) for item in raw_workspaces)
            if isinstance(raw_workspaces, (list, tuple, set, frozenset))
            else frozenset()
        )
        org_id = user.get("org_id")
        raw_teams = user.get("team_ids")
        team_ids = (
            frozenset(str(item) for item in raw_teams)
            if isinstance(raw_teams, (list, tuple, set, frozenset))
            else frozenset()
        )
        return cls(
            user_id=user_id,
            roles=roles,
            scopes=scopes,
            workspace_ids=workspace_ids,
            org_id=str(org_id) if org_id is not None else None,
            team_ids=team_ids,
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
