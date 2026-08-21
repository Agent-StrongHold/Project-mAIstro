"""approval slot types and protocol (SPEC-187)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from maistro.capabilities.protocols import CapabilityProvider


@dataclass(frozen=True)
class ApprovalRequest:
    action: str
    params: dict[str, Any]
    tier: str
    requester: str
    rationale: str = ""
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class ApprovalDecision:
    request_id: str
    approved: bool
    actor: str = ""


@runtime_checkable
class Approval(CapabilityProvider, Protocol):
    async def request(self, req: ApprovalRequest) -> ApprovalDecision:
        """Create a pending approval and return the decision once resolved."""
        ...
