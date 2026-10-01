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

    @staticmethod
    def _frozen_str_set(raw: object) -> frozenset[str]:
        """Coerce a legacy collection field to a ``frozenset[str]``."""
        if isinstance(raw, (list, tuple, set, frozenset)):
            return frozenset(str(item) for item in raw)
        return frozenset()

    @classmethod
    def _roles_from_legacy(cls, user: Mapping[str, Any]) -> frozenset[str]:
        """A single legacy ``role`` overrides a ``roles`` collection."""
        role = user.get("role")
        if role is not None:
            return frozenset({str(role)})
        return cls._frozen_str_set(user.get("roles"))

    @classmethod
    def from_legacy_dict(cls, user: Mapping[str, Any]) -> Principal:
        """Bridge hive ``request.state.user`` dicts during cutover migration."""
        org_id = user.get("org_id")
        return cls(
            user_id=str(user.get("id") or user.get("user_id") or ""),
            roles=cls._roles_from_legacy(user),
            scopes=cls._frozen_str_set(user.get("scopes")),
            workspace_ids=cls._frozen_str_set(user.get("workspace_ids") or user.get("workspaces")),
            org_id=str(org_id) if org_id is not None else None,
            team_ids=cls._frozen_str_set(user.get("team_ids")),
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
