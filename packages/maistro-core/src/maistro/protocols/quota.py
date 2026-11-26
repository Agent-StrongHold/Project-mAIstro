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
    ) -> float | None:
        """Usage as a fraction of the free allowance (0.0 to 1.0+), or ``None``.

        ``None`` means the provider/cycle carries incomplete evidence (at
        least one call recorded without a provider usage report): the true
        ratio is unknowable and must not be presented as a measured value —
        in particular not as ``0.0`` with full headroom, which would read as
        complete accounting while omitting spend (#718). A provider/cycle
        with no recorded call at all is vacuously complete and returns ``0.0``.
        """
        ...

    async def get_all_usage(self) -> list[dict[str, object]]:
        """Get usage records for dashboards, including incomplete evidence.

        Rows with ``usage_complete=False`` contain at least one provider call
        whose token report was unavailable; their percentage must not be
        presented as a complete accounting of provider spend.
        """
        ...
