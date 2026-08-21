from __future__ import annotations

import pytest

from maistro_evolve.audit import AuditEntry, GenomeAuditTrail


class _RecordingSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def log_delegation(self, peer_name: str, agent_id: str, detail: str) -> None:
        self.calls.append((peer_name, agent_id, detail))


class _FailingSink:
    async def log_delegation(self, peer_name: str, agent_id: str, detail: str) -> None:
        raise RuntimeError("sink unavailable")


class TestGenomeAuditTrail:
    @pytest.mark.asyncio
    async def test_record_appends_entry_with_sequence_one(self):
        trail = GenomeAuditTrail(_RecordingSink())
        entry = await trail.record("promotion_attempt", "g-1", detail="x")
        assert entry == AuditEntry(
            sequence=1, event="promotion_attempt", genome_id="g-1", detail="x"
        )
        assert trail.entries == [entry]

    @pytest.mark.asyncio
    async def test_sequence_numbers_increment_with_no_gaps(self):
        trail = GenomeAuditTrail(_RecordingSink())
        for i in range(5):
            await trail.record("event", f"g-{i}")
        assert [e.sequence for e in trail.entries] == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_record_forwards_to_sink_with_genome_as_agent_id(self):
        sink = _RecordingSink()
        trail = GenomeAuditTrail(sink)
        await trail.record("rollback_committed", "g-target", detail="restored")
        assert sink.calls == [("rollback_committed", "g-target", "restored")]

    @pytest.mark.asyncio
    async def test_entries_property_returns_a_copy(self):
        trail = GenomeAuditTrail(_RecordingSink())
        await trail.record("event", "g-1")
        snapshot = trail.entries
        snapshot.append(AuditEntry(sequence=99, event="forged", genome_id="x", detail=""))
        assert len(trail.entries) == 1

    @pytest.mark.asyncio
    async def test_failing_sink_raises_and_does_not_append_entry(self):
        trail = GenomeAuditTrail(_FailingSink())
        with pytest.raises(RuntimeError, match="sink unavailable"):
            await trail.record("promotion_attempt", "g-1")
        assert trail.entries == []

    @pytest.mark.asyncio
    async def test_sequence_continues_correctly_after_a_prior_failure_is_fixed(self):
        sink = _RecordingSink()
        trail = GenomeAuditTrail(sink)
        await trail.record("event_a", "g-1")
        failing_trail_entries_before = len(trail.entries)
        # Swap in a failing sink mid-life, confirm a failed record never
        # consumes a sequence number (no gap is ever observable).
        trail._sink = _FailingSink()  # type: ignore[assignment]
        with pytest.raises(RuntimeError):
            await trail.record("event_b", "g-2")
        assert len(trail.entries) == failing_trail_entries_before
        trail._sink = sink  # type: ignore[assignment]
        entry = await trail.record("event_c", "g-3")
        assert entry.sequence == 2
        assert [e.sequence for e in trail.entries] == [1, 2]
