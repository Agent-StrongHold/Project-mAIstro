"""Quota tracker protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# Callers reuse this identity when a usage write is retried after an
# ambiguous database result. Omitting it means this is a new observation.
UsageEventId = str


@runtime_checkable
class QuotaTracker(Protocol):
    """Tracks token usage per provider per billing cycle."""

    async def record_usage(
        self,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
        event_id: UsageEventId | None = None,
    ) -> dict[str, object]:
        """Record token usage once for ``event_id`` and return updated totals.

        Implementations generate an identity when one is omitted for backwards
        compatibility. Retry-capable callers must pass the same identity for
        every attempt to record one observed invocation.
        """
        ...

    async def get_usage_pct(
        self,
        provider: str,
        billing_cycle: str,
        free_tokens: int,
    ) -> float:
        """Get usage as a percentage of free tier (0.0 to 1.0+)."""
        ...

    async def get_all_usage(self) -> list[dict[str, object]]:
        """Get all usage records for dashboard."""
        ...
