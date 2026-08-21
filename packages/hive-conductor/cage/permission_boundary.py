"""Permission boundary — Turing can never escalate its own tier.

Tier hierarchy (lowest → highest):
  0: sandbox   — can only read/write ephemeral memory, no tool calls
  1: worker    — can call approved tools, read durable memory
  2: operator  — can write durable memory, run DAGs
  3: admin     — can modify configs, approve proposals (HUMAN ONLY)

Rules:
  - Turing starts at tier assigned by human admin
  - Turing can NEVER request or grant itself a higher tier
  - Turing can NEVER modify the tier of any other agent
  - Only tier 3 (admin/human) can change tier assignments
  - Tier checks are enforced at the cage level, not the application level
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Tier(IntEnum):
    SANDBOX = 0
    WORKER = 1
    OPERATOR = 2
    ADMIN = 3


@dataclass(frozen=True)
class EscalationAttempt:
    agent_id: str
    current_tier: Tier
    requested_tier: Tier
    reason: str


class PermissionBoundary:
    """Enforces tier boundaries. All escalation attempts are logged and blocked."""

    def __init__(self) -> None:
        self._violations: list[EscalationAttempt] = []

    def check_escalation(
        self, agent_id: str, current: Tier, requested: Tier
    ) -> EscalationAttempt | None:
        if requested > current:
            v = EscalationAttempt(agent_id, current, requested, "self-escalation blocked")
            self._violations.append(v)
            return v
        return None

    def check_tier_modification(
        self, actor_id: str, actor_tier: Tier, target_id: str, new_tier: Tier
    ) -> EscalationAttempt | None:
        if actor_tier < Tier.ADMIN:
            v = EscalationAttempt(
                actor_id,
                actor_tier,
                Tier.ADMIN,
                f"only admin can modify tiers; tried to set {target_id} to {new_tier.name}",
            )
            self._violations.append(v)
            return v
        return None

    def can_call_tool(self, tier: Tier) -> bool:
        return tier >= Tier.WORKER

    def can_write_durable(self, tier: Tier) -> bool:
        return tier >= Tier.OPERATOR

    def can_run_dag(self, tier: Tier) -> bool:
        return tier >= Tier.OPERATOR

    def can_modify_config(self, tier: Tier) -> bool:
        return tier >= Tier.ADMIN

    @property
    def violations(self) -> list[EscalationAttempt]:
        return list(self._violations)
