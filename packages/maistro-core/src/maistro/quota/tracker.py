"""Quota tracker: token usage recording per provider per billing cycle."""

from __future__ import annotations

from collections import defaultdict
from uuid import uuid4

from maistro.quota.billing import cycle_key

UsagePayload = tuple[str, str, int, int]


class InMemoryQuotaTracker:
    def __init__(self) -> None:
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

    async def get_usage_pct(
        self,
        provider: str,
        billing_cycle: str,
        free_tokens: int,
    ) -> float:
        if free_tokens <= 0:
            return 0.0
        key = (provider, cycle_key(billing_cycle))
        entry = self._usage[key]
        return entry["total_tokens"] / free_tokens

    async def get_all_usage(self) -> list[dict[str, object]]:
        result = []
        for (provider, ck), entry in self._usage.items():
            result.append({"provider": provider, "cycle_key": ck, **entry})
        return result
