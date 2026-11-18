"""Backend composition for canonical Event persistence and publication (#61)."""

from __future__ import annotations

from typing import Any

from maistro.events.bus import EventBus
from maistro.events.envelope import EventStore, InMemoryEventStore, SqliteEventStore
from maistro.events.handlers import install_builtin_handlers
from maistro.events.publisher import CanonicalEventPublisher
from maistro.events.recipes import install_builtin_recipes


def wire_legacy_trigger_surface(bus: EventBus) -> None:
    """Subscribe ADR-086 builtin handlers and recipe catalog on the legacy bus.

    Called from process container construction (#2313) so ``maistro.events.handlers``
    and ``maistro.events.recipes`` are reachable production surfaces. Recipe
    triggers are installed disabled — ops enable after configuring endpoints —
    which does not weaken #836 (disabled triggers never match / never fire).
    """
    install_builtin_handlers(bus)
    install_builtin_recipes(bus, enabled=False)


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


__all__ = ["wire_canonical_events", "wire_legacy_trigger_surface"]
