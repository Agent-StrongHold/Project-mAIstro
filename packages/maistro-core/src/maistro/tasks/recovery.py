"""Crash-loop quarantine policy and version-drift check (SPEC-256 / ADR-056)."""

from __future__ import annotations

from maistro.agents.circuit_breaker import CircuitBreaker
from maistro.tasks.checkpoint import TaskCheckpoint


class CrashLoopPolicy:
    def record_crash(self, breaker: CircuitBreaker) -> None:
        breaker.record_failure()

    def should_quarantine(self, breaker: CircuitBreaker) -> bool:
        return not breaker.allow_request()


def version_compatible(
    checkpoint: TaskCheckpoint,
    *,
    current_recipe_version: str,
    current_code_registry_version: str,
) -> bool:
    return (
        checkpoint.recipe_version == current_recipe_version
        and checkpoint.code_registry_version == current_code_registry_version
    )
