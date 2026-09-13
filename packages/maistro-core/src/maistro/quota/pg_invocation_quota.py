"""PostgreSQL quota admission and settlement for canonical Invocations."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from maistro.capabilities.binding import Binding
from maistro.capabilities.invocation import Invocation, InvocationStatus
from maistro.quota.invocation_quota import (
    EstimateResolver,
    InvocationQuotaDenied,
    QuotaBudget,
    QuotaEvidenceConflict,
)

_LOCK_KEY = 0x6D616973_71756F74  # "maisquot"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS invocation_quota_budgets (
    budget_id TEXT PRIMARY KEY, definition JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS invocation_quota_reservations (
    invocation_id TEXT PRIMARY KEY, identity JSONB NOT NULL,
    state TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT -1
);
CREATE TABLE IF NOT EXISTS invocation_quota_allocations (
    invocation_id TEXT NOT NULL REFERENCES invocation_quota_reservations(invocation_id),
    budget_id TEXT NOT NULL REFERENCES invocation_quota_budgets(budget_id),
    maximum BIGINT NOT NULL, held BIGINT NOT NULL, spent BIGINT NOT NULL DEFAULT 0,
    measured BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (invocation_id, budget_id)
);
CREATE INDEX IF NOT EXISTS idx_invocation_quota_alloc_budget
    ON invocation_quota_allocations (budget_id);
"""


class PgInvocationQuota:
    """Database-serialized quota collaborator at the Invocation boundary."""

    def __init__(
        self,
        pool: Any,
        *,
        estimate: EstimateResolver,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._pool = pool
        self._estimate = estimate
        self._clock = clock

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(_SCHEMA)

    async def register_budget(self, budget: QuotaBudget) -> None:
        definition = json.dumps(budget.__dict__, sort_keys=True)
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """INSERT INTO invocation_quota_budgets (budget_id, definition)
                   VALUES ($1, $2::jsonb)
                   ON CONFLICT (budget_id) DO NOTHING""",
                budget.budget_id,
                definition,
            )
            row = await conn.fetchrow(
                "SELECT definition::text FROM invocation_quota_budgets WHERE budget_id=$1",
                budget.budget_id,
            )
            if row is None or json.loads(row[0]) != json.loads(definition):
                raise QuotaEvidenceConflict("budget identity is immutable")

    async def reserve(self, invocation: Invocation, binding: Binding) -> None:
        estimate = await self._estimate(invocation, binding)
        identity = {
            "workspace_id": binding.workspace_id,
            "principal_id": estimate.principal_id,
            "provider_name": invocation.binding.provider_name,
            "capability": binding.capability,
            "run_id": invocation.run_id,
            "node_run_id": invocation.node_run_id,
            "attempt_id": invocation.attempt_id,
            "binding_id": binding.binding_id,
            "effect_key": invocation.effect_key,
            "tokens": estimate.tokens,
            "micro_usd": estimate.micro_usd,
        }
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _LOCK_KEY)
            existing = await conn.fetchrow(
                "SELECT identity, state, reason FROM invocation_quota_reservations WHERE invocation_id=$1",
                invocation.invocation_id,
            )
            if existing is not None:
                if _json_value(existing["identity"]) != identity:
                    raise QuotaEvidenceConflict("Invocation quota identity was reused")
                if existing["state"] == "denied":
                    raise InvocationQuotaDenied(existing["reason"])
                return

            now = self._clock()
            rows = await conn.fetch("SELECT budget_id, definition FROM invocation_quota_budgets")
            budgets = [QuotaBudget(**_json_value(row["definition"])) for row in rows]
            applicable = [
                budget
                for budget in budgets
                if budget.period_start <= now < budget.period_end
                and (
                    budget.provider_name is None
                    or budget.provider_name == invocation.binding.provider_name
                )
                and (budget.workspace_id is None or budget.workspace_id == binding.workspace_id)
                and (budget.principal_id is None or budget.principal_id == estimate.principal_id)
                and (budget.capability is None or budget.capability == binding.capability)
            ]
            reason = "missing applicable quota policy" if not applicable else ""
            allocations: list[tuple[str, int, int]] = []
            for budget in applicable:
                maximum = estimate.maximum(budget.unit)
                if maximum is None:
                    reason = f"missing upper bound for budget {budget.budget_id}"
                    break
                row = await conn.fetchrow(
                    """SELECT COALESCE(SUM(spent), 0) AS spent, COALESCE(SUM(held), 0) AS held
                       FROM invocation_quota_allocations WHERE budget_id=$1""",
                    budget.budget_id,
                )
                available = budget.limit - budget.reserve - int(row["spent"]) - int(row["held"])
                if maximum > available:
                    reason = f"quota exhausted for budget {budget.budget_id}"
                    break
                allocations.append((budget.budget_id, maximum, maximum))

            await conn.execute(
                """INSERT INTO invocation_quota_reservations
                   (invocation_id, identity, state, reason) VALUES ($1,$2::jsonb,$3,$4)""",
                invocation.invocation_id,
                json.dumps(identity, sort_keys=True),
                "denied" if reason else "held",
                reason,
            )
            if not reason:
                for budget_id, maximum, held in allocations:
                    await conn.execute(
                        """INSERT INTO invocation_quota_allocations
                           (invocation_id, budget_id, maximum, held) VALUES ($1,$2,$3,$4)""",
                        invocation.invocation_id,
                        budget_id,
                        maximum,
                        held,
                    )
        if reason:
            raise InvocationQuotaDenied(reason)

    async def observe(self, invocation: Invocation) -> None:
        if invocation.status in {InvocationStatus.CREATED, InvocationStatus.RUNNING}:
            return
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _LOCK_KEY)
            row = await conn.fetchrow(
                "SELECT state FROM invocation_quota_reservations WHERE invocation_id=$1 FOR UPDATE",
                invocation.invocation_id,
            )
            if row is None or row["state"] in {"settled", "released", "unknown"}:
                return
            if invocation.status is InvocationStatus.UNKNOWN:
                await conn.execute(
                    "UPDATE invocation_quota_reservations SET state='unknown' WHERE invocation_id=$1",
                    invocation.invocation_id,
                )
                return
            usage = invocation.usage if invocation.status is InvocationStatus.COMPLETED else None
            if usage is None:
                await conn.execute(
                    "UPDATE invocation_quota_reservations SET state='unknown' WHERE invocation_id=$1",
                    invocation.invocation_id,
                )
                return
            tokens = usage.input_units + usage.output_units
            amount_by_unit = {
                "requests": 1,
                "tokens": tokens,
                "micro_usd": round((usage.cost_cents or 0) * 10_000),
            }
            allocations = await conn.fetch(
                "SELECT budget_id, maximum FROM invocation_quota_allocations WHERE invocation_id=$1",
                invocation.invocation_id,
            )
            for allocation in allocations:
                budget = await conn.fetchrow(
                    "SELECT definition FROM invocation_quota_budgets WHERE budget_id=$1",
                    allocation["budget_id"],
                )
                unit = _json_value(budget["definition"])["unit"]
                actual = amount_by_unit.get(unit, tokens)
                await conn.execute(
                    "UPDATE invocation_quota_allocations SET held=0, spent=$1, measured=TRUE WHERE invocation_id=$2 AND budget_id=$3",
                    min(actual, int(allocation["maximum"])),
                    invocation.invocation_id,
                    allocation["budget_id"],
                )
            await conn.execute(
                "UPDATE invocation_quota_reservations SET state='settled', revision=0 WHERE invocation_id=$1",
                invocation.invocation_id,
            )


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


__all__ = ["PgInvocationQuota"]
