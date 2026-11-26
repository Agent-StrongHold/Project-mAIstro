"""Quota tracker: token usage recording per provider per billing cycle."""

from __future__ import annotations

from collections import defaultdict
from uuid import uuid4

from maistro.quota.billing import cycle_key

UsagePayload = tuple[str, str, int, int]


class InMemoryQuotaTracker:
    def __init__(self) -> None:
        self._invocations: set[str] = set()
        self._unreported: dict[tuple[str, str], int] = defaultdict(int)
        self._usage: dict[tuple[str, str], dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "request_count": 0},
        )
        self._events: dict[str, UsagePayload] = {}

    async def record_usage(
        self,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
        event_id: str | None = None,
    ) -> dict[str, object]:
        event_id = event_id or uuid4().hex
        key = (provider, cycle_key(billing_cycle))
        payload = (provider, key[1], input_tokens, output_tokens)
        previous = self._events.get(event_id)
        if previous is not None:
            if previous != payload:
                raise ValueError(f"event_id {event_id!r} was reused with different usage")
            return {"provider": provider, "cycle_key": key[1], **self._usage[key]}

        self._events[event_id] = payload
        entry = self._usage[key]
        entry["input_tokens"] += input_tokens
        entry["output_tokens"] += output_tokens
        entry["total_tokens"] += input_tokens + output_tokens
        entry["request_count"] += 1
        return {"provider": provider, "cycle_key": key[1], **entry}

    async def record_invocation(
        self,
        invocation_id: str,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
        usage_reported: bool,
    ) -> dict[str, object]:
        """Record one physical Invocation once, including missing evidence."""
        key = (provider, cycle_key(billing_cycle))
        if invocation_id in self._invocations:
            return self._snapshot(provider, key)
        self._invocations.add(invocation_id)
        if usage_reported:
            return await self.record_usage(provider, billing_cycle, input_tokens, output_tokens)
        return await self.record_unreported(provider, billing_cycle)

    async def record_unreported(self, provider: str, billing_cycle: str) -> dict[str, object]:
        """Keep missing provider usage visible without charging zero tokens."""
        key = (provider, cycle_key(billing_cycle))
        self._unreported[key] += 1
        entry = self._usage[key]
        entry["request_count"] += 1
        return self._snapshot(provider, key)

    def _snapshot(self, provider: str, key: tuple[str, str]) -> dict[str, object]:
        result: dict[str, object] = {"provider": provider, "cycle_key": key[1], **self._usage[key]}
        unreported = self._unreported.get(key, 0)
        if unreported:
            result["unreported_count"] = unreported
            result["usage_complete"] = False
        return result

    async def get_usage_pct(
        self,
        provider: str,
        billing_cycle: str,
        free_tokens: int,
    ) -> float | None:
        """Usage as a fraction of the free allowance, or ``None`` when unknown.

        #718: a provider/cycle whose evidence is incomplete (at least one call
        recorded without a provider usage report) must not present a measured
        percentage. The unreported call's tokens are unknowable, so any ratio
        computed over the reported remainder would read as complete while
        understating spend — the false ``0.0``/full-headroom presentation this
        method used to produce. Callers convey ``None`` as "usage unknown",
        never as zero.
        """
        if free_tokens <= 0:
            return 0.0
        key = (provider, cycle_key(billing_cycle))
        entry = self._usage.get(key)
        if entry is None:
            # No call was ever recorded for this provider/cycle: vacuously
            # complete, a measured zero, not missing evidence.
            return 0.0
        # Unreported calls live in their own map, not folded into the usage
        # aggregate, so the aggregate stays pure measured tokens. This read has
        # to consult both or an incomplete cycle presents as a measured ratio
        # over the reported remainder -- the false full-headroom answer #718
        # exists to prevent.
        if self._unreported.get(key) or entry.get("usage_complete") is False:
            return None
        return entry["total_tokens"] / free_tokens

    async def get_all_usage(self) -> list[dict[str, object]]:
        result = []
        for (provider, ck), entry in self._usage.items():
            item: dict[str, object] = {"provider": provider, "cycle_key": ck, **entry}
            unreported = self._unreported.get((provider, ck), 0)
            if unreported:
                item["unreported_count"] = unreported
                item["usage_complete"] = False
            result.append(item)
        return result
