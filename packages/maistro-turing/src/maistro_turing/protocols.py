"""Protocols for the memory and self-model persistence layer.

These define the backend-agnostic interface that both SQLiteRepo and
PostgresRepo must satisfy. Extracted from the concrete repo.py / self_repo.py
implementations so that callers depend on behaviour, not storage engine.

See DESIGN.md §3 and specs/persistence.md.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .types import EpisodicMemory, MemoryTier, SourceKind


class RepoError(RuntimeError):
    pass


class ImmutableViolation(RepoError):
    pass


class ProvenanceViolation(RepoError):
    pass


class WisdomDeferred(RepoError):
    pass


class WisdomInvariantViolation(RepoError):
    pass


@runtime_checkable
class MemoryRepo(Protocol):
    """Core episodic memory store. Backend-agnostic.

    Acceptance criteria:
    - AC-1: insert returns memory_id; get(insert(m)) == m
    - AC-2: durable tiers reject soft_delete
    - AC-3: superseded_by is settable exactly once
    - AC-4: decay_weight clamps to tier floor
    - AC-5: find with no filters returns all non-deleted memories
    - AC-6: close is idempotent
    """

    def insert(self, memory: EpisodicMemory) -> str: ...
    def get(self, memory_id: str) -> EpisodicMemory | None: ...
    def get_head(self, memory_id: str) -> EpisodicMemory | None: ...
    def walk_lineage(self, memory_id: str) -> list[EpisodicMemory]: ...
    def set_superseded_by(self, memory_id: str, successor_id: str) -> None: ...
    def increment_contradiction_count(self, memory_id: str) -> None: ...
    def touch_access(self, memory_id: str) -> None: ...
    def decay_weight(self, memory_id: str, delta: float) -> float: ...
    def soft_delete(self, memory_id: str) -> None: ...
    def find(
        self,
        *,
        self_id: str | None = ...,
        tier: MemoryTier | None = ...,
        tiers: Iterable[MemoryTier] | None = ...,
        source: SourceKind | None = ...,
        sources: Iterable[SourceKind] | None = ...,
        intent_at_time: str | None = ...,
        created_after: datetime | None = ...,
        include_deleted: bool = ...,
        include_superseded: bool = ...,
    ) -> Iterator[EpisodicMemory]: ...
    def count_by_tier(self, tier: MemoryTier) -> int: ...
    def close(self) -> None: ...


@runtime_checkable
class WorkingMemoryStore(Protocol):
    """Short-term prioritised scratchpad. Backend-agnostic.

    Acceptance criteria:
    - AC-7: add returns entry_id; entries() includes it
    - AC-8: auto-evicts lowest priority when max_entries exceeded
    - AC-9: remove returns True if existed, False otherwise
    - AC-10: clear returns count of removed entries
    - AC-11: content truncated to WORKING_MEMORY_MAX_CONTENT_LEN
    """

    def entries(self, self_id: str) -> list[Any]: ...
    def add(
        self, self_id: str, content: str, *, priority: float = ..., max_entries: int = ...
    ) -> str: ...
    def remove(self, self_id: str, entry_id: str) -> bool: ...
    def update_priority(self, self_id: str, entry_id: str, *, priority: float) -> bool: ...
    def clear(self, self_id: str) -> int: ...
    def render(self, self_id: str) -> str: ...


__all__ = [
    "ImmutableViolation",
    "MemoryRepo",
    "ProvenanceViolation",
    "RepoError",
    "WisdomDeferred",
    "WisdomInvariantViolation",
    "WorkingMemoryStore",
]
