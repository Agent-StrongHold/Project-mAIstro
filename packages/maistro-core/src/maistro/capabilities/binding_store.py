"""Canonical authority for resolving consumer Bindings at effect time.

A Binding identifier is only a reference. It grants nothing until this store
resolves the immutable Binding against the canonical Workspace, Project, Node,
and Capability of the execution requesting it. That makes a Graph parameter or
Agent declaration unable to authorize itself merely by naming an id.

The in-memory implementation remains the explicit ephemeral authority. SQLite
and PostgreSQL implementations persist the same immutable Binding contract so a
restart does not manufacture a new authorization universe for governed effects.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from maistro.capabilities.binding import Binding

if TYPE_CHECKING:
    import aiosqlite
    import asyncpg


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_bindings (
    binding_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    node_id TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_capability_binding_scope
    ON capability_bindings (workspace_id, project_id, capability, binding_id);
"""


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


def _scope_checked(
    binding: Binding,
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
    if binding.workspace_id != workspace_id:
        raise BindingScopeDenied(
            f"Binding {binding_id!r} belongs to Workspace {binding.workspace_id!r}, "
            f"not {workspace_id!r}"
        )
    if binding.project_id != project_id:
        raise BindingScopeDenied(
            f"Binding {binding_id!r} belongs to Project {binding.project_id!r}, "
            f"not {project_id!r}"
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


async def _resolve(
    store: BindingStore,
    binding_id: str,
    *,
    workspace_id: str,
    project_id: str,
    node_id: str,
    capability: str,
) -> Binding:
    required = (binding_id, workspace_id, project_id, node_id, capability)
    if any(not value.strip() for value in required):
        names = ("binding_id", "workspace_id", "project_id", "node_id", "capability")
        missing = names[next(i for i, value in enumerate(required) if not value.strip())]
        raise BindingScopeDenied(f"{missing} is required to resolve a Binding")
    binding = await store.get(binding_id)
    if binding is None:
        raise BindingNotFound(f"Binding {binding_id!r} is not registered")
    return _scope_checked(
        binding,
        binding_id=binding_id,
        workspace_id=workspace_id,
        project_id=project_id,
        node_id=node_id,
        capability=capability,
    )


class InMemoryBindingStore:
    """Concurrency-safe process-local BindingStore for explicit ephemeral use."""

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
        return await _resolve(
            self,
            binding_id,
            workspace_id=workspace_id,
            project_id=project_id,
            node_id=node_id,
            capability=capability,
        )


class SqliteBindingStore:
    """SQLite-backed immutable Binding authority."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        await self._conn.executescript(_SQLITE_SCHEMA)
        await self._conn.commit()

    async def put(self, binding: Binding) -> Binding:
        async with self._lock:
            existing = await self.get(binding.binding_id)
            if existing is not None:
                if existing != binding:
                    raise ValueError(
                        f"Binding {binding.binding_id!r} is immutable and already registered"
                    )
                return existing
            await self._conn.execute(
                """INSERT INTO capability_bindings (
                    binding_id, workspace_id, project_id, capability, node_id,
                    created_at, payload_json
                ) VALUES (?,?,?,?,?,?,?)""",
                (
                    binding.binding_id,
                    binding.workspace_id,
                    binding.project_id,
                    binding.capability,
                    binding.node_id,
                    binding.created_at.timestamp(),
                    binding.model_dump_json(),
                ),
            )
            await self._conn.commit()
        return binding.model_copy(deep=True)

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
        return await _resolve(
            self,
            binding_id,
            workspace_id=workspace_id,
            project_id=project_id,
            node_id=node_id,
            capability=capability,
        )


class PgBindingStore:
    """PostgreSQL-backed immutable Binding authority shared by replicas."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def put(self, binding: Binding) -> Binding:
        await self._pool.execute(
            """INSERT INTO capability_bindings (
                binding_id, workspace_id, project_id, capability, node_id,
                created_at, payload_json
            ) VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (binding_id) DO NOTHING""",
            binding.binding_id,
            binding.workspace_id,
            binding.project_id,
            binding.capability,
            binding.node_id,
            binding.created_at,
            binding.model_dump_json(),
        )
        persisted = await self.get(binding.binding_id)
        if persisted is None:
            raise RuntimeError(f"Binding {binding.binding_id!r} was not persisted")
        if persisted != binding:
            raise ValueError(
                f"Binding {binding.binding_id!r} is immutable and already registered"
            )
        return persisted

    async def get(self, binding_id: str) -> Binding | None:
        payload = await self._pool.fetchval(
            "SELECT payload_json FROM capability_bindings WHERE binding_id = $1",
            binding_id,
        )
        return Binding.model_validate_json(str(payload)) if payload is not None else None

    async def resolve(
        self,
        binding_id: str,
        *,
        workspace_id: str,
        project_id: str,
        node_id: str,
        capability: str,
    ) -> Binding:
        return await _resolve(
            self,
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