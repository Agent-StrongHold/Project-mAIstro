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


class BindingDisabled(BindingResolutionError):
    """A Binding exists but has been disabled by its owner or policy."""


def _validate_scope(
    binding: Binding | None,
    *,
    binding_id: str,
    workspace_id: str,
    project_id: str,
    node_id: str,
    capability: str,
) -> Binding:
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
    if not binding.enabled:
        raise BindingDisabled(f"Binding {binding_id!r} is disabled")
    return binding


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


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_bindings (
    binding_id TEXT PRIMARY KEY,
    binding_json TEXT NOT NULL
);
"""


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
            if existing is not None and existing != binding:
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
        return _validate_scope(
            await self.get(binding_id),
            binding_id=binding_id,
            workspace_id=workspace_id,
            project_id=project_id,
            node_id=node_id,
            capability=capability,
        )


class SqliteBindingStore:
    """SQLite-backed Binding authority shared by all nodes in one container."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        await self._conn.executescript(_SQLITE_SCHEMA)
        await self._conn.commit()

    async def put(self, binding: Binding) -> Binding:
        async with self._lock:
            existing = await self.get(binding.binding_id)
            if existing is not None and existing != binding:
                raise ValueError(
                    f"Binding {binding.binding_id!r} is immutable and already registered"
                )
            if existing is None:
                await self._conn.execute(
                    "INSERT INTO capability_bindings (binding_id, binding_json) VALUES (?, ?)",
                    (binding.binding_id, binding.model_dump_json()),
                )
                await self._conn.commit()
            return binding.model_copy(deep=True)

    async def get(self, binding_id: str) -> Binding | None:
        cursor = await self._conn.execute(
            "SELECT binding_json FROM capability_bindings WHERE binding_id = ?",
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
        return _validate_scope(
            await self.get(binding_id),
            binding_id=binding_id,
            workspace_id=workspace_id,
            project_id=project_id,
            node_id=node_id,
            capability=capability,
        )


class PgBindingStore:
    """PostgreSQL-backed Binding authority with immutable identity semantics."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_bindings (
                    binding_id TEXT PRIMARY KEY,
                    binding_json JSONB NOT NULL
                )
                """
            )

    async def put(self, binding: Binding) -> Binding:
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT binding_json FROM capability_bindings WHERE binding_id = $1 FOR UPDATE",
                binding.binding_id,
            )
            if row is not None:
                existing = Binding.model_validate(row["binding_json"])
                if existing != binding:
                    raise ValueError(
                        f"Binding {binding.binding_id!r} is immutable and already registered"
                    )
                return existing.model_copy(deep=True)
            await conn.execute(
                "INSERT INTO capability_bindings (binding_id, binding_json) VALUES ($1, $2::jsonb)",
                binding.binding_id,
                binding.model_dump_json(),
            )
            return binding.model_copy(deep=True)

    async def get(self, binding_id: str) -> Binding | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT binding_json FROM capability_bindings WHERE binding_id = $1",
                binding_id,
            )
        return Binding.model_validate(row["binding_json"]) if row is not None else None

    async def resolve(
        self,
        binding_id: str,
        *,
        workspace_id: str,
        project_id: str,
        node_id: str,
        capability: str,
    ) -> Binding:
        return _validate_scope(
            await self.get(binding_id),
            binding_id=binding_id,
            workspace_id=workspace_id,
            project_id=project_id,
            node_id=node_id,
            capability=capability,
        )


__all__ = [
    "BindingDisabled",
    "BindingNotFound",
    "BindingResolutionError",
    "BindingScopeDenied",
    "BindingStore",
    "InMemoryBindingStore",
    "PgBindingStore",
    "SqliteBindingStore",
]
