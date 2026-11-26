"""Canonical Invocation usage-recorder contracts (#718).

The recorder is the live quota-recording path installed at Invocation
terminalization by ``CapabilityEffectContext``. These tests pin the three
behaviors that make the ledger trustworthy:

- the same physical Invocation is charged exactly once, whatever retries
  terminalization makes;
- a tracker predating canonical evidence still receives its usage through the
  ``record_usage`` compatibility path rather than being silently dropped;
- a call whose provider never reported usage is projected as *unreported*
  evidence, never as a measured zero.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.capabilities.binding import ResolvedBinding
from maistro.capabilities.invocation import Invocation, InvocationUsage
from maistro.quota.recorder import CanonicalInvocationUsageRecorder
from maistro.quota.tracker import InMemoryQuotaTracker
from maistro.quota.usage_log import InMemoryUsageLog


def _binding(provider_name: str = "openai") -> ResolvedBinding:
    return ResolvedBinding(
        binding_id="binding-1",
        capability="model_chat",
        provider_name=provider_name,
        provider_trust_tier="trusted",
    )


def _invocation(
    invocation_id: str = "inv-1",
    provider_name: str = "openai",
    usage: InvocationUsage | None = None,
) -> Invocation:
    return Invocation(
        invocation_id=invocation_id,
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        binding=_binding(provider_name),
        effect_key="model.chat",
        usage=usage,
    )


class LegacyTracker:
    """A tracker from before canonical evidence: usage-only, no identity.

    Mirrors the external/custom trackers the compatibility branch exists for
    (e.g. RSI's burn recorder): they know ``record_usage`` and maybe
    ``record_unreported``, but nothing keyed by Invocation.
    """

    def __init__(self) -> None:
        self.usage_calls: list[tuple[Any, ...]] = []
        self.unreported_calls: list[tuple[Any, ...]] = []

    async def record_usage(self, provider: str, cycle: str, tin: int, tout: int) -> None:
        self.usage_calls.append((provider, cycle, tin, tout))

    async def record_unreported(self, provider: str, cycle: str) -> None:
        self.unreported_calls.append((provider, cycle))


class UsageOnlyTracker:
    """The oldest shape: usage recording only, no unreported projection."""

    def __init__(self) -> None:
        self.usage_calls: list[tuple[Any, ...]] = []

    async def record_usage(self, provider: str, cycle: str, tin: int, tout: int) -> None:
        self.usage_calls.append((provider, cycle, tin, tout))


@pytest.mark.asyncio
async def test_records_one_invocation_exactly_once_across_repeated_calls() -> None:
    """Terminalization retries the same physical call; the ledger must not care."""
    log = InMemoryUsageLog()
    tracker = InMemoryQuotaTracker()
    recorder = CanonicalInvocationUsageRecorder(log, tracker)
    usage = InvocationUsage(input_units=11, output_units=5)

    await recorder.record(_invocation(usage=usage))
    await recorder.record(_invocation(usage=usage))

    events = log.events_for("openai")
    assert len(events) == 1
    (row,) = [r for r in await tracker.get_all_usage() if r["provider"] == "openai"]
    assert row["request_count"] == 1
    assert row["total_tokens"] == 16


@pytest.mark.asyncio
async def test_legacy_tracker_with_usage_receives_record_usage() -> None:
    log = InMemoryUsageLog()
    tracker = LegacyTracker()
    recorder = CanonicalInvocationUsageRecorder(log, tracker)

    await recorder.record(_invocation(usage=InvocationUsage(input_units=7, output_units=3)))

    assert tracker.usage_calls == [("openai", "monthly", 7, 3)]
    assert tracker.unreported_calls == []


@pytest.mark.asyncio
async def test_legacy_tracker_without_usage_is_marked_unreported() -> None:
    log = InMemoryUsageLog()
    tracker = LegacyTracker()
    recorder = CanonicalInvocationUsageRecorder(log, tracker)

    await recorder.record(_invocation())  # no usage: provider omitted it

    assert tracker.usage_calls == []
    assert tracker.unreported_calls == [("openai", "monthly")]
    # And the local log keeps the honest marker: usage_reported is False, not
    # a zero-token measurement.
    (event,) = log.events_for("openai")
    assert event.usage_reported is False
    assert event.input_tokens == 0


@pytest.mark.asyncio
async def test_usage_only_tracker_without_usage_is_a_no_op_not_a_crash() -> None:
    log = InMemoryUsageLog()
    tracker = UsageOnlyTracker()
    recorder = CanonicalInvocationUsageRecorder(log, tracker)

    await recorder.record(_invocation())  # must not raise

    assert tracker.usage_calls == []
    assert not hasattr(tracker, "record_unreported")  # the premise of this test


class TransientLedgerTracker:
    """A durable tracker whose first write fails, like a transient DB outage.

    The write is identity-keyed and idempotent, exactly like the SQLite and
    PostgreSQL ``record_invocation`` implementations.
    """

    def __init__(self) -> None:
        self.inner = InMemoryQuotaTracker()
        self.calls = 0

    async def record_invocation(
        self,
        invocation_id: str,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
        usage_reported: bool,
    ) -> dict[str, object]:
        self.calls += 1
        if self.calls == 1:
            raise OSError("quota ledger transiently unavailable")
        return await self.inner.record_invocation(
            invocation_id,
            provider,
            billing_cycle,
            input_tokens,
            output_tokens,
            usage_reported,
        )

    async def get_all_usage(self) -> list[dict[str, object]]:
        return await self.inner.get_all_usage()


@pytest.mark.asyncio
async def test_transient_ledger_failure_is_retried_not_permanently_lost() -> None:
    """#718 at-least-once: a failed write leaves the Invocation unmarked.

    The previous behavior pre-marked the Invocation before the awaited tracker
    write, so a transient ledger failure permanently omitted durable quota
    evidence — the retry was a silent no-op. Now the retry re-attempts and the
    ledger ends up charged exactly once, with exactly one usage event.
    """
    log = InMemoryUsageLog()
    tracker = TransientLedgerTracker()
    recorder = CanonicalInvocationUsageRecorder(log, tracker)
    usage = InvocationUsage(input_units=11, output_units=5)

    with pytest.raises(OSError, match="transiently unavailable"):
        await recorder.record(_invocation(usage=usage))
    # The failed attempt recorded no half-evidence either.
    assert log.events_for("openai") == ()

    await recorder.record(_invocation(usage=usage))  # the repair attempt

    assert tracker.calls == 2
    (row,) = [r for r in await tracker.get_all_usage() if r["provider"] == "openai"]
    assert row["request_count"] == 1
    assert row["total_tokens"] == 16
    events = log.events_for("openai")
    assert len(events) == 1
    assert events[0].invocation_id == "inv-1"


@pytest.mark.asyncio
async def test_repair_retry_after_success_does_not_double_charge() -> None:
    """The retry machinery itself must stay at-most-once for charging."""
    log = InMemoryUsageLog()
    tracker = InMemoryQuotaTracker()
    recorder = CanonicalInvocationUsageRecorder(log, tracker)
    usage = InvocationUsage(input_units=4, output_units=2)

    await recorder.record(_invocation(usage=usage))
    await recorder.record(_invocation(usage=usage))  # spurious replay

    (row,) = [r for r in await tracker.get_all_usage() if r["provider"] == "openai"]
    assert row["request_count"] == 1
    assert len(log.events_for("openai")) == 1
