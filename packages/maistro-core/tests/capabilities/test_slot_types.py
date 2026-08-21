from __future__ import annotations

from maistro.capabilities.slots.approval import ApprovalDecision, ApprovalRequest
from maistro.capabilities.slots.infra import ActionTier, InfraHealth, ResourceHealth


def test_infra_health_shape():
    h = InfraHealth(
        ts="2026-05-30T00:00:00Z",
        resources={"gpu": ResourceHealth(status="ok", detail={})},
    )
    assert h.resources["gpu"].status == "ok"


def test_action_tier_values():
    assert {t.value for t in ActionTier} == {"read", "reversible", "destructive"}


def test_approval_request_and_decision():
    req = ApprovalRequest(
        action="restart_stack",
        params={"name": "traefik"},
        tier="destructive",
        requester="self_repair",
        rationale="traefik unhealthy",
    )
    dec = ApprovalDecision(request_id=req.request_id, approved=True, actor="blake")
    assert dec.request_id == req.request_id and dec.approved is True
