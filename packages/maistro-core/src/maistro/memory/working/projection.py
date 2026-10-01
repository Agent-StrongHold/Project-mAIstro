"""The per-Workspace working-memory projection (M4-H / #301).

This is the ephemeral half of ADR-082226-5104 §5-6: one working graph per
active Workspace, hydrated from the durable observation log, held in process
memory, **never authoritative**. A projection that is corrupted, stale or
simply idle is discarded and rebuilt from the log — "Ladybug failure must
never imply durable data loss", so nothing here writes anything the log does
not already hold.

The role ADR-082226-5104 assigns to LadybugDB is played by an embedded
in-process graph over the log; the ADR-039 external-library adoption decision
for the LadybugDB binary itself is deliberately *not* made in this module.
The seam a Ladybug-backed implementation would take is this class: hydrate /
apply / active set / neighbor traversal / drop, per Workspace, single-writer
by construction (one projection object per Workspace per process).

The **working set** is a derivation over the log, not a second copy:

* an entry at or before the last ``RESET`` marker is out, unless it is in the
  survival set (the ids the reset named, plus every entry flagged
  ``survive_reset`` — those survive from *any* position);
* an entry a later ``SUMMARY`` folded is out, for the same reason;
* ``RESET`` markers themselves are bookkeeping, not context.

Every exclusion is recomputable from the append-only log, which is what makes
the projection disposable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from maistro.memory.working.store import WorkspaceLogStore
from maistro.memory.working.types import (
    ObservationKind,
    WorkingResult,
    WorkspaceObservation,
    make_result_id,
    observation,
)


@dataclass(frozen=True)
class ProjectionStats:
    """What the projection currently holds, for tests and eviction policy."""

    entries: int
    active: int
    folded: int
    results: int
    last_reset_seq: int | None


class WorkspaceWorkingMemory:
    """One Workspace's ephemeral working graph. Single-writer by ownership."""

    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id
        self._entries: dict[str, WorkspaceObservation] = {}
        self._results: dict[str, WorkingResult] = {}
        self._last_used = time.monotonic()
        self._active: list[WorkspaceObservation] = []
        self._last_reset_seq: int | None = None
        self._survival: frozenset[str] = frozenset()
        self._dirty = True

    # -- hydration ---------------------------------------------------------

    def hydrate(
        self,
        entries: list[WorkspaceObservation],
        results: list[WorkingResult] | None = None,
    ) -> None:
        """Materialise log state into the projection. Callers read the
        entries from the durable store; this method owns no I/O."""
        for entry in entries:
            self.apply(entry)
        for result in results or []:
            self._results[result.result_id] = result
        self.touch()

    def apply(self, entry: WorkspaceObservation) -> None:
        """Fold one appended log entry into the projection incrementally."""
        self._entries[entry.entry_id] = entry
        if entry.kind is ObservationKind.RESET:
            # The newest reset owns the survival set: it names what it keeps,
            # so a later hard reset can drop an earlier reset's survivors.
            # (Accumulating across markers would disagree with hydration,
            # which reads from the newest marker — the one disagreement that
            # breaks rebuild equivalence.) The ``survive_reset`` flag remains
            # the cross-reset mechanism; it needs no naming.
            self._survival = frozenset(str(v) for v in entry.meta.get("survival", []))
            if entry.seq is not None:
                self._last_reset_seq = max(
                    self._last_reset_seq if self._last_reset_seq is not None else 0,
                    entry.seq,
                )
        self._dirty = True
        self.touch()

    def attach_result(self, result: WorkingResult) -> None:
        self._results[result.result_id] = result
        self.touch()

    def touch(self) -> None:
        self._last_used = time.monotonic()

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self._last_used

    # -- the working-set derivation ----------------------------------------

    def _recompute(self) -> None:
        ordered = sorted(
            (e for e in self._entries.values() if e.seq is not None),
            key=lambda e: e.seq if e.seq is not None else 0,
        )
        folded: set[str] = set()
        for entry in ordered:
            if entry.kind is not ObservationKind.SUMMARY:
                continue
            if entry.seq is not None and entry.seq <= (self._last_reset_seq or 0):
                continue
            folded.update(str(v) for v in entry.meta.get("folds", []))
        active: list[WorkspaceObservation] = []
        for entry in ordered:
            if entry.kind is ObservationKind.RESET:
                continue
            in_survival = entry.survive_reset or entry.entry_id in self._survival
            if not in_survival:
                if (
                    self._last_reset_seq is not None
                    and entry.seq is not None
                    and entry.seq <= self._last_reset_seq
                ):
                    continue
                if entry.entry_id in folded:
                    continue
            active.append(entry)
        self._active = active
        self._dirty = False

    def active_entries(self) -> list[WorkspaceObservation]:
        """The working set, in log order."""
        if self._dirty:
            self._recompute()
        return list(self._active)

    def entry(self, entry_id: str) -> WorkspaceObservation | None:
        return self._entries.get(entry_id)

    def all_entries(self) -> list[WorkspaceObservation]:
        """Every held entry in log order — the GUIDE view, which lists what
        exists beyond the working set (the log remembers folded entries even
        when the working set does not)."""
        return sorted(
            self._entries.values(),
            key=lambda e: e.seq if e.seq is not None else 0,
        )

    def all_results(self) -> list[WorkingResult]:
        """Every hydrated full result."""
        return list(self._results.values())

    def result(self, result_id: str) -> WorkingResult | None:
        return self._results.get(result_id)

    def entries_by_digest(self, digest: str) -> list[WorkspaceObservation]:
        """Every held entry with this content digest — the redundant-
        hypothesis lookup that needs no vector retrieval."""
        return [e for e in self._entries.values() if e.digest == digest]

    def neighbors(self, entry_id: str) -> list[WorkspaceObservation]:
        """Graph traversal: the entries *associated* with this one.

        Edges are the only relations the architecture commits to (ADR
        §3: typed, shallow, workspace-bound): the entry's referenced result's
        sibling entries (same ``result_ref``), and the entries sharing its
        content digest (same claim re-observed). Lineage, not similarity.
        """
        entry = self._entries.get(entry_id)
        if entry is None:
            return []
        found: dict[str, WorkspaceObservation] = {}
        if entry.result_ref is not None:
            found.update(
                {
                    e.entry_id: e
                    for e in self._entries.values()
                    if e.result_ref == entry.result_ref and e.entry_id != entry_id
                }
            )
        found.update(
            {
                e.entry_id: e
                for e in self._entries.values()
                if e.digest == entry.digest and e.entry_id != entry_id and entry.digest
            }
        )
        return sorted(found.values(), key=lambda e: e.seq if e.seq is not None else 0)

    @property
    def last_reset_seq(self) -> int | None:
        return self._last_reset_seq

    def stats(self) -> ProjectionStats:
        if self._dirty:
            self._recompute()
        return ProjectionStats(
            entries=len(self._entries),
            active=len(self._active),
            folded=len(self._entries) - len(self._active),
            results=len(self._results),
            last_reset_seq=self._last_reset_seq,
        )

    def drop(self) -> None:
        """Discard the projection. The log is untouched; a later hydrate
        rebuilds an equivalent working set."""
        self._entries.clear()
        self._results.clear()
        self._active.clear()
        self._last_reset_seq = None
        self._survival = frozenset()
        self._dirty = True


class WorkingMemoryManager:
    """Lazily hydrated, evictable per-Workspace projections.

    One live projection per active Workspace — runs in the same Workspace
    share hot context, and a traversal in one Workspace cannot wander into
    another's because the data is simply absent (ADR-082226-5104 §5). Idle
    TTL and capacity bounds keep a ten-thousand-workspace deployment at a
    few dozen live graphs.
    """

    def __init__(
        self,
        store: WorkspaceLogStore,
        *,
        ttl_seconds: float = 900.0,
        max_projections: int = 64,
    ) -> None:
        self.store = store
        self.ttl_seconds = ttl_seconds
        self.max_projections = max_projections
        self._projections: dict[str, WorkspaceWorkingMemory] = {}

    async def projection(self, workspace_id: str) -> WorkspaceWorkingMemory:
        """Return the Workspace's projection, hydrating it on first use.

        Hydration materialises the entries logged after the last reset plus
        the results those entries reference — the working set is what a
        Workspace resumes with, not the whole history.
        """
        existing = self._projections.get(workspace_id)
        if existing is not None:
            existing.touch()
            return existing
        projection = WorkspaceWorkingMemory(workspace_id)
        reset_marker = await self.store.latest_entry(workspace_id, kinds=(ObservationKind.RESET,))
        after = reset_marker.seq if reset_marker is not None and reset_marker.seq else 0
        entries = await self.store.list_entries(workspace_id, after_seq=after)
        if reset_marker is not None:
            projection.apply(reset_marker)
            # Survival-set entries may sit anywhere in the log — after the
            # pagination point they arrive with the window above; before it
            # they are read explicitly: the ones the reset named by id, and
            # every entry flagged ``survive_reset``, which survives from any
            # position. Without the flag read a pre-reset pinned entry would
            # vanish on rebuild, breaking rebuild equivalence.
            window_ids = {e.entry_id for e in entries}
            pinned = await self.store.list_entries(workspace_id, survive_reset=True)
            for entry in pinned:
                if entry.entry_id not in window_ids:
                    entries.append(entry)
                    window_ids.add(entry.entry_id)
            named = [str(v) for v in reset_marker.meta.get("survival", [])]
            for entry_id in named:
                if entry_id in window_ids:
                    continue
                survivor = await self.store.get_entry(workspace_id, entry_id)
                if survivor is not None:
                    entries.append(survivor)
                    window_ids.add(entry_id)
        entries = [e for e in entries if e.seq is not None]
        entries.sort(key=lambda e: e.seq if e.seq is not None else 0)
        projection.hydrate(entries)
        refs = {e.result_ref for e in entries if e.result_ref}
        for ref in refs:
            result = await self.store.get_result(workspace_id, ref)
            if result is not None:
                projection.attach_result(result)
        self._projections[workspace_id] = projection
        self.evict()
        return projection

    async def observe(
        self,
        workspace_id: str,
        *,
        cycle: int,
        text: str,
        kind: ObservationKind = ObservationKind.OBSERVATION,
        run_id: str = "",
        survive_reset: bool = False,
        meta: dict[str, object] | None = None,
    ) -> WorkspaceObservation:
        """Append an observation through the store, keeping a hot projection
        coherent. The store is the authority; the projection never invents
        log positions."""
        entry = observation(
            workspace_id=workspace_id,
            cycle=cycle,
            text=text,
            kind=kind,
            run_id=run_id,
            survive_reset=survive_reset,
            meta=meta,
        )
        stored = await self.store.append(entry)
        hot = self._projections.get(workspace_id)
        if hot is not None:
            hot.apply(stored)
        return stored

    async def record_tool_result(
        self,
        workspace_id: str,
        *,
        cycle: int,
        source: str,
        content: str,
        text: str,
        run_id: str = "",
        survive_reset: bool = False,
        meta: dict[str, object] | None = None,
    ) -> tuple[WorkingResult, WorkspaceObservation]:
        """Store a full result once, then log the compact pointer to it.

        This is the "reference-addressable" write path: identical payloads in
        one Workspace collapse to one stored result (content-addressed), and
        the log entry carries the compact line plus the reference — never the
        payload.
        """
        result = WorkingResult(
            workspace_id=workspace_id,
            result_id=make_result_id(workspace_id, source, content),
            source=source,
            content=content,
            meta=dict(meta or {}),
        )
        await self.store.put_result(result)
        entry = observation(
            workspace_id=workspace_id,
            cycle=cycle,
            kind=ObservationKind.TOOL_RESULT,
            text=text,
            run_id=run_id,
            result_ref=result.result_id,
            digest=result.digest,
            survive_reset=survive_reset,
            meta=dict(meta or {}),
        )
        stored = await self.store.append(entry)
        hot = self._projections.get(workspace_id)
        if hot is not None:
            hot.attach_result(result)
            hot.apply(stored)
        return result, stored

    def evict(self) -> int:
        """Enforce idle TTL and capacity. Returns projections evicted.

        Eviction is lossless by construction: every evicted graph is
        rebuildable from the log, so eviction never waits for a save.
        """
        evicted = 0
        stale = [ws for ws, p in self._projections.items() if p.idle_seconds > self.ttl_seconds]
        for ws in stale:
            self._projections.pop(ws)
            evicted += 1
        while len(self._projections) > self.max_projections:
            oldest = max(self._projections.values(), key=lambda p: p.idle_seconds)
            self._projections.pop(oldest.workspace_id)
            evicted += 1
        return evicted

    def live_workspaces(self) -> list[str]:
        return sorted(self._projections)

    def hot(self, workspace_id: str) -> WorkspaceWorkingMemory | None:
        """The live projection, if one is loaded — without hydrating."""
        return self._projections.get(workspace_id)

    async def dispose(self, workspace_id: str) -> None:
        """Drop one projection. Log untouched (it is the system of record)."""
        self._projections.pop(workspace_id, None)

    async def rebuild(self, workspace_id: str) -> WorkspaceWorkingMemory:
        """Discard and rehydrate — the corruption recovery path. Because the
        log is authoritative, rebuild is always exactly `dispose` + hydrate;
        there is nothing to reconcile."""
        await self.dispose(workspace_id)
        return await self.projection(workspace_id)
