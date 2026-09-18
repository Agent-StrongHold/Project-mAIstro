"""Trigger definitions and glob pattern matching (ADR-086 / SPEC-070226-b234).

A trigger is a declarative ``(event-pattern -> handler)`` rule — data, not
code. Patterns are dot-segmented globs: ``agent.*`` matches ``agent.created``
and ``agent.delegated`` but NOT ``task.created`` and NOT ``agent.task.created``
(a ``*`` matches exactly one dot-separated segment).

Distinct from the richer, payload-condition :class:`maistro.events.bus.Trigger`
used by the in-memory bus; this store backs the durable reactor loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import uuid4

if TYPE_CHECKING:
    import aiosqlite


def pattern_matches(pattern: str, event_type: str) -> bool:
    """Segment-wise glob match of ``pattern`` against ``event_type``.

    Both are split on ``.``; segment counts must be equal and each pattern
    segment is glob-matched (``fnmatch``) against the corresponding event
    segment. So ``agent.*`` matches ``agent.created`` but neither
    ``task.created`` nor ``agent.task.created``.
    """
    if not pattern or not event_type:
        return False
    pattern_parts = pattern.split(".")
    event_parts = event_type.split(".")
    if len(pattern_parts) != len(event_parts):
        return False
    return all(fnmatchcase(ev, pat) for pat, ev in zip(pattern_parts, event_parts, strict=True))


@dataclass
class TriggerDefinition:
    """Declarative trigger: event pattern -> handler endpoint."""

    trigger_id: str = field(default_factory=lambda: uuid4().hex[:8])
    name: str = ""
    event_pattern: str = ""
    handler_url: str = ""
    enabled: bool = True

    def matches(self, event_type: str) -> bool:
        return self.enabled and pattern_matches(self.event_pattern, event_type)


@runtime_checkable
class TriggerStore(Protocol):
    """Store of durable trigger definitions."""

    async def add(self, trigger: TriggerDefinition) -> None: ...

    async def get(self, trigger_id: str) -> TriggerDefinition | None: ...

    async def remove(self, trigger_id: str) -> None: ...

    async def list_triggers(self) -> list[TriggerDefinition]: ...

    async def get_matching(self, event_type: str) -> list[TriggerDefinition]:
        """Return enabled triggers whose pattern matches ``event_type``."""
        ...

    async def set_enabled(self, trigger_id: str, enabled: bool) -> None: ...


class InMemoryTriggerStore:
    """In-memory :class:`TriggerStore`."""

    def __init__(self) -> None:
        self._triggers: dict[str, TriggerDefinition] = {}
        self._lock = asyncio.Lock()

    async def add(self, trigger: TriggerDefinition) -> None:
        async with self._lock:
            self._triggers[trigger.trigger_id] = trigger

    async def get(self, trigger_id: str) -> TriggerDefinition | None:
        return self._triggers.get(trigger_id)

    async def remove(self, trigger_id: str) -> None:
        async with self._lock:
            self._triggers.pop(trigger_id, None)

    async def list_triggers(self) -> list[TriggerDefinition]:
        return list(self._triggers.values())

    async def get_matching(self, event_type: str) -> list[TriggerDefinition]:
        return [t for t in self._triggers.values() if t.matches(event_type)]

    async def set_enabled(self, trigger_id: str, enabled: bool) -> None:
        async with self._lock:
            trigger = self._triggers.get(trigger_id)
            if trigger is not None:
                trigger.enabled = enabled


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trigger_definitions (
    trigger_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    event_pattern TEXT NOT NULL DEFAULT '',
    handler_url TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1
)
"""


class SqliteTriggerStore:
    """SQLite-backed :class:`TriggerStore`.

    Pattern matching happens in Python (glob semantics are not expressible in
    portable SQL), so ``get_matching`` loads enabled triggers and filters.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        await self._conn.execute(_SCHEMA)
        await self._conn.commit()

    async def add(self, trigger: TriggerDefinition) -> None:
        await self._conn.execute(
            """INSERT INTO trigger_definitions
               (trigger_id, name, event_pattern, handler_url, enabled)
               VALUES (?,?,?,?,?)
               ON CONFLICT(trigger_id) DO UPDATE SET
                 name=excluded.name, event_pattern=excluded.event_pattern,
                 handler_url=excluded.handler_url, enabled=excluded.enabled""",
            (
                trigger.trigger_id,
                trigger.name,
                trigger.event_pattern,
                trigger.handler_url,
                1 if trigger.enabled else 0,
            ),
        )
        await self._conn.commit()

    async def get(self, trigger_id: str) -> TriggerDefinition | None:
        cursor = await self._conn.execute(
            "SELECT trigger_id, name, event_pattern, handler_url, enabled "
            "FROM trigger_definitions WHERE trigger_id = ?",
            (trigger_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_trigger(tuple(row)) if row is not None else None

    async def remove(self, trigger_id: str) -> None:
        await self._conn.execute(
            "DELETE FROM trigger_definitions WHERE trigger_id = ?", (trigger_id,)
        )
        await self._conn.commit()

    async def list_triggers(self) -> list[TriggerDefinition]:
        cursor = await self._conn.execute(
            "SELECT trigger_id, name, event_pattern, handler_url, enabled FROM trigger_definitions"
        )
        rows = await cursor.fetchall()
        return [self._row_to_trigger(tuple(r)) for r in rows]

    async def get_matching(self, event_type: str) -> list[TriggerDefinition]:
        cursor = await self._conn.execute(
            "SELECT trigger_id, name, event_pattern, handler_url, enabled "
            "FROM trigger_definitions WHERE enabled = 1"
        )
        rows = await cursor.fetchall()
        triggers = [self._row_to_trigger(tuple(r)) for r in rows]
        return [t for t in triggers if t.matches(event_type)]

    async def set_enabled(self, trigger_id: str, enabled: bool) -> None:
        await self._conn.execute(
            "UPDATE trigger_definitions SET enabled = ? WHERE trigger_id = ?",
            (1 if enabled else 0, trigger_id),
        )
        await self._conn.commit()

    @staticmethod
    def _row_to_trigger(row: tuple[object, ...]) -> TriggerDefinition:
        return TriggerDefinition(
            trigger_id=str(row[0]),
            name=str(row[1] or ""),
            event_pattern=str(row[2] or ""),
            handler_url=str(row[3] or ""),
            enabled=bool(row[4]),
        )
