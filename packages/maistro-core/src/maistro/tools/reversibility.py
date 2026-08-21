"""Tool reversibility taxonomy types (SPEC-252 / ADR-050)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ToolReversibility(StrEnum):
    INTERNAL = "internal"
    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"


@dataclass(frozen=True)
class ToolRegistration:
    name: str
    reversibility: ToolReversibility
    compensator: str | None = None
    impact_estimator: str | None = None
    idempotency_key: str | None = None


class ToolRegistrationError(Exception):
    pass


def default_for_external() -> ToolReversibility:
    return ToolReversibility.IRREVERSIBLE
