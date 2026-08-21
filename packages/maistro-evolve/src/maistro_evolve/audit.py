"""Audit trail for genome self-modification state transitions.

Reuses ``maistro.a2a.guest_peers.AuditLogger`` (the same Protocol Phase 10's
``agent.delegate_remote`` node logs through) rather than inventing a parallel
audit mechanism for maistro-evolve. ``peer_name`` carries the event name and
``agent_id`` carries the genome id — the protocol's shape is generic enough
to cover both delegation and genome events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class GenomeAuditSink(Protocol):
    async def log_delegation(self, peer_name: str, agent_id: str, detail: str) -> None: ...


@dataclass(frozen=True)
class AuditEntry:
    sequence: int
    event: str
    genome_id: str
    detail: str


class GenomeAuditTrail:
    """Append-only, strictly-sequenced log of genome state transitions.

    Sequence numbers start at 1 and increment by exactly 1 per successful
    ``record()`` call, with no gaps — ``entries`` is the sole source of
    truth for what was recorded, so a caller can never observe a missing
    sequence number without it meaning a record genuinely never happened.
    """

    def __init__(self, sink: GenomeAuditSink) -> None:
        self._sink = sink
        self._entries: list[AuditEntry] = []

    @property
    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    async def record(self, event: str, genome_id: str, detail: str = "") -> AuditEntry:
        entry = AuditEntry(
            sequence=len(self._entries) + 1,
            event=event,
            genome_id=genome_id,
            detail=detail,
        )
        await self._sink.log_delegation(peer_name=event, agent_id=genome_id, detail=detail)
        self._entries.append(entry)
        return entry
