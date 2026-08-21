"""Authenticated principal for maistro-server HTTP APIs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: str
    token: str
    roles: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles
