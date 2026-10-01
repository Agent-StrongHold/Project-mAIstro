"""WorkingMemoryManager: one working graph per active Workspace.

ADR-082226-5104 §5: "Granularity is one working graph per active Workspace,
not per Run ... Working graphs are lazy and evictable: hydrate on demand, keep
hot while active, evict on idle TTL or memory pressure. 10,000 workspaces with
40 active means roughly 40 live graphs, not 10,000."

The manager is where that policy lives. It owns the per-Workspace projections,
the lazy hydrate-from-authoritative path, the idle-TTL eviction sweep, and the
failure bookkeeping that keeps Ladybug-style backend failures visible: a
projection that cannot be constructed is not retried silently forever, and a
hydration that fails is logged at error level and answered with ``False`` —
never with a claim that hot recall is active.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Protocol

from maistro.memory.working.projection import WorkspaceWorkingMemoryProjection
from maistro.memory.working.protocol import DEFAULT_EMBEDDING_MODEL

if TYPE_CHECKING:
    from collections.abc import Iterator

    from maistro.memory.working.extraction import EntityExtractor
    from maistro.memory.working.protocol import (
        HydrationReport,
        WorkingMemory,
    )
    from maistro.protocols.embeddings import EmbeddingClient
    from maistro.protocols.memory import EpisodicStore
    from maistro.types.memory import EpisodicMemory

logger = logging.getLogger(__name__)

#: How many durable memories one hydration pass materialises. The working
#: graph is a *hot projection*, not a copy of the durable store (ADR-082226-5104
#: open question 2 leaves the selection policy to measurement); this bounds the
#: blast radius of that question until the benchmark answers it.
DEFAULT_HYDRATION_LIMIT = 500

#: Seconds a projection may sit untouched before the idle sweep evicts it.
DEFAULT_IDLE_TTL_SECONDS = 900.0


class Clock(Protocol):
    """The one method of :mod:`time` the manager needs (tests fake this)."""

    def monotonic(self) -> float: ...


class WorkingMemoryError(RuntimeError):
    """A hydration from the authoritative store failed.

    Raised, not logged-and-ignored: the caller asked for the working graph to
    be brought up to date with durable truth, and "it could not be" is an
    answer the caller needs, not noise. Degrading to durable-path retrieval is
    the manager's decision at its own call sites — with a log line.
    """


class WorkingMemoryManager:
    """Owns the active Workspaces' working graphs and their lifecycle.

    One manager per runtime; the container binds it to the configured
    ``workspace_id`` ("One instance is one Workspace"), and tests may drive
    several Workspaces through one manager to prove isolation.
    """

    def __init__(
        self,
        *,
        workspace_id: str,
        episodic_store: EpisodicStore,
        embedding_client: EmbeddingClient | None = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        entity_extractor: EntityExtractor | None = None,
        hydration_limit: int = DEFAULT_HYDRATION_LIMIT,
        idle_ttl_seconds: float = DEFAULT_IDLE_TTL_SECONDS,
        clock: Clock | None = None,
    ) -> None:
        self._default_workspace_id = workspace_id
        self._episodic_store = episodic_store
        self._embedding_client = embedding_client
        self._embedding_model = embedding_model
        self._entity_extractor = entity_extractor
        self._hydration_limit = hydration_limit
        self._idle_ttl_seconds = idle_ttl_seconds
        self._clock = clock or time

        self._projections: dict[str, WorkspaceWorkingMemoryProjection] = {}
        # workspace_id -> monotonic timestamp of last use, for the idle sweep.
        self._last_used: dict[str, float] = {}
        # workspace_id -> reason the projection is not serving. Non-empty is
        # the observable "hot recall is degraded" state; it is set loudly and
        # cleared only by a successful (re)construction.
        self._degraded: dict[str, str] = {}
        self._evictions = 0

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def workspace_id(self) -> str:
        """The Workspace this manager was wired for (the container's)."""
        return self._default_workspace_id

    @property
    def evictions(self) -> int:
        return self._evictions

    @property
    def active_workspace_ids(self) -> list[str]:
        return sorted(self._projections)

    def degraded_reason(self, workspace_id: str | None = None) -> str:
        """Why the named Workspace's hot path is not serving ('' = healthy)."""
        return self._degraded.get(self._resolve(workspace_id), "")

    def projection(self, workspace_id: str | None = None) -> WorkspaceWorkingMemoryProjection:
        """Get or lazily construct the named Workspace's projection.

        Construction failure is *the* Ladybug-backend failure mode (a library
        that cannot open its database, for instance). It is logged at error
        level with the reason, recorded in :meth:`degraded_reason`, and raised
        — callers that cannot have a working graph must know, not guess.
        """
        wid = self._resolve(workspace_id)
        self._last_used[wid] = self._clock.monotonic()
        existing = self._projections.get(wid)
        if existing is not None:
            return existing
        try:
            projection = WorkspaceWorkingMemoryProjection(
                workspace_id=wid,
                embedding_client=self._embedding_client,
                embedding_model=self._embedding_model,
                entity_extractor=self._entity_extractor,
            )
        except Exception as error:
            reason = f"working-memory backend init failed for workspace '{wid}': {error}"
            self._degraded[wid] = reason
            logger.error("%s", reason)
            raise WorkingMemoryError(reason) from error
        self._projections[wid] = projection
        self._degraded.pop(wid, None)
        return projection

    # ------------------------------------------------------------------
    # Hydration
    # ------------------------------------------------------------------

    async def ensure_hydrated(
        self,
        *,
        workspace_id: str | None = None,
        force: bool = False,
        memories: list[EpisodicMemory] | None = None,
    ) -> bool:
        """Lazily hydrate the named Workspace's projection from durable truth.

        Idempotent: :meth:`WorkingMemory.hydrate` recognises records whose
        durable (content, weight) has not moved, so calling this on every
        retrieval costs one scoped ``list_by_scope`` read and no re-indexing.

        Because every ``list_by_scope`` implementation filters deleted
        records, the snapshot path cannot carry the explicit tombstones
        ``hydrate`` consumes; the snapshot is therefore reconciled by ID
        after hydration — projection records absent from the durable read
        are dropped, so consolidations that delete or absorb a memory stop
        leaving it searchable here.

        Returns True when the projection is serving, False when hydration
        could not run — with the failure logged at error/warning level and
        recorded in :meth:`degraded_reason`. It does not raise for *source*
        read failures, because a retrieval caller wants its fallback path,
        not an exception; pass ``memories`` explicitly when the caller wants
        raw ``WorkingMemoryError`` semantics instead.
        """
        wid = self._resolve(workspace_id)
        try:
            projection = self.projection(wid)
        except WorkingMemoryError:
            return False
        if force:
            # Suspicion of in-place corruption: discard the derived state and
            # re-derive it. Costs one full re-index; guarantees the projection
            # is rebuilt from durable truth rather than trusted.
            await projection.reset()
        stale = None
        if memories is None:
            try:
                memories = await self._episodic_store.list_by_scope(
                    min_weight=0.0, limit=self._hydration_limit
                )
            except Exception as error:
                reason = f"working-memory hydration read failed for workspace '{wid}': {error}"
                self._degraded[wid] = reason
                logger.error("%s", reason)
                return False
            # The snapshot excludes deleted records, so hydrate() never sees
            # their tombstones; reconcile by ID instead (see docstring).
            durable_ids = {m.memory_id for m in memories}
            stale = [
                r.memory_id for r in projection.records() if r.memory_id not in durable_ids
            ]
        await projection.hydrate(memories)
        if stale:
            for memory_id in stale:
                await projection.delete(memory_id)
            logger.info(
                "working-memory[%s]: reconciled %d record(s) missing from durable snapshot",
                wid,
                len(stale),
            )
        return True

    async def hydrate_workspace(
        self, memories: list[EpisodicMemory], *, workspace_id: str | None = None
    ) -> HydrationReport:
        """Hydrate from an explicit record list and surface the report.

        This is the path that *raises*: a caller that handed over records
        wants the ``HydrationReport``, and a backend failure here is an
        exception, not a degraded boolean.
        """
        projection = self.projection(workspace_id)
        return await projection.hydrate(memories)

    # ------------------------------------------------------------------
    # Eviction / rebuild
    # ------------------------------------------------------------------

    def evict(self, workspace_id: str | None = None) -> bool:
        """Drop the named Workspace's projection. Durable state is untouched."""
        wid = self._resolve(workspace_id)
        if wid not in self._projections:
            return False
        del self._projections[wid]
        self._last_used.pop(wid, None)
        self._evictions += 1
        logger.info("working-memory[%s]: projection evicted", wid)
        return True

    def evict_idle(self, *, now: float | None = None) -> list[str]:
        """Evict projections idle beyond the TTL. Returns the evicted ids."""
        moment = self._clock.monotonic() if now is None else now
        idle = [
            wid
            for wid, used in self._last_used.items()
            if moment - used > self._idle_ttl_seconds and wid in self._projections
        ]
        for wid in idle:
            self.evict(wid)
        return idle

    async def rebuild(self, *, workspace_id: str | None = None) -> bool:
        """Discard the projection and rehydrate from the authoritative store.

        The corruption path (ADR-082226-5104 §6): "if a projection is
        corrupted, throw it away and rebuild it." No durable write happens
        anywhere on this path, so a rebuild cannot lose or change authoritative
        state — that is the property the conformance tests pin.
        """
        wid = self._resolve(workspace_id)
        self.evict(wid)
        return await self.ensure_hydrated(workspace_id=wid, force=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve(self, workspace_id: str | None) -> str:
        return workspace_id if workspace_id else self._default_workspace_id

    def __iter__(self) -> Iterator[WorkingMemory]:
        return iter(self._projections.values())
