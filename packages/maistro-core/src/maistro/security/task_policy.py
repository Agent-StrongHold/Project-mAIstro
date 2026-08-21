"""Task acceptance policy -- gate for task creation with budget enforcement.

Evaluates: (user, agent, "task_create") -> allow/deny
Budget rules: (user, budget_tier, "budget") -> allow/deny
"""

from __future__ import annotations

import logging
import math
from typing import Protocol, runtime_checkable

logger = logging.getLogger("maistro.security.task_policy")


@runtime_checkable
class TaskAcceptancePolicy(Protocol):
    def check_task_creation(
        self,
        user_id: str,
        agent_name: str,
    ) -> bool: ...

    def check_budget(
        self,
        user_id: str,
        priority_tier: str,
        token_budget: float | None = None,
        cost_budget: float | None = None,
        wall_clock_seconds: float | None = None,
    ) -> bool: ...


class InMemoryTaskAcceptancePolicy:
    """In-memory task acceptance policy with configurable limits."""

    def __init__(self) -> None:
        self._denied_agents: set[tuple[str, str]] = set()
        self._base_budget: dict[str, dict[str, float]] = {
            "P0": {"max_cost": 10.0, "max_seconds": 300},
            "P1": {"max_cost": 5.0, "max_seconds": 600},
            "P2": {"max_cost": 20.0, "max_seconds": 3600},
            "P3": {"max_cost": 10.0, "max_seconds": 1800},
            "P4": {"max_cost": 50.0, "max_seconds": 7200},
            "P5": {"max_cost": 100.0, "max_seconds": 14400},
        }
        self._base_tokens_per_tier: dict[str, float] = {
            "P0": 200_000,
            "P1": 150_000,
            "P2": 100_000,
            "P3": 75_000,
            "P4": 50_000,
            "P5": 25_000,
        }

    def _calculate_token_budget(self, priority_tier: str) -> float:
        base_tokens = self._base_tokens_per_tier.get(priority_tier, 100_000)
        priority = int(priority_tier[1:])
        return base_tokens / math.log2(priority + 2)

    def deny_agent(self, user_id: str, agent_name: str) -> None:
        self._denied_agents.add((user_id, agent_name))

    def set_budget_limit(
        self,
        tier: str,
        max_tokens: float | None = None,
        max_cost: float | None = None,
        max_seconds: float | None = None,
    ) -> None:
        if max_tokens is not None:
            self._base_tokens_per_tier[tier] = max_tokens
        if max_cost is not None:
            self._base_budget[tier]["max_cost"] = max_cost
        if max_seconds is not None:
            self._base_budget[tier]["max_seconds"] = max_seconds

    def check_task_creation(
        self,
        user_id: str,
        agent_name: str,
    ) -> bool:
        if (user_id, agent_name) in self._denied_agents:
            logger.warning(
                "Task creation DENIED: user=%s agent=%s",
                user_id,
                agent_name,
            )
            return False
        return True

    def check_budget(
        self,
        user_id: str,
        priority_tier: str,
        token_budget: float | None = None,
        cost_budget: float | None = None,
        wall_clock_seconds: float | None = None,
    ) -> bool:
        if priority_tier not in self._base_budget:
            logger.warning(
                "Budget DENIED: user=%s unknown tier=%s",
                user_id,
                priority_tier,
            )
            return False
        limits = self._base_budget[priority_tier]

        if token_budget is not None:
            max_tokens = self._calculate_token_budget(priority_tier)
            if token_budget > max_tokens:
                logger.warning(
                    "Budget check failed: user=%s tier=%s (token budget exceeded)",
                    user_id,
                    priority_tier,
                )
                return False

        if cost_budget is not None and cost_budget > limits.get("max_cost", float("inf")):
            logger.warning(
                "Budget check failed: user=%s tier=%s (cost budget exceeded)",
                user_id,
                priority_tier,
            )
            return False

        max_seconds = limits.get("max_seconds", float("inf"))
        if wall_clock_seconds is not None and wall_clock_seconds > max_seconds:
            logger.warning(
                "Budget check failed: user=%s tier=%s (time budget exceeded)",
                user_id,
                priority_tier,
            )
            return False

        return True
