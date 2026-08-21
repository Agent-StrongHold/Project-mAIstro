"""Built-in approval inbox — the baseline `approval` provider (SPEC-184/187).

Needs no external service: request() creates a pending item and awaits an
asyncio.Event resolved by the UI/CLI/API via resolve()."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from maistro.capabilities.slots.approval import ApprovalDecision, ApprovalRequest
from maistro.capabilities.types import ProviderHealth


@dataclass
class _Pending:
    req: ApprovalRequest
    event: asyncio.Event
    decision: ApprovalDecision | None = None


class InboxApproval:
    """Baseline approval provider backed by an in-process pending queue."""

    def __init__(self) -> None:
        self._pending: dict[str, _Pending] = {}

    # --- CapabilityProvider ---
    @property
    def name(self) -> str:
        return "inbox"

    @property
    def slot(self) -> str:
        return "approval"

    @property
    def trust_tier(self) -> str:
        return "t0"

    def requires(self) -> tuple[str, ...]:
        return ()

    async def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)

    # --- Approval ---
    async def request(self, req: ApprovalRequest) -> ApprovalDecision:
        pending = _Pending(req=req, event=asyncio.Event())
        self._pending[req.request_id] = pending
        await pending.event.wait()
        decision = pending.decision
        self._pending.pop(req.request_id, None)
        if decision is None:  # pragma: no cover - decision is always set before event fires
            raise RuntimeError("approval resolved without a decision")
        return decision

    # --- UI/CLI/API surface ---
    def pending(self) -> list[ApprovalRequest]:
        return [p.req for p in self._pending.values()]

    def resolve(self, request_id: str, *, approved: bool, actor: str = "") -> bool:
        pending = self._pending.get(request_id)
        if pending is None:
            return False
        pending.decision = ApprovalDecision(request_id=request_id, approved=approved, actor=actor)
        pending.event.set()
        return True
