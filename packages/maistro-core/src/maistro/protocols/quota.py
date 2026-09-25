"""Quota tracker protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class QuotaTracker(Protocol):
    """Tracks token usage per provider per billing cycle."""

    async def record_usage(
        self,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, object]:
        """Record token usage. Returns updated totals."""
        ...

    async def record_invocation(
        self,
        invocation_id: str,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
        usage_reported: bool,
    ) -> dict[str, object]:
        """Record one canonical physical Invocation at most once.

        ``usage_reported=False`` is evidence that the provider call happened
        without token accounting; it must remain visible as unreported rather
        than becoming a measured zero.
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
        """Get usage records for dashboards, including incomplete evidence.

        Rows with ``usage_complete=False`` contain at least one provider call
        whose token report was unavailable; their percentage must not be
        presented as a complete accounting of provider spend.
        """
        ...
