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

#: What a legacy dict may have put in a collection field. A caller that
#: produced a bare string gets an empty set rather than a set of characters.
_COLLECTION_TYPES = (list, tuple, set, frozenset)


def _string_set(value: Any) -> frozenset[str]:
    """Coerce one legacy collection field, however it was serialized.

    Four fields -- roles, scopes, workspace_ids, team_ids -- arrive from
    `request.state.user` in whatever shape the producing code happened to use,
    and each repeated this same isinstance-or-empty dance inline. One named
    rule is shorter and is the only place to change if the accepted shapes
    ever do.
    """

    if isinstance(value, _COLLECTION_TYPES):
        return frozenset(str(item) for item in value)
    return frozenset()


def _legacy_roles(user: Mapping[str, Any]) -> frozenset[str]:
    """The roles a legacy principal claims, from either spelling.

    Singular ``role`` wins when both are present: a dict carrying both was
    narrowed to a single role somewhere in older code, and reading the plural
    there would widen it back.
    """

    role = user.get("role")
    if role is not None:
        return frozenset({str(role)})
    return _string_set(user.get("roles"))


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
        org_id = user.get("org_id")
        return cls(
            user_id=str(user.get("id") or user.get("user_id") or ""),
            roles=_legacy_roles(user),
            scopes=_string_set(user.get("scopes")),
            workspace_ids=_string_set(user.get("workspace_ids") or user.get("workspaces")),
            org_id=str(org_id) if org_id is not None else None,
            team_ids=_string_set(user.get("team_ids")),
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
