"""Canonical concurrent Run and Attempt admission.

The Run store calls this authority for every producer. In-memory and SQLite
implementations are useful for local deployments and tests; PostgreSQL uses a
shared lease table and transaction advisory locks so replicas cannot each
believe they have the same capacity.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ConcurrencyLimits:
    """Hard ceilings. A value of one is the smallest safe configurable floor."""

    max_runs_per_principal: int = 8
    max_runs_per_workspace: int = 32
    max_runs_global: int = 128
    max_attempts_per_principal: int = 16
    max_attempts_per_workspace: int = 64
    max_attempts_global: int = 256
    lease_ttl: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        for name in (
            "max_runs_per_principal",
            "max_runs_per_workspace",
            "max_runs_global",
            "max_attempts_per_principal",
            "max_attempts_per_workspace",
            "max_attempts_global",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")
        if self.lease_ttl <= timedelta(0):
            raise ValueError("lease_ttl must be positive")

    def as_dict(self) -> dict[str, int | float]:
        return {
            "max_runs_per_principal": self.max_runs_per_principal,
            "max_runs_per_workspace": self.max_runs_per_workspace,
            "max_runs_global": self.max_runs_global,
            "max_attempts_per_principal": self.max_attempts_per_principal,
            "max_attempts_per_workspace": self.max_attempts_per_workspace,
            "max_attempts_global": self.max_attempts_global,
            "lease_ttl_seconds": self.lease_ttl.total_seconds(),
        }

    @classmethod
    def from_environment(cls) -> ConcurrencyLimits:
        """Read the same operator knobs used by Settings without importing it."""
        import os

        def integer(name: str, default: int) -> int:
            value = os.getenv(name)
            return default if value is None else int(value)

        ttl = os.getenv("RUN_ADMISSION_LEASE_TTL_SECONDS")
        return cls(
            max_runs_per_principal=integer("MAX_CONCURRENT_RUNS_PER_PRINCIPAL", 8),
            max_runs_per_workspace=integer("MAX_CONCURRENT_RUNS_PER_WORKSPACE", 32),
            max_runs_global=integer("MAX_CONCURRENT_RUNS_GLOBAL", 128),
            max_attempts_per_principal=integer("MAX_CONCURRENT_ATTEMPTS_PER_PRINCIPAL", 16),
            max_attempts_per_workspace=integer("MAX_CONCURRENT_ATTEMPTS_PER_WORKSPACE", 64),
            max_attempts_global=integer("MAX_CONCURRENT_ATTEMPTS_GLOBAL", 256),
            lease_ttl=timedelta(seconds=300 if ttl is None else int(ttl)),
        )


class RunAdmissionRejected(ValueError):
    """Admission was refused before work was created or executed."""

    def __init__(self, dimension: str, limit: int, current: int, retry_after: float) -> None:
        self.dimension = dimension
        self.limit = limit
        self.current = current
        self.retry_after = retry_after
        super().__init__(
            f"concurrent admission limit reached for {dimension}: {current}/{limit}; "
            f"retry after {retry_after:.1f}s"
        )


@dataclass(frozen=True)
class AdmissionLease:
    lease_id: str
    kind: str
    resource_id: str
    workspace_id: str
    principal_id: str
    expires_at: datetime


@dataclass(frozen=True)
class AdmissionSnapshot:
    limits: ConcurrencyLimits
    active_runs: int
    active_attempts: int
    active_run_leases: int
    active_attempt_leases: int


@runtime_checkable
class ConcurrencyAdmission(Protocol):
    async def acquire_run(
        self, run_id: str, *, workspace_id: str, principal_id: str | None
    ) -> AdmissionLease: ...

    async def acquire_attempt(
        self, attempt_id: str, *, workspace_id: str, principal_id: str | None
    ) -> AdmissionLease: ...

    async def release_run(self, run_id: str) -> None: ...

    async def release_attempt(self, attempt_id: str) -> None: ...

    async def renew_run(self, run_id: str, *, ttl: timedelta | None = None) -> bool: ...

    async def renew_attempt(self, attempt_id: str, *, ttl: timedelta | None = None) -> bool: ...

    async def reclaim_stale(self, *, now: datetime | None = None) -> int: ...

    async def snapshot(self) -> AdmissionSnapshot: ...


class InMemoryConcurrencyAdmission:
    """Atomic reference authority for one process."""

    def __init__(self, limits: ConcurrencyLimits | None = None) -> None:
        self.limits = limits or ConcurrencyLimits.from_environment()
        self._leases: dict[str, AdmissionLease] = {}
        self._lock = asyncio.Lock()

    def _purge(self, now: datetime) -> None:
        for key, lease in list(self._leases.items()):
            if lease.expires_at <= now:
                del self._leases[key]

    async def _acquire(
        self, kind: str, resource_id: str, *, workspace_id: str, principal_id: str | None
    ) -> AdmissionLease:
        async with self._lock:
            now = datetime.now(UTC)
            self._purge(now)
            principal = principal_id or "<anonymous>"
            leases = [lease for lease in self._leases.values() if lease.kind == kind]
            limits = (
                (
                    self.limits.max_runs_per_principal,
                    self.limits.max_runs_per_workspace,
                    self.limits.max_runs_global,
                )
                if kind == "run"
                else (
                    self.limits.max_attempts_per_principal,
                    self.limits.max_attempts_per_workspace,
                    self.limits.max_attempts_global,
                )
            )
            dimensions = (
                ("principal", sum(lease.principal_id == principal for lease in leases), limits[0]),
                (
                    "workspace",
                    sum(lease.workspace_id == workspace_id for lease in leases),
                    limits[1],
                ),
                ("global", len(leases), limits[2]),
            )
            for dimension, current, limit in dimensions:
                if current >= limit:
                    raise RunAdmissionRejected(
                        f"{kind}s/{dimension}",
                        limit,
                        current,
                        self.limits.lease_ttl.total_seconds(),
                    )
            lease = AdmissionLease(
                lease_id=uuid.uuid4().hex,
                kind=kind,
                resource_id=resource_id,
                workspace_id=workspace_id,
                principal_id=principal,
                expires_at=now + self.limits.lease_ttl,
            )
            self._leases[lease.lease_id] = lease
            return lease

    async def acquire_run(
        self, run_id: str, *, workspace_id: str, principal_id: str | None
    ) -> AdmissionLease:
        return await self._acquire(
            "run", run_id, workspace_id=workspace_id, principal_id=principal_id
        )

    async def acquire_attempt(
        self, attempt_id: str, *, workspace_id: str, principal_id: str | None
    ) -> AdmissionLease:
        return await self._acquire(
            "attempt", attempt_id, workspace_id=workspace_id, principal_id=principal_id
        )

    async def _release(self, kind: str, resource_id: str) -> None:
        async with self._lock:
            for key, lease in list(self._leases.items()):
                if lease.kind == kind and lease.resource_id == resource_id:
                    del self._leases[key]

    async def release_run(self, run_id: str) -> None:
        await self._release("run", run_id)

    async def release_attempt(self, attempt_id: str) -> None:
        await self._release("attempt", attempt_id)

    async def _renew(self, kind: str, resource_id: str, ttl: timedelta | None) -> bool:
        async with self._lock:
            now = datetime.now(UTC)
            self._purge(now)
            for key, lease in self._leases.items():
                if lease.kind == kind and lease.resource_id == resource_id:
                    self._leases[key] = AdmissionLease(
                        **{**lease.__dict__, "expires_at": now + (ttl or self.limits.lease_ttl)}
                    )
                    return True
            return False

    async def renew_run(self, run_id: str, *, ttl: timedelta | None = None) -> bool:
        return await self._renew("run", run_id, ttl)

    async def renew_attempt(self, attempt_id: str, *, ttl: timedelta | None = None) -> bool:
        return await self._renew("attempt", attempt_id, ttl)

    async def reclaim_stale(self, *, now: datetime | None = None) -> int:
        async with self._lock:
            before = len(self._leases)
            self._purge(now or datetime.now(UTC))
            return before - len(self._leases)

    async def snapshot(self) -> AdmissionSnapshot:
        async with self._lock:
            self._purge(datetime.now(UTC))
            runs = sum(lease.kind == "run" for lease in self._leases.values())
            attempts = sum(lease.kind == "attempt" for lease in self._leases.values())
            return AdmissionSnapshot(self.limits, runs, attempts, runs, attempts)


class SqliteConcurrencyAdmission(InMemoryConcurrencyAdmission):
    """Shared SQLite lease authority; the database, not process memory, counts."""

    def __init__(self, conn: Any, limits: ConcurrencyLimits | None = None) -> None:
        super().__init__(limits)
        self._conn = conn

    async def ensure_schema(self) -> None:
        await self._conn.execute(
            """CREATE TABLE IF NOT EXISTS canonical_admission_leases (
                lease_id TEXT PRIMARY KEY, kind TEXT NOT NULL, resource_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL, principal_id TEXT NOT NULL, expires_at TEXT NOT NULL,
                UNIQUE(kind, resource_id)
            )"""
        )
        await self._conn.commit()

    async def _db_acquire(
        self, kind: str, resource_id: str, *, workspace_id: str, principal_id: str | None
    ) -> AdmissionLease:
        async with self._lock:
            now = datetime.now(UTC)
            nested = bool(self._conn.in_transaction)
            if not nested:
                await self._conn.execute("BEGIN IMMEDIATE")
            try:
                await self._conn.execute(
                    "DELETE FROM canonical_admission_leases WHERE expires_at <= ?",
                    (now.isoformat(),),
                )
                principal = principal_id or "<anonymous>"
                rows = await self._conn.execute_fetchall(
                    "SELECT workspace_id, principal_id FROM canonical_admission_leases WHERE kind = ?",
                    (kind,),
                )
                limits = (
                    (
                        self.limits.max_runs_per_principal,
                        self.limits.max_runs_per_workspace,
                        self.limits.max_runs_global,
                    )
                    if kind == "run"
                    else (
                        self.limits.max_attempts_per_principal,
                        self.limits.max_attempts_per_workspace,
                        self.limits.max_attempts_global,
                    )
                )
                dimensions = (
                    ("principal", sum(row[1] == principal for row in rows), limits[0]),
                    ("workspace", sum(row[0] == workspace_id for row in rows), limits[1]),
                    ("global", len(rows), limits[2]),
                )
                for dimension, current, limit in dimensions:
                    if current >= limit:
                        raise RunAdmissionRejected(
                            f"{kind}s/{dimension}",
                            limit,
                            current,
                            self.limits.lease_ttl.total_seconds(),
                        )
                lease = AdmissionLease(
                    uuid.uuid4().hex,
                    kind,
                    resource_id,
                    workspace_id,
                    principal,
                    now + self.limits.lease_ttl,
                )
                await self._conn.execute(
                    "INSERT INTO canonical_admission_leases VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        lease.lease_id,
                        lease.kind,
                        lease.resource_id,
                        lease.workspace_id,
                        lease.principal_id,
                        lease.expires_at.isoformat(),
                    ),
                )
                if not nested:
                    await self._conn.commit()
                return lease
            except Exception:
                if not nested:
                    await self._conn.rollback()
                raise

    async def acquire_run(
        self, run_id: str, *, workspace_id: str, principal_id: str | None
    ) -> AdmissionLease:
        return await self._db_acquire(
            "run", run_id, workspace_id=workspace_id, principal_id=principal_id
        )

    async def acquire_attempt(
        self, attempt_id: str, *, workspace_id: str, principal_id: str | None
    ) -> AdmissionLease:
        return await self._db_acquire(
            "attempt", attempt_id, workspace_id=workspace_id, principal_id=principal_id
        )

    async def _db_delete(self, kind: str, resource_id: str) -> None:
        async with self._lock:
            await self._conn.execute(
                "DELETE FROM canonical_admission_leases WHERE kind = ? AND resource_id = ?",
                (kind, resource_id),
            )
            await self._conn.commit()

    async def release_run(self, run_id: str) -> None:
        await self._db_delete("run", run_id)

    async def release_attempt(self, attempt_id: str) -> None:
        await self._db_delete("attempt", attempt_id)

    async def _db_renew(self, kind: str, resource_id: str, ttl: timedelta | None) -> bool:
        async with self._lock:
            now = datetime.now(UTC)
            cursor = await self._conn.execute(
                "UPDATE canonical_admission_leases SET expires_at = ? "
                "WHERE kind = ? AND resource_id = ? AND expires_at > ?",
                (
                    (now + (ttl or self.limits.lease_ttl)).isoformat(),
                    kind,
                    resource_id,
                    now.isoformat(),
                ),
            )
            await self._conn.commit()
            return bool(cursor.rowcount == 1)

    async def renew_run(self, run_id: str, *, ttl: timedelta | None = None) -> bool:
        return await self._db_renew("run", run_id, ttl)

    async def renew_attempt(self, attempt_id: str, *, ttl: timedelta | None = None) -> bool:
        return await self._db_renew("attempt", attempt_id, ttl)

    async def reclaim_stale(self, *, now: datetime | None = None) -> int:
        async with self._lock:
            cursor = await self._conn.execute(
                "DELETE FROM canonical_admission_leases WHERE expires_at <= ?",
                ((now or datetime.now(UTC)).isoformat(),),
            )
            await self._conn.commit()
            return int(cursor.rowcount)

    async def snapshot(self) -> AdmissionSnapshot:
        async with self._lock:
            cursor = await self._conn.execute(
                "SELECT kind, count(*) FROM canonical_admission_leases "
                "WHERE expires_at > ? GROUP BY kind",
                (datetime.now(UTC).isoformat(),),
            )
            rows = await cursor.fetchall()
        runs = next((int(row[1]) for row in rows if row[0] == "run"), 0)
        attempts = next((int(row[1]) for row in rows if row[0] == "attempt"), 0)
        return AdmissionSnapshot(self.limits, runs, attempts, runs, attempts)


class PostgresConcurrencyAdmission:
    """Replica-safe lease authority backed by PostgreSQL."""

    def __init__(self, pool: Any, limits: ConcurrencyLimits | None = None) -> None:
        self._pool = pool
        self.limits = limits or ConcurrencyLimits.from_environment()

    async def _acquire(
        self, kind: str, resource_id: str, *, workspace_id: str, principal_id: str | None
    ) -> AdmissionLease:
        principal = principal_id or "<anonymous>"
        async with self._pool.acquire() as conn, conn.transaction():
            now = datetime.now(UTC)
            await conn.execute("DELETE FROM canonical_admission_leases WHERE expires_at <= $1", now)
            keys = sorted(
                (
                    f"{kind}:global",
                    f"{kind}:workspace:{workspace_id}",
                    f"{kind}:principal:{principal}",
                )
            )
            for key in keys:
                await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", key)
            counts = await conn.fetchrow(
                """SELECT count(*) AS total,
                    count(*) FILTER (WHERE workspace_id = $2) AS workspace,
                    count(*) FILTER (WHERE principal_id = $3) AS principal
                   FROM canonical_admission_leases WHERE kind = $1""",
                kind,
                workspace_id,
                principal,
            )
            limits = (
                (
                    self.limits.max_runs_per_principal,
                    self.limits.max_runs_per_workspace,
                    self.limits.max_runs_global,
                )
                if kind == "run"
                else (
                    self.limits.max_attempts_per_principal,
                    self.limits.max_attempts_per_workspace,
                    self.limits.max_attempts_global,
                )
            )
            for dimension, current, limit in (
                ("principal", counts["principal"], limits[0]),
                ("workspace", counts["workspace"], limits[1]),
                ("global", counts["total"], limits[2]),
            ):
                if current >= limit:
                    raise RunAdmissionRejected(
                        f"{kind}s/{dimension}",
                        limit,
                        int(current),
                        self.limits.lease_ttl.total_seconds(),
                    )
            lease = AdmissionLease(
                uuid.uuid4().hex,
                kind,
                resource_id,
                workspace_id,
                principal,
                now + self.limits.lease_ttl,
            )
            await conn.execute(
                """INSERT INTO canonical_admission_leases
                   (lease_id, kind, resource_id, workspace_id, principal_id, expires_at)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                lease.lease_id,
                lease.kind,
                lease.resource_id,
                lease.workspace_id,
                lease.principal_id,
                lease.expires_at,
            )
            return lease

    async def acquire_run(
        self, run_id: str, *, workspace_id: str, principal_id: str | None
    ) -> AdmissionLease:
        return await self._acquire(
            "run", run_id, workspace_id=workspace_id, principal_id=principal_id
        )

    async def acquire_attempt(
        self, attempt_id: str, *, workspace_id: str, principal_id: str | None
    ) -> AdmissionLease:
        return await self._acquire(
            "attempt", attempt_id, workspace_id=workspace_id, principal_id=principal_id
        )

    async def _execute(self, sql: str, *args: Any) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(sql, *args)

    async def release_run(self, run_id: str) -> None:
        await self._execute(
            "DELETE FROM canonical_admission_leases WHERE kind = 'run' AND resource_id = $1", run_id
        )

    async def release_attempt(self, attempt_id: str) -> None:
        await self._execute(
            "DELETE FROM canonical_admission_leases WHERE kind = 'attempt' AND resource_id = $1",
            attempt_id,
        )

    async def _renew(self, kind: str, resource_id: str, ttl: timedelta | None) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE canonical_admission_leases SET expires_at = $1 WHERE kind = $2 AND resource_id = $3 AND expires_at > $4",
                datetime.now(UTC) + (ttl or self.limits.lease_ttl),
                kind,
                resource_id,
                datetime.now(UTC),
            )
            return bool(result.endswith("1"))

    async def renew_run(self, run_id: str, *, ttl: timedelta | None = None) -> bool:
        return await self._renew("run", run_id, ttl)

    async def renew_attempt(self, attempt_id: str, *, ttl: timedelta | None = None) -> bool:
        return await self._renew("attempt", attempt_id, ttl)

    async def reclaim_stale(self, *, now: datetime | None = None) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM canonical_admission_leases WHERE expires_at <= $1",
                now or datetime.now(UTC),
            )
            return int(result.rsplit(" ", 1)[-1])

    async def snapshot(self) -> AdmissionSnapshot:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT kind, count(*) AS count FROM canonical_admission_leases WHERE expires_at > $1 GROUP BY kind",
                datetime.now(UTC),
            )
        runs = next((int(row["count"]) for row in rows if row["kind"] == "run"), 0)
        attempts = next((int(row["count"]) for row in rows if row["kind"] == "attempt"), 0)
        return AdmissionSnapshot(self.limits, runs, attempts, runs, attempts)


__all__ = [
    "AdmissionLease",
    "AdmissionSnapshot",
    "ConcurrencyAdmission",
    "ConcurrencyLimits",
    "InMemoryConcurrencyAdmission",
    "PostgresConcurrencyAdmission",
    "RunAdmissionRejected",
    "SqliteConcurrencyAdmission",
]
