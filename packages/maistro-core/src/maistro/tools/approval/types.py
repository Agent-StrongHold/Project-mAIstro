"""Approval gate types (SPEC-253 / ADR-051)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ApprovalTarget = Literal["plan", "call"]
ApprovalOutcome = Literal["approved", "denied", "timeout"]


@dataclass(frozen=True)
class ApprovalDecision:
    task_id: str
    target: ApprovalTarget
    outcome: ApprovalOutcome
    latency_ms: int
    decided_by: str


@dataclass(frozen=True)
class Impact:
    dimension: str
    value: float


@dataclass(frozen=True)
class Threshold:
    dimension: str
    gt: float
