"""Backend composition for canonical Event persistence and publication (#61)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maistro.events.bus import EventBus
from maistro.events.envelope import EventStore, InMemoryEventStore, SqliteEventStore
from maistro.events.handlers import install_builtin_handlers
from maistro.events.processing import (
    CanonicalProjectionStore,
    InMemoryCanonicalProjectionStore,
    InMemoryProjectionFailureStore,
    ProjectionFailureStore,
)
from maistro.events.publisher import CanonicalEventPublisher
from maistro.events.recipes import install_builtin_recipes


@dataclass(frozen=True)
class CanonicalProjection:
    """The replayable canonical-Envelope -> durable-log projection seam (#2506).

    ``projection_store`` holds the per-stream replay cursor (registered at the
    canonical watermark, claimed under a lease, advanced under a fence) and
    ``failure_store`` the poison bookkeeping. Both live beside the canonical
    EventStore they scan, so a healed trigger log survives every restart and
    is shared by every replica that shares the canonical database.
    """

    projection_store: CanonicalProjectionStore
    failure_store: ProjectionFailureStore


def wire_legacy_trigger_surface(bus: EventBus) -> None:
    """Subscribe ADR-086 builtin handlers and recipe catalog on the legacy bus.

    Called from process container construction (#2313) so ``maistro.events.handlers``
    and ``maistro.events.recipes`` are reachable production surfaces. Recipe
    triggers are installed disabled — ops enable after configuring endpoints —
    which does not weaken #836 (disabled triggers never match / never fire).
    """
    install_builtin_handlers(bus)
    install_builtin_recipes(bus, enabled=False)


async def wire_canonical_projection(*, event_store: Any) -> CanonicalProjection:
    """Compose the canonical-log projection stores beside their canonical store (#2506).

    The canonical EventStore in hand decides the backend: a `PgEventStore`
    projects onto that store's pool, a `SqliteEventStore` onto that store's own
    connection, anything else projects in memory beside the store. The
    projection cursor reads the canonical watermark table during registration,
    so it must live in the same database the canonical EventStore writes —
    and the store is the only reliable statement of which database that is.
    A container may be handed a fully composed `effect_context` whose event
    authority was built on a different database than the container's own
    stores (or is in-memory inside a durable container), so selecting the
    projection from separately supplied pools read a watermark — or found no
    watermark table at all — in the wrong place (#2506 review).
    """
    from maistro.events.pg_envelope import PgEventStore

    if isinstance(event_store, PgEventStore):
        from maistro.events.pg_stores import PgCanonicalProjectionStore, PgProjectionFailureStore

        return CanonicalProjection(
            projection_store=PgCanonicalProjectionStore(event_store.pool),
            failure_store=PgProjectionFailureStore(event_store.pool),
        )
    if isinstance(event_store, SqliteEventStore):
        from maistro.events.processing import (
            SqliteCanonicalProjectionStore,
            SqliteProjectionFailureStore,
        )

        projection_store = SqliteCanonicalProjectionStore(event_store.conn)
        failure_store = SqliteProjectionFailureStore(event_store.conn)
        await projection_store.ensure_schema()
        await failure_store.ensure_schema()
        return CanonicalProjection(
            projection_store=projection_store,
            failure_store=failure_store,
        )
    return CanonicalProjection(
        projection_store=InMemoryCanonicalProjectionStore(event_store),
        failure_store=InMemoryProjectionFailureStore(),
    )


async def wire_canonical_events(
    *,
    pg_pool: Any = None,
    db_pool: Any = None,
    legacy_bus: EventBus | None = None,
) -> CanonicalEventPublisher:
    """Select the one canonical Event sequencing authority for this process."""
    store: EventStore
    if pg_pool is not None:
        from maistro.events.pg_envelope import PgEventStore

        pg_store = PgEventStore(pg_pool)
        await pg_store.ensure_schema()
        store = pg_store
    elif db_pool is not None:
        sqlite_store = SqliteEventStore(db_pool)
        await sqlite_store.ensure_schema()
        store = sqlite_store
    else:
        store = InMemoryEventStore()
    return CanonicalEventPublisher(store, legacy_bus=legacy_bus)


__all__ = [
    "CanonicalProjection",
    "wire_canonical_events",
    "wire_canonical_projection",
    "wire_legacy_trigger_surface",
]
