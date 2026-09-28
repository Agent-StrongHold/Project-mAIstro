"""Quota tracker: token usage recording per provider per billing cycle."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING
from uuid import uuid4

from maistro.quota.billing import cycle_key

if TYPE_CHECKING:
    from maistro.protocols.quota import QuotaTracker

UsagePayload = tuple[str, str, int, int]


class InMemoryQuotaTracker:
    def __init__(self) -> None:
        self._invocations: set[str] = set()
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
        entry = self._usage.get((provider, cycle_key(billing_cycle)))
        if entry is None:
            # No call was ever recorded for this provider/cycle: vacuously
            # complete, a measured zero, not missing evidence.
            return 0.0
        if entry.get("usage_complete") is False or entry.get("unreported_count"):
            return None
        return entry["total_tokens"] / free_tokens

    async def get_all_usage(self) -> list[dict[str, object]]:
        result = []
        for (provider, ck), entry in self._usage.items():
            result.append({"provider": provider, "cycle_key": ck, **entry})
        return result


_default_quota_tracker: QuotaTracker | None = None


def get_default_quota_tracker() -> QuotaTracker | None:
    """The process-wide shared quota ledger, when a composition registered one.

    Mirrors ``quota.usage_log.get_default_usage_log``'s module-level-singleton
    pattern for the one recording site that crosses no canonical Invocation
    authority: the conductor's raw-gateway fallback (``agents/conductor.py``)
    marks its ungoverned call here so a process that *does* carry a ledger
    never presents complete quota evidence while omitting that call class.
    ``None`` (no composition root registered a tracker) keeps the fallback on
    the usage-log-only evidence path — evidence is never fabricated where no
    ledger exists to receive it.
    """
    return _default_quota_tracker


def set_default_quota_tracker(tracker: QuotaTracker | None) -> None:
    """Register (or, with ``None``, clear) the process-wide quota ledger.

    Set once by the Container composition root (``maistro.container``), which
    is the single place every production process gets its ledger — never by
    agents or runners themselves (#718 stop condition: the canonical effect
    path owns authoritative recording; this default only receives the
    ungoverned fallback's non-Invocation evidence).
    """
    global _default_quota_tracker
    _default_quota_tracker = tracker
