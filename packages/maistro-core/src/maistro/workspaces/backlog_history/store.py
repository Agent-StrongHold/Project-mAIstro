"""The BacklogItem history store contract and its in-memory reference (#101).

A journal, not a store of current state: it only appends events and reads them
back in the order they were recorded. There is no update and no delete — a
history that can be rewritten is not provenance.
"""

from __future__ import annotations

import asyncio
import builtins
from typing import Protocol, runtime_checkable

from maistro.workspaces.backlog_history.model import (
    BacklogEventAlreadyExists,
    BacklogHistoryEvent,
    BacklogHistoryEventKind,
)


@runtime_checkable
class BacklogHistoryStore(Protocol):
    """Append-only BacklogItem history for one deployment.

    `append` assigns the per-(workspace, item) `sequence` and refuses an
    `event_id` that is already recorded. Reads are ordered by that sequence,
    so a UI or agent replays exactly what happened, in order, even when two
    entries share a timestamp.
    """

    async def append(self, event: BacklogHistoryEvent) -> BacklogHistoryEvent:
        """Record `event`; returns it with its assigned `sequence`."""
        ...

    async def history_for_item(
        self,
        workspace_id: str,
        item_id: str,
        *,
        kind: BacklogHistoryEventKind | None = None,
    ) -> builtins.list[BacklogHistoryEvent]:
        """The item's entries, oldest first."""
        ...

    async def history_for_workspace(
        self,
        workspace_id: str,
        *,
        project_id: str | None = None,
        item_id: str | None = None,
        kind: BacklogHistoryEventKind | None = None,
    ) -> builtins.list[BacklogHistoryEvent]:
        """Entries across the Workspace (optionally one Project/item/kind)."""
        ...


class InMemoryBacklogHistoryStore:
    """Reference implementation; the contract the durable stores are held to."""

    def __init__(self) -> None:
        self._events: dict[str, BacklogHistoryEvent] = {}
        self._order: builtins.list[BacklogHistoryEvent] = []
        self._sequences: dict[tuple[str, str], int] = {}
        self._lock = asyncio.Lock()

    async def append(self, event: BacklogHistoryEvent) -> BacklogHistoryEvent:
        async with self._lock:
            if event.event_id in self._events:
                raise BacklogEventAlreadyExists(event.event_id)
            key = (event.workspace_id, event.item_id)
            sequence = self._sequences.get(key, 0) + 1
            self._sequences[key] = sequence
            recorded = event.model_copy(update={"sequence": sequence}, deep=True)
            self._events[recorded.event_id] = recorded
            self._order.append(recorded)
        return recorded.model_copy(deep=True)

    async def history_for_item(
        self,
        workspace_id: str,
        item_id: str,
        *,
        kind: BacklogHistoryEventKind | None = None,
    ) -> builtins.list[BacklogHistoryEvent]:
        return self._select(
            workspace_id,
            item_id=item_id,
            kind=kind,
        )

    async def history_for_workspace(
        self,
        workspace_id: str,
        *,
        project_id: str | None = None,
        item_id: str | None = None,
        kind: BacklogHistoryEventKind | None = None,
    ) -> builtins.list[BacklogHistoryEvent]:
        return self._select(
            workspace_id,
            project_id=project_id,
            item_id=item_id,
            kind=kind,
        )

    def _select(
        self,
        workspace_id: str,
        *,
        project_id: str | None = None,
        item_id: str | None = None,
        kind: BacklogHistoryEventKind | None = None,
    ) -> builtins.list[BacklogHistoryEvent]:
        # Same order the SQLite journal answers with: per item, by the
        # sequence the store assigned, so both backends replay identically.
        return [
            event.model_copy(deep=True)
            for event in sorted(
                (
                    event
                    for event in self._order
                    if event.workspace_id == workspace_id
                    and (project_id is None or event.project_id == project_id)
                    and (item_id is None or event.item_id == item_id)
                    and (kind is None or event.kind == kind)
                ),
                key=lambda event: (event.item_id, event.sequence or 0),
            )
        ]


__all__ = ["BacklogHistoryStore", "InMemoryBacklogHistoryStore"]
