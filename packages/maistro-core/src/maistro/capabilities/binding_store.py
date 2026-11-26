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
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from maistro.capabilities.binding import Binding

if TYPE_CHECKING:
    import aiosqlite
    import asyncpg


# Column layout matches Alembic revision 040 (`capability_bindings`): the JSON
# payload preserves the complete immutable record while the projected columns
# keep scope lookups indexed and auditable.
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
-- A tombstone, not a column. `revoke` deletes the binding row -- that is what
-- makes a revoked identity unrecoverable -- so a `revoked_at` on
-- `capability_bindings` would be deleted along with the thing it forbids, and
-- the id could be re-registered by an actor that still remembers it (#846).
CREATE TABLE IF NOT EXISTS capability_binding_revocations (
    binding_id TEXT PRIMARY KEY,
    revoked_at REAL NOT NULL
);
"""


class BindingResolutionError(RuntimeError):
    """A referenced Binding cannot authorize the requested effect."""


class BindingNotFound(BindingResolutionError):
    """The requested Binding identity has no registered definition."""


class BindingScopeDenied(BindingResolutionError):
    """A Binding exists but does not cover the requesting execution scope."""


class BindingDisabled(BindingResolutionError):
    """A Binding exists but its operator disabled it, so it authorizes nothing."""


@runtime_checkable
class BindingStore(Protocol):
    """Canonical Binding definition and scope-resolution contract.

    Implementable by both the ephemeral in-memory authority and durable
    (SQLite/PostgreSQL) backends: every member is either async or usable at
    boot over an open connection.
    """

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


@runtime_checkable
class RevocableBindingStore(BindingStore, Protocol):
    """A BindingStore that additionally supports operator revocation (#846).

    Every backend implements this as of #1133: a capability can be cut off
    for already-constructed actors without a process restart, and on SQLite
    or PostgreSQL the revocation outlives the process that issued it.

    ``register`` is deliberately *not* here. It was, while
    :class:`InMemoryBindingStore` was the only implementation -- declared
    sync, because that store needs no I/O to register. No durable store can
    satisfy a synchronous write, so the one member that made this contract
    unmeetable was the member no effect path uses. Revocation is what the
    runtime needs from this protocol, and revocation is what it asks for.

    Boot registration is :meth:`BindingStore.put`, which every backend
    implements and which has the semantics boot needs on all three:
    idempotent for an identical Binding, ``ValueError`` for a changed one,
    and ``BindingNotFound`` over a revocation tombstone -- so a restart
    cannot re-grant an identity an operator withdrew. hive-conductor's
    self_repair and harness route went through the in-memory ``register``
    and narrowed to that concrete class first, which turned both off on
    exactly the deployments that persist anything; they call ``put`` now
    (#1133).
    """

    async def revoke(self, binding_id: str) -> None: ...


async def register_boot_binding(bindings: BindingStore, binding: Binding) -> Binding:
    """Register a composition-time Binding once, and again on every restart.

    Returns the registered record, which after the first boot is the one
    already stored. A durable store compares the *whole* Binding, and a
    freshly constructed one differs from the stored copy by ``created_at``
    alone -- so a composition root that simply re-``put`` its boot Binding
    succeeded on the first boot and raised ``ValueError`` on every one after,
    taking the capability offline exactly when the deployment persisted
    anything (Codex, #1760).

    Reusing the stored record rather than stamping a fixed ``created_at``
    keeps the real first-registration time, which is the only thing that
    timestamp is for.

    A *changed* definition is still refused. Equality is checked with the
    candidate's own ``created_at`` substituted in, so the comparison asks the
    question that matters -- has this identity been redefined -- rather than
    the one that is answered differently on every process start.

    Revocation survives this: a revoked identity is absent from ``get`` and
    refused by ``put``, so a restart cannot re-grant what an operator withdrew.
    """

    existing = await bindings.get(binding.binding_id)
    if existing is None:
        return await bindings.put(binding)
    if existing.model_copy(update={"created_at": binding.created_at}) != binding:
        raise ValueError(
            f"Binding {binding.binding_id!r} is registered with a different definition; "
            "a boot Binding is immutable and cannot be redefined in place"
        )
    return existing


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
    if binding.disabled:
        raise BindingDisabled(f"Binding {binding_id!r} is disabled and cannot authorize effects")
    return _scope_checked(
        binding,
        binding_id=binding_id,
        workspace_id=workspace_id,
        project_id=project_id,
        node_id=node_id,
        capability=capability,
    )


class InMemoryBindingStore:
    """Concurrency-safe process-local BindingStore for explicit ephemeral use.

    Binding identities are immutable. Re-registering the exact same Binding is
    idempotent; trying to change the definition behind an existing id is
    rejected instead of silently widening authority.
    """

    def __init__(self) -> None:
        self._items: dict[str, Binding] = {}
        self._revoked: set[str] = set()
        self._lock = asyncio.Lock()

    async def put(self, binding: Binding) -> Binding:
        async with self._lock:
            return self._put_locked(binding)

    def register(self, binding: Binding) -> Binding:
        """Register a boot-time Binding without creating a runtime grant.

        Composition roots use this before serving requests. Runtime effect paths
        must use ``resolve``; in particular, a revoked identity can never be
        re-created by an actor that still remembers its id.

        Not part of :class:`RevocableBindingStore`: it is synchronous because
        this store needs no I/O, and that is precisely what no durable
        backend can offer.
        """
        if binding.binding_id in self._revoked:
            raise BindingNotFound(f"Binding {binding.binding_id!r} has been revoked")
        return self._put_locked(binding)

    def _put_locked(self, binding: Binding) -> Binding:
        if binding.binding_id in self._revoked:
            raise BindingNotFound(f"Binding {binding.binding_id!r} has been revoked")
        existing = self._items.get(binding.binding_id)
        if existing is not None and existing != binding:
            raise ValueError(f"Binding {binding.binding_id!r} is immutable and already registered")
        persisted = binding.model_copy(deep=True)
        self._items[binding.binding_id] = persisted
        return persisted.model_copy(deep=True)

    async def revoke(self, binding_id: str) -> None:
        """Withdraw a Binding permanently for this store's lifetime."""
        async with self._lock:
            self._items.pop(binding_id, None)
            self._revoked.add(binding_id)

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
        if binding_id in self._revoked:
            # Revocation is a distinct denial: the identity is known and
            # forbidden, never merely "unknown" (#846).
            raise BindingNotFound(f"Binding {binding_id!r} has been revoked")
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

    async def _is_revoked(self, binding_id: str) -> bool:
        cursor = await self._conn.execute(
            "SELECT 1 FROM capability_binding_revocations WHERE binding_id = ?",
            (binding_id,),
        )
        return await cursor.fetchone() is not None

    async def put(self, binding: Binding) -> Binding:
        async with self._lock:
            return await self._put_locked(binding)

    async def _put_locked(self, binding: Binding) -> Binding:
        if await self._is_revoked(binding.binding_id):
            raise BindingNotFound(f"Binding {binding.binding_id!r} has been revoked")
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

    async def revoke(self, binding_id: str) -> None:
        """Withdraw a Binding permanently -- across restarts, not just this process.

        Tombstone first, then delete: if the process dies between the two the
        identity is already forbidden, which is the safe order. The reverse
        would leave a window where the binding is gone but re-registrable.
        """
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                await self._conn.execute(
                    "INSERT OR IGNORE INTO capability_binding_revocations "
                    "(binding_id, revoked_at) VALUES (?,?)",
                    (binding_id, datetime.now(UTC).timestamp()),
                )
                await self._conn.execute(
                    "DELETE FROM capability_bindings WHERE binding_id = ?",
                    (binding_id,),
                )
            except BaseException:
                await self._conn.rollback()
                raise
            await self._conn.commit()

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
        if await self._is_revoked(binding_id):
            # The identity is known and forbidden, never merely "unknown" (#846).
            raise BindingNotFound(f"Binding {binding_id!r} has been revoked")
        return await _resolve(
            self,
            binding_id,
            workspace_id=workspace_id,
            project_id=project_id,
            node_id=node_id,
            capability=capability,
        )


class PgBindingStore:
    """PostgreSQL-backed immutable Binding authority shared by replicas.

    ``ensure_schema`` mirrors Alembic revision 040 so a deployment that has not
    run migrations (local composition, tests) still gets the same table shape
    the migration owns in production.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_bindings (
                    binding_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    node_id TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_capability_binding_scope
                    ON capability_bindings (workspace_id, project_id, capability, binding_id)
                """
            )
            # Revocation tombstones (#1133). Created here as well as by alembic
            # 047 so an effect context built outside the migration path does
            # not query a table that does not exist.
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_binding_revocations (
                    binding_id TEXT PRIMARY KEY,
                    revoked_at TIMESTAMPTZ NOT NULL
                )
                """
            )

    async def _is_revoked(self, binding_id: str) -> bool:
        found = await self._pool.fetchval(
            "SELECT 1 FROM capability_binding_revocations WHERE binding_id = $1",
            binding_id,
        )
        return found is not None

    async def put(self, binding: Binding) -> Binding:
        if await self._is_revoked(binding.binding_id):
            raise BindingNotFound(f"Binding {binding.binding_id!r} has been revoked")
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
            # Either the insert lost a race with a concurrent revoke, or the
            # row never landed. Re-reading the tombstone tells the caller
            # which, instead of reporting a storage fault for a policy
            # decision another replica made.
            if await self._is_revoked(binding.binding_id):
                raise BindingNotFound(f"Binding {binding.binding_id!r} has been revoked")
            raise RuntimeError(f"Binding {binding.binding_id!r} was not persisted")
        if persisted != binding:
            raise ValueError(f"Binding {binding.binding_id!r} is immutable and already registered")
        return persisted

    async def revoke(self, binding_id: str) -> None:
        """Withdraw a Binding permanently, for every replica on this database.

        One transaction, tombstone before delete: a replica that reads
        between the two statements must see the identity as forbidden rather
        than as absent-and-re-registrable.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO capability_binding_revocations (binding_id, revoked_at) "
                "VALUES ($1,$2) ON CONFLICT (binding_id) DO NOTHING",
                binding_id,
                datetime.now(UTC),
            )
            await conn.execute(
                "DELETE FROM capability_bindings WHERE binding_id = $1",
                binding_id,
            )

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
        if await self._is_revoked(binding_id):
            # The identity is known and forbidden, never merely "unknown" (#846).
            raise BindingNotFound(f"Binding {binding_id!r} has been revoked")
        return await _resolve(
            self,
            binding_id,
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
    "RevocableBindingStore",
    "SqliteBindingStore",
    "register_boot_binding",
]
