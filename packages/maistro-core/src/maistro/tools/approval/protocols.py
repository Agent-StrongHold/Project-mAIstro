"""Approval gate Protocol (SPEC-253 / ADR-051)."""

from __future__ import annotations

from typing import Protocol

from maistro.tools.approval.types import ApprovalDecision, Impact


class ApprovalGate(Protocol):
    async def request_plan_approval(
        self, task_id: str, irreversible_calls: tuple[str, ...]
    ) -> ApprovalDecision: ...

    async def request_escalation(
        self, task_id: str, call: str, impacts: tuple[Impact, ...]
    ) -> ApprovalDecision: ...
