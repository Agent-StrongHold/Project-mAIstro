"""In-memory UserModelStore. Durable SQLite/PostgreSQL twins follow (#1047)."""

from __future__ import annotations

import asyncio
import dataclasses

from maistro.memory.user_model.types import (
    Correction,
    FactState,
    RevisionConflictError,
    TombstonedLineageError,
    UserModelFact,
    new_fact_id,
)


class InMemoryUserModelStore:
    """Append-only lineages of UserModelFact revisions, keyed by lineage id."""

    def __init__(self) -> None:
        self._lineages: dict[str, list[UserModelFact]] = {}
        self._tombstoned: set[str] = set()
        self._lock = asyncio.Lock()

    async def append_revision(self, fact: UserModelFact) -> UserModelFact:
        async with self._lock:
            if fact.lineage_id in self._tombstoned:
                raise TombstonedLineageError(fact.lineage_id)
            history = self._lineages.get(fact.lineage_id, [])
            _check_follows(history[-1] if history else None, fact)
            if history:
                history[-1] = dataclasses.replace(history[-1], state=FactState.SUPERSEDED)
            self._lineages[fact.lineage_id] = [*history, fact]
            return fact

    async def current(self, lineage_id: str) -> UserModelFact | None:
        history = self._lineages.get(lineage_id)
        return history[-1] if history else None

    async def history(self, lineage_id: str) -> list[UserModelFact]:
        return list(self._lineages.get(lineage_id, []))

    async def list_for_user(self, owner_user_id: str) -> list[UserModelFact]:
        if not owner_user_id:
            return []
        return [
            history[-1]
            for lineage_id, history in self._lineages.items()
            if lineage_id not in self._tombstoned and history[-1].owner_user_id == owner_user_id
        ]

    async def tombstone(
        self, lineage_id: str, *, acting_user_id: str, reason: str
    ) -> UserModelFact:
        async with self._lock:
            history = self._lineages.get(lineage_id)
            if not history:
                raise KeyError(lineage_id)
            head = history[-1]
            if not acting_user_id or head.owner_user_id != acting_user_id:
                raise PermissionError("only the owner may tombstone a user-model fact")
            if lineage_id in self._tombstoned:
                return head
            tomb = dataclasses.replace(
                head,
                fact_id=new_fact_id(),
                revision=head.revision + 1,
                supersedes=head.fact_id,
                statement="",
                evidence=(),
                persona_hints=(),
                state=FactState.TOMBSTONED,
                correction=Correction(corrected_by=acting_user_id, reason=reason),
            )
            self._lineages[lineage_id] = [tomb]
            self._tombstoned.add(lineage_id)
            return tomb

    async def is_tombstoned(self, lineage_id: str) -> bool:
        return lineage_id in self._tombstoned


def _check_follows(head: UserModelFact | None, fact: UserModelFact) -> None:
    if head is None:
        if fact.revision != 1:
            raise RevisionConflictError(f"lineage {fact.lineage_id} starts at revision 1")
        return
    if fact.revision != head.revision + 1 or fact.supersedes != head.fact_id:
        raise RevisionConflictError(
            f"revision {fact.revision} does not follow {head.fact_id} (revision {head.revision})"
        )
    if fact.owner_user_id != head.owner_user_id:
        raise RevisionConflictError("a lineage never changes owner")
