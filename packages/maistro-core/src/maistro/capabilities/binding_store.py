"""Canonical authority for resolving consumer Bindings at effect time.

A Binding identifier is only a reference. It grants nothing until this store
resolves the immutable Binding against the canonical Workspace, Project, Node,
and Capability of the execution requesting it. That makes a Graph parameter or
Agent declaration unable to authorize itself merely by naming an id.

The in-memory implementation is the process-local M1 authority used by the
composition seam in :mod:`maistro.capabilities.effect_context`. Durable Binding
persistence can implement the same protocol without changing effect consumers.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import aiosqlite
    import asyncpg

from maistro.capabilities.binding import Binding


class BindingResolutionError(RuntimeError):
    """A referenced Binding cannot authorize the requested effect."""


class BindingNotFound(BindingResolutionError):
    """The requested Binding identity has no registered definition."""


class BindingScopeDenied(BindingResolutionError):
    """A Binding exists but does not cover the requesting execution scope."""


@runtime_checkable
class BindingStore(Protocol):
    """Canonical Binding definition and scope-resolution contract."""

    async def put(self, binding: Binding) -> Binding: ...

    async def get(self, binding_id: str) -> Binding | None: ...

    async def resolve(
        self,
        binding_id: str,
        *,
        workspace_id: str,
        project_id: str,
        node_id: str,
        capability: str,
    ) -> Binding: ...


def _same_binding_definition(existing: Binding, candidate: Binding) -> bool:
    """Treat a startup reload's generated timestamp as non-semantic."""
    return existing.model_dump(exclude={"created_at"}) == candidate.model_dump(
        exclude={"created_at"}
    )


def _resolve_binding(
    binding: Binding | None,
    binding_id: str,
    *,
    workspace_id: str,
    project_id: str,
    node_id: str,
    capability: str,
) -> Binding:
    """Apply the one canonical scope check to every Binding backend."""
    required = {
        "binding_id": binding_id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "node_id": node_id,
        "capability": capability,
    }
    for field, value in required.items():
        if not value.strip():
            raise BindingScopeDenied(f"{field} is required to resolve a Binding")
    if binding is None:
        raise BindingNotFound(f"Binding {binding_id!r} is not registered")
    if binding.workspace_id != workspace_id:
        raise BindingScopeDenied(
            f"Binding {binding_id!r} belongs to Workspace {binding.workspace_id!r}, "
            f"not {workspace_id!r}"
        )
    if binding.project_id != project_id:
        raise BindingScopeDenied(
            f"Binding {binding_id!r} belongs to Project {binding.project_id!r}, not {project_id!r}"
        )
    if binding.node_id and binding.node_id != node_id:
        raise BindingScopeDenied(
            f"Binding {binding_id!r} is restricted to Node {binding.node_id!r}, not {node_id!r}"
        )
    if binding.capability != capability:
        raise BindingScopeDenied(
            f"Binding {binding_id!r} authorizes Capability {binding.capability!r}, "
            f"not {capability!r}"
        )
    return binding


