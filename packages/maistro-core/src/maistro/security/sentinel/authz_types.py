"""Authorization tier ladder types (SPEC-245 / ADR-068 §B,F)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal


class Tier(StrEnum):
    OPEN = "open"
    ROLE_AUTO = "role_team_auto"
    SELF_ELEVATION = "self_elevation"
    DELEGATED = "delegated_approval"
    ADMIN = "admin_elevation"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class Principal:
    """A human or agent acting on a request (ADR-068 §A)."""

    id: str
    kind: Literal["human", "agent"]
    roles: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    owner: str | None = None  # required when kind == "agent"


@dataclass(frozen=True)
class AuthzDecision:
    tier: Tier
    authorized: bool
    needs: Literal["none", "self_elevation", "scoped_2fa", "delegated", "admin"]
    approver_scope: str | None
    within_budget: bool
    rlphd: Any | None
    reason: str
