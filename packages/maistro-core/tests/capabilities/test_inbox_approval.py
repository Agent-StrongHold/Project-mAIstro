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