class InMemoryBindingStore:
    """Concurrency-safe process-local BindingStore.

    Binding identities are immutable. Re-registering the exact same Binding is
    idempotent; trying to change the definition behind an existing id is
    rejected instead of silently widening authority.
    """

    def __init__(self) -> None:
        self._items: dict[str, Binding] = {}
        self._lock = asyncio.Lock()

    async def put(self, binding: Binding) -> Binding:
        async with self._lock:
            existing = self._items.get(binding.binding_id)
            if existing is not None and not _same_binding_definition(existing, binding):
                raise ValueError(
                    f"Binding {binding.binding_id!r} is immutable and already registered"
                )
            persisted = binding.model_copy(deep=True)
            self._items[binding.binding_id] = persisted
            return persisted.model_copy(deep=True)

    async def get(self, binding_id: str) -> Binding | None:
        item = self._items.get(binding_id)
        return item.model_copy(deep=True) if item is not None else None

    async def resolve(
        self,
        binding_id: str,
        *,
        workspace_id: str,
        project_id: str,
        node_id: str,
        capability: str,
    ) -> Binding:
        return _resolve_binding(
            await self.get(binding_id),
            binding_id,
            workspace_id=workspace_id,
            project_id=project_id,
            node_id=node_id,
            capability=capability,
        )


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_bindings (
    binding_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


class SqliteBindingStore:
    """Durable BindingStore for single-instance SQLite deployments."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        await self._conn.executescript(_SQLITE_SCHEMA)
        await self._conn.commit()

    async def put(self, binding: Binding) -> Binding:
        async with self._lock:
            cursor = await self._conn.execute(
                "SELECT payload_json FROM capability_bindings WHERE binding_id = ?",
                (binding.binding_id,),
            )
            row = await cursor.fetchone()
            if row is not None:
                existing = Binding.model_validate_json(str(row[0]))
                if not _same_binding_definition(existing, binding):
                    raise ValueError(
                        f"Binding {binding.binding_id!r} is immutable and already registered"
                    )
                return existing.model_copy(deep=True)
            await self._conn.execute(
                "INSERT OR IGNORE INTO capability_bindings "
                "(binding_id, workspace_id, project_id, payload_json) VALUES (?,?,?,?)",
                (
                    binding.binding_id,
                    binding.workspace_id,
                    binding.project_id,
                    binding.model_dump_json(),
                ),
            )
            await self._conn.commit()
            stored = await self.get(binding.binding_id)
            if stored is None:  # pragma: no cover - insert or conflict guarantees a row
                raise RuntimeError(f"Binding {binding.binding_id!r} disappeared after registration")
            if not _same_binding_definition(stored, binding):
                raise ValueError(
                    f"Binding {binding.binding_id!r} is immutable and already registered"
                )
            return stored.model_copy(deep=True)

    async def get(self, binding_id: str) -> Binding | None:
        cursor = await self._conn.execute(
            "SELECT payload_json FROM capability_bindings WHERE binding_id = ?",
            (binding_id,),
        )
        row = await cursor.fetchone()
        return Binding.model_validate_json(str(row[0])) if row is not None else None

    async def resolve(
        self,
        binding_id: str,
        *,
        workspace_id: str,
        project_id: str,
        node_id: str,
        capability: str,
    ) -> Binding:
        return _resolve_binding(
            await self.get(binding_id),
            binding_id,
            workspace_id=workspace_id,
            project_id=project_id,
            node_id=node_id,
            capability=capability,
        )


class PgBindingStore:
    """Durable BindingStore for shared PostgreSQL deployments."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", 0x6D61_6962)
            await conn.execute(
                """CREATE TABLE IF NOT EXISTS capability_bindings (
                    binding_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    payload_json JSONB NOT NULL
                )"""
            )

    async def put(self, binding: Binding) -> Binding:
        await self._pool.execute(
            """INSERT INTO capability_bindings
               (binding_id, workspace_id, project_id, payload_json)
               VALUES ($1,$2,$3,$4::jsonb)
               ON CONFLICT (binding_id) DO NOTHING""",
            binding.binding_id,
            binding.workspace_id,
            binding.project_id,
            binding.model_dump_json(),
        )
        existing = await self.get(binding.binding_id)
        if existing is None:  # pragma: no cover - insert or conflict guarantees a row
            raise RuntimeError(f"Binding {binding.binding_id!r} disappeared after registration")
        if not _same_binding_definition(existing, binding):
            raise ValueError(f"Binding {binding.binding_id!r} is immutable and already registered")
        return existing.model_copy(deep=True)

    async def get(self, binding_id: str) -> Binding | None:
        row = await self._pool.fetchrow(
            "SELECT payload_json FROM capability_bindings WHERE binding_id = $1",
            binding_id,
        )
        if row is None:
            return None
        payload = row["payload_json"]
        return (
            Binding.model_validate_json(payload)
            if isinstance(payload, str)
            else Binding.model_validate(payload)
        )

    async def resolve(
        self,
        binding_id: str,
        *,
        workspace_id: str,
        project_id: str,
        node_id: str,
        capability: str,
    ) -> Binding:
        return _resolve_binding(
            await self.get(binding_id),
            binding_id,
            workspace_id=workspace_id,
            project_id=project_id,
            node_id=node_id,
            capability=capability,
        )


__all__ = [
    "BindingNotFound",
    "BindingResolutionError",
    "BindingScopeDenied",
    "BindingStore",
    "InMemoryBindingStore",
    "PgBindingStore",
    "SqliteBindingStore",
]
