"""Tests for maistro.tools.approval.protocols — ApprovalGate Protocol."""

from __future__ import annotations

import pytest

from maistro.tools.approval.protocols import ApprovalGate
from maistro.tools.approval.types import ApprovalDecision, Impact


class _FakeGate:
    async def request_plan_approval(
        self, task_id: str, irreversible_calls: tuple[str, ...]
    ) -> ApprovalDecision:
        return ApprovalDecision(
            task_id=task_id, target="plan", outcome="approved", latency_ms=1, decided_by="user"
        )

    async def request_escalation(
        self, task_id: str, call: str, impacts: tuple[Impact, ...]
    ) -> ApprovalDecision:
        return ApprovalDecision(
            task_id=task_id, target="call", outcome="denied", latency_ms=1, decided_by="user"
        )


class TestApprovalGateProtocol:
    @pytest.mark.asyncio
    async def test_conforming_implementation_satisfies_protocol(self) -> None:
        gate: ApprovalGate = _FakeGate()
        decision = await gate.request_plan_approval("t1", ("rm -rf",))
        assert decision.outcome == "approved"

    @pytest.mark.asyncio
    async def test_request_escalation(self) -> None:
        gate: ApprovalGate = _FakeGate()
        decision = await gate.request_escalation("t1", "deploy", ())
        assert decision.outcome == "denied"
