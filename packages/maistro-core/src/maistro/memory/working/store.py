"""The durable workspace observation log — protocol and in-memory reference.

``WorkspaceLogStore`` is the system of record the working-memory projection
hydrates from (ADR-082226-5104: PostgreSQL/SQLite durable, projection
ephemeral). The protocol is deliberately narrow and **append-only**: entries
are appended and read back, never mutated or deleted in place. The only
driven deletion is ``purge_workspace`` — removing a Workspace removes its log,
which is a retention decision, not an edit.

``InMemoryWorkspaceLogStore`` is the reference implementation every durable
twin (see ``sqlite_store.py``) must agree with; it is also the honest
fallback for processes with no database pool, where the wiring warns loudly
that the log dies with the process.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol, runtime_checkable

from maistro.memory.working.types import (
    ObservationKind,
    WorkingResult,
    WorkspaceObservation,
)


@runtime_checkable
class WorkspaceLogStore(Protocol):
    """Append-only per-Workspace observation log + addressable results.

    M1 product-local projection: Workspace

    The log is keyed by ``workspace_id`` but is not the canonical Workspace
    store — ``maistro.workspaces`` owns that. This is the #301 observation
    log, a domain store projected onto the Workspace axis.
    """

    async def append(self, entry: WorkspaceObservation) -> WorkspaceObservation:
        """Append one entry, assigning its log position (``seq``).

        Returns the entry as stored, with ``seq`` set. Callers pass an entry
        with ``seq=None``; a caller-chosen ``seq`` is ignored, because log
        position belongs to the log, not the writer.
        """
        ...

    async def list_entries(
        self,
        workspace_id: str,
        *,
        kinds: tuple[ObservationKind, ...] | None = None,
        after_seq: int = 0,
        limit: int | None = None,
        survive_reset: bool | None = None,
    ) -> list[WorkspaceObservation]:
        """Entries in log order (``seq`` ascending), optionally filtered.

        ``after_seq`` paginates past a previously seen position; ``limit``
        bounds the read. ``survive_reset`` filters on the survival flag —
        hydration needs the flag-filtered read because a pinned entry may sit
        *before* the last reset marker, outside the post-reset window, and
        still belongs in the rebuilt working set. The full history is always
        reachable — this is the lossless read that survives every reset.
        """
        ...

    async def get_entry(self, workspace_id: str, entry_id: str) -> WorkspaceObservation | None: ...

    async def latest_entry(
        self,
        workspace_id: str,
        *,
        kinds: tuple[ObservationKind, ...] | None = None,
    ) -> WorkspaceObservation | None:
        """The newest entry matching the filter, in log order.

        Exists so "where is the last reset marker" is one indexed read
        instead of a walk of the whole log.
        """
        ...

    async def put_result(self, result: WorkingResult) -> bool:
        """Store a full result under its content address.

        Returns ``True`` when the record is new, ``False`` when the same
        ``result_id`` already existed — identical results are stored once and
        referenced any number of times.
        """
        ...

    async def get_result(self, workspace_id: str, result_id: str) -> WorkingResult | None: ...

    async def purge_workspace(self, workspace_id: str) -> int:
        """Delete every log entry and result for a Workspace.

        The driven deletion path for retention: a Workspace that goes away
        takes its log with it. Returns the number of entries purged (results
        are not counted — they are payload, not observations).
        """
        ...


class InMemoryWorkspaceLogStore:
    """Reference implementation: process memory, correct by construction.

    Every durable twin must agree with this class on ordering, seq
    assignment, result dedup and purge counts, which is why the conformance
    suite runs both legs over the same calls.

    M1 product-local projection: Workspace
    """

    def __init__(self) -> None:
        self._entries: dict[str, list[WorkspaceObservation]] = {}
        self._by_id: dict[str, dict[str, WorkspaceObservation]] = {}
        self._results: dict[str, dict[str, WorkingResult]] = {}

    async def append(self, entry: WorkspaceObservation) -> WorkspaceObservation:
        log = self._entries.setdefault(entry.workspace_id, [])
        stored = replace(entry, seq=len(log) + 1)
        log.append(stored)
        self._by_id.setdefault(entry.workspace_id, {})[entry.entry_id] = stored
        return stored

    async def list_entries(
        self,
        workspace_id: str,
        *,
        kinds: tuple[ObservationKind, ...] | None = None,
        after_seq: int = 0,
        limit: int | None = None,
        survive_reset: bool | None = None,
    ) -> list[WorkspaceObservation]:
        found = [
            e
            for e in self._entries.get(workspace_id, [])
            if e.seq is not None
            and e.seq > after_seq
            and (kinds is None or e.kind in kinds)
            and (survive_reset is None or e.survive_reset is survive_reset)
        ]
        if limit is not None:
            found = found[:limit]
        return list(found)

    async def get_entry(self, workspace_id: str, entry_id: str) -> WorkspaceObservation | None:
        return self._by_id.get(workspace_id, {}).get(entry_id)

    async def latest_entry(
        self,
        workspace_id: str,
        *,
        kinds: tuple[ObservationKind, ...] | None = None,
    ) -> WorkspaceObservation | None:
        log = self._entries.get(workspace_id, [])
        for entry in reversed(log):
            if kinds is None or entry.kind in kinds:
                return entry
        return None

    async def put_result(self, result: WorkingResult) -> bool:
        bucket = self._results.setdefault(result.workspace_id, {})
        if result.result_id in bucket:
            return False
        bucket[result.result_id] = result
        return True

    async def get_result(self, workspace_id: str, result_id: str) -> WorkingResult | None:
        return self._results.get(workspace_id, {}).get(result_id)

    async def purge_workspace(self, workspace_id: str) -> int:
        purged = len(self._entries.get(workspace_id, []))
        self._entries.pop(workspace_id, None)
        self._by_id.pop(workspace_id, None)
        self._results.pop(workspace_id, None)
        return purged
