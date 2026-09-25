"""Quota tracker: token usage recording per provider per billing cycle."""

from __future__ import annotations

from collections import defaultdict

from maistro.quota.billing import cycle_key


class InMemoryQuotaTracker:
    def __init__(self) -> None:
        self._invocations: set[str] = set()
        self._usage: dict[tuple[str, str], dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "request_count": 0},
        )

    async def record_usage(
        self,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, object]:
        key = (provider, cycle_key(billing_cycle))
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
        if invocation_id in self._invocations:
            key = (provider, cycle_key(billing_cycle))
            return {"provider": provider, "cycle_key": key[1], **self._usage[key]}
        self._invocations.add(invocation_id)
        if usage_reported:
            return await self.record_usage(provider, billing_cycle, input_tokens, output_tokens)
        await self.record_unreported(provider, billing_cycle)
        key = (provider, cycle_key(billing_cycle))
        return {"provider": provider, "cycle_key": key[1], **self._usage[key]}

    async def record_unreported(self, provider: str, billing_cycle: str) -> None:
        """Keep missing provider usage visible without charging zero tokens."""
        key = (provider, cycle_key(billing_cycle))
        entry = self._usage[key]
        entry.setdefault("unreported_count", 0)
        entry["unreported_count"] += 1
        entry["usage_complete"] = False
        entry.setdefault("input_tokens", 0)
        entry.setdefault("output_tokens", 0)
        entry.setdefault("total_tokens", 0)
        entry.setdefault("request_count", 0)
        entry["request_count"] += 1

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
