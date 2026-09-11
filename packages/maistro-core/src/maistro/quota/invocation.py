"""Quota admission and accounting for the canonical Invocation boundary.

This module deliberately owns the quota *decision* for a physical effect. Router
and Agent objects may still carry legacy configuration for selection or reporting,
but they must not decide whether a provider call can start. A reservation is held
from admission through provider completion; successful usage is then committed to
the same scope, while proven failures release it and ambiguous outcomes remain
reserved until an explicit reconciliation arrives.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import uuid4

from maistro.quota.rate_profile import WINDOW_SECONDS, LimitUnit, ModelRateProfile, RateConstraint
from maistro.quota.usage_log import InMemoryUsageLog
from maistro.types.errors import QuotaReserveError

if TYPE_CHECKING:
    from maistro.capabilities.binding import Binding
    from maistro.capabilities.invocation import InvocationUsage


class QuotaOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class QuotaAmount:
    """Conservative units reserved before a provider call starts."""

    requests: int = 1
    input_tokens: int = 0
    output_tokens: int = 0
    images: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, int | float]:
        return {
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "images": self.images,
            "cost_usd": self.cost_usd,
        }


@dataclass(frozen=True)
class QuotaReservation:
    """Secret-free evidence of the admission scope and reserved amount."""

    reservation_id: str
    invocation_id: str
    scope_key: str
    workspace_id: str
    project_id: str
    principal_id: str
    provider: str
    capability: str
    amount: QuotaAmount
    created_at: float


@dataclass(frozen=True)
class QuotaSettlement:
    """The accounting result attached to a terminal Invocation."""

    scope_key: str
    outcome: QuotaOutcome
    reserved: QuotaAmount
    final: QuotaAmount | None
    reconciled: bool = False


@runtime_checkable
class QuotaAdmission(Protocol):
    """Canonical reserve/settle contract for provider effects.

    Implementations must make ``reserve`` atomic with respect to all replicas
    sharing their backing store. The in-memory implementation is intentionally
    process-local and is suitable for tests and explicitly ephemeral deployments.
    """

    async def reserve(
        self,
        *,
        invocation_id: str,
        binding: Binding,
        provider: str,
        principal_id: str,
        capability: str,
        amount: QuotaAmount,
    ) -> QuotaReservation: ...

    async def settle(
        self,
        invocation_id: str,
        outcome: QuotaOutcome,
        usage: InvocationUsage | None = None,
    ) -> QuotaSettlement: ...

    async def reconcile(
        self,
        invocation_id: str,
        usage: InvocationUsage | None = None,
    ) -> QuotaSettlement: ...


class InMemoryInvocationQuota:
    """Atomic process-local quota gate backed by the shared usage log."""

    def __init__(
        self,
        *,
        usage_log: InMemoryUsageLog | None = None,
        profile_for: Callable[[str], ModelRateProfile] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.usage_log = usage_log or InMemoryUsageLog()
        self._profile_for = profile_for or _permissive_profile
        self._clock = clock
        self._reservations: dict[str, QuotaReservation] = {}
        self._uncertain: set[str] = set()
        self._lock = asyncio.Lock()

    async def reserve(
        self,
        *,
        invocation_id: str,
        binding: Binding,
        provider: str,
        principal_id: str,
        capability: str,
        amount: QuotaAmount,
    ) -> QuotaReservation:
        if (
            amount.requests <= 0
            or min(amount.input_tokens, amount.output_tokens, amount.images) < 0
        ):
            raise ValueError("quota reservation amounts must be non-negative")
        profile = self._profile_for(provider)
        scope_key = profile.scope_key(
            provider=provider,
            model=provider,
            workspace=binding.workspace_id,
            workspace_id=binding.workspace_id,
            project=binding.project_id,
            project_id=binding.project_id,
            principal=principal_id,
            principal_id=principal_id,
            capability=capability,
        )
        now = self._clock()
        reservation = QuotaReservation(
            reservation_id=uuid4().hex,
            invocation_id=invocation_id,
            scope_key=scope_key,
            workspace_id=binding.workspace_id,
            project_id=binding.project_id,
            principal_id=principal_id,
            provider=provider,
            capability=capability,
            amount=amount,
            created_at=now,
        )
        async with self._lock:
            for constraint in profile.constraints:
                used = self._used(constraint, scope_key, now)
                pending = self._pending(constraint, scope_key, now)
                requested = _amount_for(amount, constraint.unit)
                if used + pending + requested > constraint.limit:
                    raise QuotaReserveError(
                        f"quota reserve exhausted for provider {provider!r} "
                        f"({constraint.unit.value}/{constraint.window.value}: "
                        f"{used + pending:.0f}/{constraint.limit})"
                    )
            self._reservations[invocation_id] = reservation
        return reservation

    async def settle(
        self,
        invocation_id: str,
        outcome: QuotaOutcome,
        usage: InvocationUsage | None = None,
    ) -> QuotaSettlement:
        async with self._lock:
            reservation = self._reservations.get(invocation_id)
            if reservation is None:
                raise KeyError(f"no quota reservation for Invocation {invocation_id!r}")
            if outcome is QuotaOutcome.UNKNOWN:
                self._uncertain.add(invocation_id)
                return QuotaSettlement(
                    scope_key=reservation.scope_key,
                    outcome=outcome,
                    reserved=reservation.amount,
                    final=None,
                )
            self._reservations.pop(invocation_id)
            self._uncertain.discard(invocation_id)
            final = _usage_amount(usage) if outcome is QuotaOutcome.COMPLETED else None
            if final is not None:
                self.usage_log.record(
                    reservation.scope_key,
                    input_tokens=final.input_tokens,
                    output_tokens=final.output_tokens,
                    images=final.images,
                    cost_usd=final.cost_usd,
                    now=self._clock(),
                )
            return QuotaSettlement(
                scope_key=reservation.scope_key,
                outcome=outcome,
                reserved=reservation.amount,
                final=final,
            )

    async def reconcile(
        self,
        invocation_id: str,
        usage: InvocationUsage | None = None,
    ) -> QuotaSettlement:
        """Resolve an UNKNOWN provider outcome with evidence or rollback.

        ``usage=None`` means an operator/provider verifier proved that no usage
        occurred. It is not treated as zero-cost successful usage.
        """
        return await self.settle(
            invocation_id,
            QuotaOutcome.COMPLETED if usage is not None else QuotaOutcome.FAILED,
            usage,
        )

    def pending_invocations(self) -> tuple[str, ...]:
        """Read-only recovery visibility for uncertain/provider-delayed calls."""
        return tuple(self._uncertain)

    def _used(self, constraint: object, scope_key: str, now: float) -> float:
        # Kept in one place so reservation and committed usage use identical windows.
        assert hasattr(constraint, "unit") and hasattr(constraint, "window")
        unit = constraint.unit
        seconds = WINDOW_SECONDS[constraint.window]
        if unit is LimitUnit.REQUESTS:
            return self.usage_log.count_since(scope_key, seconds, now=now)
        return self.usage_log.tokens_since(scope_key, seconds, unit, now=now)

    def _pending(self, constraint: object, scope_key: str, now: float) -> float:
        assert hasattr(constraint, "unit") and hasattr(constraint, "window")
        cutoff = now - WINDOW_SECONDS[constraint.window]
        return sum(
            _amount_for(reservation.amount, constraint.unit)
            for reservation in self._reservations.values()
            if reservation.scope_key == scope_key and reservation.created_at > cutoff
        )


class SqliteInvocationQuota:
    """Durable, transactionally serialized quota admission for one SQLite DB.

    Reservations and committed usage live in the database rather than beside
    the process-local usage cache. ``BEGIN IMMEDIATE`` makes the check plus
    reservation one critical section, so two worker processes sharing the DB
    cannot both consume the last slot.
    """

    def __init__(
        self,
        conn: object,
        *,
        profile_for: Callable[[str], ModelRateProfile] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._conn = conn
        self._profile_for = profile_for or _permissive_profile
        self._clock = clock
        self._lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        await self._conn.executescript(  # type: ignore[attr-defined]
            """
            CREATE TABLE IF NOT EXISTS invocation_quota_reservations (
                invocation_id TEXT PRIMARY KEY,
                reservation_id TEXT NOT NULL UNIQUE,
                scope_key TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                capability TEXT NOT NULL,
                requests INTEGER NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                images INTEGER NOT NULL,
                cost_usd REAL NOT NULL,
                created_at REAL NOT NULL,
                state TEXT NOT NULL DEFAULT 'reserved'
            );
            CREATE INDEX IF NOT EXISTS idx_invocation_quota_pending
                ON invocation_quota_reservations (scope_key, created_at, state);
            CREATE TABLE IF NOT EXISTS invocation_quota_usage (
                usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                invocation_id TEXT NOT NULL UNIQUE,
                scope_key TEXT NOT NULL,
                timestamp REAL NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                images INTEGER NOT NULL,
                cost_usd REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_invocation_quota_usage_scope_ts
                ON invocation_quota_usage (scope_key, timestamp);
            """
        )
        await self._conn.commit()  # type: ignore[attr-defined]

    async def reserve(
        self,
        *,
        invocation_id: str,
        binding: Binding,
        provider: str,
        principal_id: str,
        capability: str,
        amount: QuotaAmount,
    ) -> QuotaReservation:
        self._validate_amount(amount)
        profile = self._profile_for(provider)
        scope_key = _scope_key(profile, provider, binding, principal_id, capability)
        now = self._clock()
        reservation = QuotaReservation(
            reservation_id=uuid4().hex,
            invocation_id=invocation_id,
            scope_key=scope_key,
            workspace_id=binding.workspace_id,
            project_id=binding.project_id,
            principal_id=principal_id,
            provider=provider,
            capability=capability,
            amount=amount,
            created_at=now,
        )
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")  # type: ignore[attr-defined]
            try:
                for constraint in profile.constraints:
                    used = await self._used(constraint, scope_key, now)
                    pending = await self._pending(constraint, scope_key, now)
                    requested = _amount_for(amount, constraint.unit)
                    if used + pending + requested > constraint.limit:
                        raise QuotaReserveError(
                            f"quota reserve exhausted for provider {provider!r} "
                            f"({constraint.unit.value}/{constraint.window.value}: "
                            f"{used + pending:.0f}/{constraint.limit})"
                        )
                await self._conn.execute(  # type: ignore[attr-defined]
                    """INSERT INTO invocation_quota_reservations
                       (invocation_id, reservation_id, scope_key, workspace_id,
                        project_id, principal_id, provider, capability, requests,
                        input_tokens, output_tokens, images, cost_usd, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        reservation.invocation_id,
                        reservation.reservation_id,
                        reservation.scope_key,
                        reservation.workspace_id,
                        reservation.project_id,
                        reservation.principal_id,
                        reservation.provider,
                        reservation.capability,
                        amount.requests,
                        amount.input_tokens,
                        amount.output_tokens,
                        amount.images,
                        amount.cost_usd,
                        now,
                    ),
                )
                await self._conn.commit()  # type: ignore[attr-defined]
            except Exception:
                await self._conn.rollback()  # type: ignore[attr-defined]
                raise
        return reservation

    async def settle(
        self,
        invocation_id: str,
        outcome: QuotaOutcome,
        usage: InvocationUsage | None = None,
    ) -> QuotaSettlement:
        async with self._lock:
            await self._conn.execute("BEGIN IMMEDIATE")  # type: ignore[attr-defined]
            try:
                row = await self._reservation_row(invocation_id)
                if row is None:
                    raise KeyError(f"no quota reservation for Invocation {invocation_id!r}")
                reservation = _reservation_from_row(row)
                if outcome is QuotaOutcome.UNKNOWN:
                    await self._conn.execute(  # type: ignore[attr-defined]
                        "UPDATE invocation_quota_reservations SET state='unknown' "
                        "WHERE invocation_id = ?",
                        (invocation_id,),
                    )
                    await self._conn.commit()  # type: ignore[attr-defined]
                    return QuotaSettlement(
                        scope_key=reservation.scope_key,
                        outcome=outcome,
                        reserved=reservation.amount,
                        final=None,
                    )
                final = _usage_amount(usage) if outcome is QuotaOutcome.COMPLETED else None
                await self._conn.execute(  # type: ignore[attr-defined]
                    "DELETE FROM invocation_quota_reservations WHERE invocation_id = ?",
                    (invocation_id,),
                )
                if final is not None:
                    await self._conn.execute(  # type: ignore[attr-defined]
                        """INSERT INTO invocation_quota_usage
                           (invocation_id, scope_key, timestamp, input_tokens,
                            output_tokens, images, cost_usd)
                           VALUES (?,?,?,?,?,?,?)""",
                        (
                            invocation_id,
                            reservation.scope_key,
                            self._clock(),
                            final.input_tokens,
                            final.output_tokens,
                            final.images,
                            final.cost_usd,
                        ),
                    )
                await self._conn.commit()  # type: ignore[attr-defined]
                return QuotaSettlement(
                    scope_key=reservation.scope_key,
                    outcome=outcome,
                    reserved=reservation.amount,
                    final=final,
                )
            except Exception:
                await self._conn.rollback()  # type: ignore[attr-defined]
                raise

    async def reconcile(
        self,
        invocation_id: str,
        usage: InvocationUsage | None = None,
    ) -> QuotaSettlement:
        return await self.settle(
            invocation_id,
            QuotaOutcome.COMPLETED if usage is not None else QuotaOutcome.FAILED,
            usage,
        )

    async def _reservation_row(self, invocation_id: str) -> tuple[Any, ...] | None:
        cursor = await self._conn.execute(  # type: ignore[attr-defined]
            """SELECT invocation_id, reservation_id, scope_key, workspace_id,
               project_id, principal_id, provider, capability, requests,
               input_tokens, output_tokens, images, cost_usd, created_at
               FROM invocation_quota_reservations WHERE invocation_id = ?""",
            (invocation_id,),
        )
        row = await cursor.fetchone()
        return tuple(row) if row is not None else None

    async def _used(self, constraint: RateConstraint, scope_key: str, now: float) -> float:
        column = _usage_column(constraint.unit)
        if constraint.unit is LimitUnit.REQUESTS:
            expression = "COUNT(*)"
        else:
            expression = f"COALESCE(SUM({column}), 0)"
        cursor = await self._conn.execute(  # type: ignore[attr-defined]
            f"SELECT {expression} FROM invocation_quota_usage "
            "WHERE scope_key = ? AND timestamp > ?",
            (scope_key, now - WINDOW_SECONDS[constraint.window]),
        )
        row = await cursor.fetchone()
        return float(row[0] or 0) if row is not None else 0.0

    async def _pending(self, constraint: RateConstraint, scope_key: str, now: float) -> float:
        column = _reservation_column(constraint.unit)
        expression = (
            "COUNT(*)" if constraint.unit is LimitUnit.REQUESTS else f"COALESCE(SUM({column}), 0)"
        )
        cursor = await self._conn.execute(  # type: ignore[attr-defined]
            f"SELECT {expression} FROM invocation_quota_reservations "
            "WHERE scope_key = ? AND created_at > ?",
            (scope_key, now - WINDOW_SECONDS[constraint.window]),
        )
        row = await cursor.fetchone()
        return float(row[0] or 0) if row is not None else 0.0

    @staticmethod
    def _validate_amount(amount: QuotaAmount) -> None:
        if (
            amount.requests <= 0
            or min(amount.input_tokens, amount.output_tokens, amount.images) < 0
        ):
            raise ValueError("quota reservation amounts must be non-negative")


