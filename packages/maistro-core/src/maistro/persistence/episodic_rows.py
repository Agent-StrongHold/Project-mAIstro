"""The one mapping between `EpisodicMemory` and a row of `episodic_memories`.

Shared by `PgEpisodicStore` and `SqliteEpisodicStore` rather than written twice.
Two backends spelling the same twenty-column mapping is how a field comes to be
written by one and dropped by the other -- and the fields this table gained in
migration 026 (`project_id`, `decay_rate`, `shared`, `flagged_for_review`) are
exactly the ones that had been on the record with no column at all
(ADR-083026-a322).

The readers are deliberately tolerant of both drivers' representations: asyncpg
hands back `datetime`, `bool` and (with the JSON codecs registered) `dict`,
while SQLite hands back ISO strings, integers and JSON text. One `from_row`
that accepts both is one place to be right.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from maistro.types.memory import EpisodicMemory, MemoryScope, MemoryTier

#: How many scope-matching rows `retrieve` ranks over, taken in weight order.
#:
#: A real difference from `InMemoryEpisodicStore`, which ranks over everything,
#: and the bound is by weight on purpose: the tier ladder's premise is that
#: weight is how much a memory matters, so the heaviest rows are the right
#: candidates to keep. Below this many matching memories the durable stores and
#: the in-memory one return identical answers, and the conformance suite
#: asserts that. Here rather than in either store, so the two agree by
#: construction (ADR-083026-a322).
RETRIEVAL_CANDIDATE_CAP = 500

#: Every column a store writes, in the order `to_row` returns them. `id` is
#: excluded: it is the table's surrogate key and no part of the record.
COLUMNS: tuple[str, ...] = (
    "memory_id",
    "tier",
    "content",
    "weight",
    "org_id",
    "team_id",
    "agent_id",
    "user_id",
    "scope",
    "project_id",
    "source",
    "context",
    "reinforcement_count",
    "contradiction_count",
    "created_at",
    "last_accessed_at",
    "deleted",
    "decay_rate",
    "shared",
    "flagged_for_review",
)


def to_row(memory: EpisodicMemory, *, text_encoded: bool) -> tuple[Any, ...]:
    """The record as bound parameters, in `COLUMNS` order.

    `text_encoded` names what separates the two drivers: PostgreSQL has a JSON
    type and a timestamp type and asyncpg binds the Python objects to them,
    while SQLite has neither and takes both as text. Passing a `datetime` to
    sqlite3 works only through an adapter deprecated in 3.12, so the conversion
    is done here where both stores can see it rather than left to the driver.
    """
    context: Any = dict(memory.context)
    created: Any = memory.created_at
    accessed: Any = memory.last_accessed_at
    if text_encoded:
        context = json.dumps(context, sort_keys=True)
        created = memory.created_at.isoformat()
        accessed = memory.last_accessed_at.isoformat()
    return (
        memory.memory_id,
        str(memory.tier),
        memory.content,
        memory.weight,
        memory.org_id,
        memory.team_id,
        memory.agent_id,
        memory.user_id,
        str(memory.scope),
        memory.project_id,
        memory.source,
        context,
        memory.reinforcement_count,
        memory.contradiction_count,
        created,
        accessed,
        memory.deleted,
        memory.decay_rate,
        memory.shared,
        memory.flagged_for_review,
    )


def _moment(value: Any) -> datetime:
    """A stored timestamp as an aware UTC `datetime`.

    Aware, always: `tick_decay` subtracts `last_accessed_at` from `now`, and a
    naive value there raises rather than decaying wrongly -- which is the better
    failure, but not one a store should be able to hand out.
    """
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        moment = datetime.fromisoformat(value)
    else:
        return datetime.now(UTC)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _context(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    if isinstance(value, str) and value:
        loaded = json.loads(value)
        return {str(k): str(v) for k, v in loaded.items()} if isinstance(loaded, dict) else {}
    return {}


def from_row(row: Any) -> EpisodicMemory:
    """A row -- anything indexable by column name -- as an `EpisodicMemory`."""
    return EpisodicMemory(
        memory_id=str(row["memory_id"] or ""),
        tier=MemoryTier(row["tier"]),
        content=str(row["content"] or ""),
        weight=float(row["weight"]),
        org_id=str(row["org_id"] or ""),
        team_id=str(row["team_id"] or ""),
        agent_id=row["agent_id"],
        user_id=row["user_id"],
        scope=MemoryScope(row["scope"]),
        project_id=str(row["project_id"] or ""),
        source=str(row["source"] or ""),
        context=_context(row["context"]),
        reinforcement_count=int(row["reinforcement_count"] or 0),
        contradiction_count=int(row["contradiction_count"] or 0),
        created_at=_moment(row["created_at"]),
        last_accessed_at=_moment(row["last_accessed_at"]),
        deleted=bool(row["deleted"]),
        decay_rate=float(row["decay_rate"]),
        shared=bool(row["shared"]),
        flagged_for_review=bool(row["flagged_for_review"]),
    )
