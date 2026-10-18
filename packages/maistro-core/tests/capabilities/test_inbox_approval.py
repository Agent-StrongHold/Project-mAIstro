from __future__ import annotations

import asyncio

from maistro.capabilities.providers.approval_inbox import InboxApproval
from maistro.capabilities.slots.approval import ApprovalRequest


async def test_request_blocks_until_resolved():
    inbox = InboxApproval()
    req = ApprovalRequest(
        action="restart_stack", params={}, tier="destructive", requester="self_repair"
    )

    async def approve_soon():
        await asyncio.sleep(0.01)
        assert any(p.request_id == req.request_id for p in inbox.pending())
        inbox.resolve(req.request_id, approved=True, actor="blake")

    decision, _ = await asyncio.gather(inbox.request(req), approve_soon())
    assert decision.approved is True and decision.actor == "blake"
    assert inbox.pending() == []


async def test_deny():
    inbox = InboxApproval()
    req = ApprovalRequest(action="docker_prune", params={}, tier="destructive", requester="op")
    asyncio.get_running_loop().call_soon(
        lambda: inbox.resolve(req.request_id, approved=False, actor="blake")
    )
    decision = await inbox.request(req)
    assert decision.approved is False


def test_is_capability_provider():
    from maistro.capabilities.protocols import CapabilityProvider

    assert isinstance(InboxApproval(), CapabilityProvider)


async def test_resolve_accepts_a_mapping_authority():
    """UI/API resolve() callers hand over plain mappings, not dataclasses."""

    inbox = InboxApproval()
    req = ApprovalRequest(action="run_workflow", params={}, tier="policy", requester="chat")

    async def resolve_soon():
        await asyncio.sleep(0.01)
        assert inbox.resolve(
            req.request_id,
            approved=True,
            actor="admin-1",
            authority={
                "kind": "human",
                "principal": "admin-1",
                "scope": "run_workflow",
                "evidence_id": req.request_id,
                "signature": "sig-1",
            },
        )

    decision, _ = await asyncio.gather(inbox.request(req), resolve_soon())
    assert decision.approved is True
    assert decision.authority is not None
    assert decision.authority.kind == "human"
    assert decision.authority.principal == "admin-1"
    assert decision.authority.scope == "run_workflow"
    assert decision.authority.signature == "sig-1"


async def _resolve_with(inbox: InboxApproval, req: ApprovalRequest, authority: object) -> None:
    """Resolve a pending request from a concurrent task, as the UI/API would."""

    await asyncio.sleep(0.01)
    assert inbox.resolve(req.request_id, approved=True, actor="admin-1", authority=authority)  # type: ignore[arg-type]


async def test_resolve_sanitizes_an_unusable_mapping_authority():
    """A malformed authority mapping resolves without authority, not without a decision."""

    for bad_authority in (
        {"kind": "robot", "principal": "p", "scope": "run_workflow", "evidence_id": "e"},
        {"kind": "human"},  # missing principal/scope/evidence_id
    ):
        inbox = InboxApproval()
        req = ApprovalRequest(action="run_workflow", params={}, tier="policy", requester="chat")

        decision, _ = await asyncio.gather(
            inbox.request(req), _resolve_with(inbox, req, bad_authority)
        )
        assert decision.approved is True
        assert decision.authority is None