class PgInvocationQuota:
    """PostgreSQL counterpart using a row lock per quota scope."""

    def __init__(
        self,
        pool: object,
        *,
        profile_for: Callable[[str], ModelRateProfile] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._pool = pool
        self._profile_for = profile_for or _permissive_profile
        self._clock = clock

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as conn:  # type: ignore[attr-defined]
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS invocation_quota_scopes (
                    scope_key TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS invocation_quota_reservations (
                    invocation_id TEXT PRIMARY KEY,
                    reservation_id TEXT NOT NULL UNIQUE,
                    scope_key TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    requests INTEGER NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    images INTEGER NOT NULL,
                    cost_usd DOUBLE PRECISION NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL,
                    state TEXT NOT NULL DEFAULT 'reserved'
                );
                CREATE INDEX IF NOT EXISTS idx_invocation_quota_pending
                    ON invocation_quota_reservations (scope_key, created_at, state);
                CREATE TABLE IF NOT EXISTS invocation_quota_usage (
                    usage_id BIGSERIAL PRIMARY KEY,
                    invocation_id TEXT NOT NULL UNIQUE,
                    scope_key TEXT NOT NULL,
                    timestamp DOUBLE PRECISION NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    images INTEGER NOT NULL,
                    cost_usd DOUBLE PRECISION NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_invocation_quota_usage_scope_ts
                    ON invocation_quota_usage (scope_key, timestamp);
                """
            )

    async def reserve(
        self,
        *,
        invocation_id: str,
        binding: Binding,
        provider: str,
        principal_id: str,
        capability: str,
        amount: QuotaAmount,
    ) -> QuotaReservation:
        if (
            amount.requests <= 0
            or min(amount.input_tokens, amount.output_tokens, amount.images) < 0
        ):
            raise ValueError("quota reservation amounts must be non-negative")
        profile = self._profile_for(provider)
        scope_key = _scope_key(profile, provider, binding, principal_id, capability)
        now = self._clock()
        reservation = QuotaReservation(
            reservation_id=uuid4().hex,
            invocation_id=invocation_id,
            scope_key=scope_key,
            workspace_id=binding.workspace_id,
            project_id=binding.project_id,
            principal_id=principal_id,
            provider=provider,
            capability=capability,
            amount=amount,
            created_at=now,
        )
        async with self._pool.acquire() as conn, conn.transaction():  # type: ignore[attr-defined]
            await conn.execute(
                "INSERT INTO invocation_quota_scopes(scope_key) VALUES($1) ON CONFLICT DO NOTHING",
                scope_key,
            )
            await conn.fetchrow(
                "SELECT scope_key FROM invocation_quota_scopes WHERE scope_key=$1 FOR UPDATE",
                scope_key,
            )
            for constraint in profile.constraints:
                used = await _pg_used(conn, constraint, scope_key, now)
                pending = await _pg_pending(conn, constraint, scope_key, now)
                requested = _amount_for(amount, constraint.unit)
                if used + pending + requested > constraint.limit:
                    raise QuotaReserveError(
                        f"quota reserve exhausted for provider {provider!r} "
                        f"({constraint.unit.value}/{constraint.window.value}: {used + pending:.0f}/{constraint.limit})"
                    )
            await conn.execute(
                """INSERT INTO invocation_quota_reservations
                   (invocation_id, reservation_id, scope_key, workspace_id, project_id,
                    principal_id, provider, capability, requests, input_tokens,
                    output_tokens, images, cost_usd, created_at)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)""",
                reservation.invocation_id,
                reservation.reservation_id,
                reservation.scope_key,
                reservation.workspace_id,
                reservation.project_id,
                reservation.principal_id,
                reservation.provider,
                reservation.capability,
                amount.requests,
                amount.input_tokens,
                amount.output_tokens,
                amount.images,
                amount.cost_usd,
                now,
            )
        return reservation

    async def settle(
        self, invocation_id: str, outcome: QuotaOutcome, usage: InvocationUsage | None = None
    ) -> QuotaSettlement:
        async with self._pool.acquire() as conn, conn.transaction():  # type: ignore[attr-defined]
            row = await conn.fetchrow(
                "SELECT * FROM invocation_quota_reservations WHERE invocation_id=$1 FOR UPDATE",
                invocation_id,
            )
            if row is None:
                raise KeyError(f"no quota reservation for Invocation {invocation_id!r}")
            reservation = _reservation_from_row(tuple(row.values()))
            if outcome is QuotaOutcome.UNKNOWN:
                await conn.execute(
                    "UPDATE invocation_quota_reservations SET state='unknown' WHERE invocation_id=$1",
                    invocation_id,
                )
                return QuotaSettlement(reservation.scope_key, outcome, reservation.amount, None)
            final = _usage_amount(usage) if outcome is QuotaOutcome.COMPLETED else None
            await conn.execute(
                "DELETE FROM invocation_quota_reservations WHERE invocation_id=$1", invocation_id
            )
            if final is not None:
                await conn.execute(
                    """INSERT INTO invocation_quota_usage
                       (invocation_id, scope_key, timestamp, input_tokens, output_tokens, images, cost_usd)
                       VALUES($1,$2,$3,$4,$5,$6,$7)""",
                    invocation_id,
                    reservation.scope_key,
                    self._clock(),
                    final.input_tokens,
                    final.output_tokens,
                    final.images,
                    final.cost_usd,
                )
            return QuotaSettlement(reservation.scope_key, outcome, reservation.amount, final)

    async def reconcile(
        self, invocation_id: str, usage: InvocationUsage | None = None
    ) -> QuotaSettlement:
        return await self.settle(
            invocation_id,
            QuotaOutcome.COMPLETED if usage is not None else QuotaOutcome.FAILED,
            usage,
        )


def _scope_key(
    profile: ModelRateProfile,
    provider: str,
    binding: Binding,
    principal_id: str,
    capability: str,
) -> str:
    return profile.scope_key(
        provider=provider,
        model=provider,
        workspace=binding.workspace_id,
        workspace_id=binding.workspace_id,
        project=binding.project_id,
        project_id=binding.project_id,
        principal=principal_id,
        principal_id=principal_id,
        capability=capability,
    )


def _usage_column(unit: LimitUnit) -> str:
    return {
        LimitUnit.INPUT_TOKENS: "input_tokens",
        LimitUnit.OUTPUT_TOKENS: "output_tokens",
        LimitUnit.TOTAL_TOKENS: "input_tokens + output_tokens",
        LimitUnit.IMAGES: "images",
        LimitUnit.CREDITS_USD: "cost_usd",
    }.get(unit, "input_tokens")


def _reservation_column(unit: LimitUnit) -> str:
    return {
        LimitUnit.INPUT_TOKENS: "input_tokens",
        LimitUnit.OUTPUT_TOKENS: "output_tokens",
        LimitUnit.TOTAL_TOKENS: "input_tokens + output_tokens",
        LimitUnit.IMAGES: "images",
        LimitUnit.CREDITS_USD: "cost_usd",
    }.get(unit, "input_tokens")


def _reservation_from_row(row: tuple[Any, ...]) -> QuotaReservation:
    return QuotaReservation(
        reservation_id=str(row[1]),
        invocation_id=str(row[0]),
        scope_key=str(row[2]),
        workspace_id=str(row[3]),
        project_id=str(row[4]),
        principal_id=str(row[5]),
        provider=str(row[6]),
        capability=str(row[7]),
        amount=QuotaAmount(
            requests=int(row[8]),
            input_tokens=int(row[9]),
            output_tokens=int(row[10]),
            images=int(row[11]),
            cost_usd=float(row[12]),
        ),
        created_at=float(row[13]),
    )


async def _pg_used(conn: Any, constraint: RateConstraint, scope_key: str, now: float) -> float:
    expression = (
        "COUNT(*)"
        if constraint.unit is LimitUnit.REQUESTS
        else f"COALESCE(SUM({_usage_column(constraint.unit)}), 0)"
    )
    row = await conn.fetchrow(
        f"SELECT {expression} FROM invocation_quota_usage WHERE scope_key=$1 AND timestamp>$2",
        scope_key,
        now - WINDOW_SECONDS[constraint.window],
    )
    return float(row[0] or 0) if row else 0.0


async def _pg_pending(conn: Any, constraint: RateConstraint, scope_key: str, now: float) -> float:
    expression = (
        "COUNT(*)"
        if constraint.unit is LimitUnit.REQUESTS
        else f"COALESCE(SUM({_reservation_column(constraint.unit)}), 0)"
    )
    row = await conn.fetchrow(
        f"SELECT {expression} FROM invocation_quota_reservations WHERE scope_key=$1 AND created_at>$2",
        scope_key,
        now - WINDOW_SECONDS[constraint.window],
    )
    return float(row[0] or 0) if row else 0.0


def _permissive_profile(provider: str) -> ModelRateProfile:
    return ModelRateProfile(provider=provider, model=provider)


def _amount_for(amount: QuotaAmount, unit: LimitUnit) -> float:
    return {
        LimitUnit.REQUESTS: float(amount.requests),
        LimitUnit.INPUT_TOKENS: float(amount.input_tokens),
        LimitUnit.OUTPUT_TOKENS: float(amount.output_tokens),
        LimitUnit.TOTAL_TOKENS: float(amount.total_tokens),
        LimitUnit.IMAGES: float(amount.images),
        LimitUnit.CREDITS_USD: amount.cost_usd,
    }[unit]


def _usage_amount(usage: InvocationUsage | None) -> QuotaAmount:
    if usage is None:
        return QuotaAmount()
    return QuotaAmount(
        input_tokens=usage.input_units,
        output_tokens=usage.output_units,
        cost_usd=(usage.cost_cents or 0.0) / 100.0,
    )


__all__ = [
    "InMemoryInvocationQuota",
    "PgInvocationQuota",
    "QuotaAdmission",
    "QuotaAmount",
    "QuotaOutcome",
    "QuotaReservation",
    "QuotaSettlement",
    "SqliteInvocationQuota",
]
