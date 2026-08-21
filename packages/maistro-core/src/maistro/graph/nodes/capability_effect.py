"""Canonical capability-effect adapter for Graph Nodes.

Capability policy may require a durable human decision before an external effect
can run. Graph already owns durable pause/resume semantics, so Nodes translate
the capability-layer pending signal into the existing ``pause_until`` contract
instead of inventing a parallel HITL lifecycle.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from maistro.capabilities.governed_invocation import InvocationApprovalPending

from .base import pause_until

T = TypeVar("T")


async def invoke_capability_effect(
    operation: Callable[[], Awaitable[T]],
    *,
    effect_key: str,
) -> T:
    """Run a governed capability effect or durably pause for human approval."""

    try:
        return await operation()
    except InvocationApprovalPending as exc:
        pause_until(
            "awaiting_human_approval",
            metadata={
                "approval_request_id": exc.request_id,
                "effect_key": effect_key,
            },
        )
        raise AssertionError("pause_until must raise") from exc  # pragma: no cover


__all__ = ["invoke_capability_effect"]
