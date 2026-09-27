"""PostgreSQL quota admission and settlement for canonical Invocations."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from decimal import ROUND_CEILING, Decimal
from typing import Any

from maistro.capabilities.binding import Binding
from maistro.capabilities.invocation import Invocation, InvocationStatus
from maistro.quota.invocation_quota import (
    EstimateResolver,
    InvocationQuotaDenied,
    Outcome,
    QuotaBudget,
    QuotaEvidenceConflict,
    QuotaObservation,
    require_amount,
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
CREATE TABLE IF NOT EXISTS invocation_quota_evidence (
    invocation_id TEXT NOT NULL REFERENCES invocation_quota_reservations(invocation_id),
    revision INTEGER NOT NULL CHECK (revision >= 0),
    evidence_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (invocation_id, revision),
    UNIQUE (invocation_id, evidence_id)
);
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

    async def reserve(  # noqa: C901 - admission checks share one transaction
        self, invocation: Invocation, binding: Binding
    ) -> None:
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
            if not math.isfinite(now):
                raise ValueError("invalid admission clock")
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
        """Record the absolute terminal fact, including partial usage facts."""
        if invocation.status in {InvocationStatus.CREATED, InvocationStatus.RUNNING}:
            return
        outcome: Outcome = (
            "not_applied"
            if invocation.status is InvocationStatus.FAILED
            else "completed"
            if invocation.status is InvocationStatus.COMPLETED
            else "unknown"
        )
        tokens: int | None = None
        micro_usd: int | None = None
        usage = invocation.usage
        if outcome == "completed" and usage is not None:
            if usage.units == "tokens":
                require_amount(usage.input_units, "input_units")
                require_amount(usage.output_units, "output_units")
                tokens = usage.input_units + usage.output_units
                require_amount(tokens, "tokens")
            if usage.cost_cents is not None:
                cents = Decimal(str(usage.cost_cents))
                if not cents.is_finite() or cents < 0:
                    raise ValueError("cost must be finite and nonnegative")
                micro_usd = int((cents * 10_000).to_integral_value(rounding=ROUND_CEILING))
                require_amount(micro_usd, "micro_usd")
        await self._apply(
            QuotaObservation(
                invocation_id=invocation.invocation_id,
                provider_name=invocation.binding.provider_name,
                evidence_id="canonical-terminal",
                revision=0,
                outcome=outcome,
                tokens=tokens,
                micro_usd=micro_usd,
            ),
            missing_ok=invocation.status is InvocationStatus.FAILED,
        )

    async def reconcile(self, observation: QuotaObservation) -> None:
        """Apply trusted absolute provider evidence without replaying an effect."""
        if observation.revision == 0:
            raise ValueError("revision zero is reserved for canonical terminal evidence")
        await self._apply(observation, missing_ok=False)

    async def _apply(  # noqa: C901 - evidence settlement is one atomic fold
        self, observation: QuotaObservation, *, missing_ok: bool
    ) -> None:
        payload = json.dumps(observation.payload(), sort_keys=True)
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _LOCK_KEY)
            reservation = await conn.fetchrow(
                "SELECT * FROM invocation_quota_reservations WHERE invocation_id=$1 FOR UPDATE",
                observation.invocation_id,
            )
            if reservation is None:
                if missing_ok:
                    return
                raise KeyError(
                    f"unreserved Invocation {observation.invocation_id}: reconcile coverage"
                )
            identity = _json_value(reservation["identity"])
            if identity["provider_name"] != observation.provider_name:
                raise QuotaEvidenceConflict("provider evidence does not match Invocation")
            if reservation["state"] == "denied":
                if observation.outcome != "not_applied":
                    raise QuotaEvidenceConflict("denied Invocation has no provider dispatch")
                return

            prior = await conn.fetch(
                "SELECT payload::text AS payload FROM invocation_quota_evidence "
                "WHERE invocation_id=$1 AND (revision=$2 OR evidence_id=$3)",
                observation.invocation_id,
                observation.revision,
                observation.evidence_id,
            )
            if prior:
                if any(json.loads(row["payload"]) != json.loads(payload) for row in prior):
                    raise QuotaEvidenceConflict("evidence identity/revision was reused")
                return
            await conn.execute(
                "INSERT INTO invocation_quota_evidence "
                "(invocation_id, revision, evidence_id, payload) VALUES ($1,$2,$3,$4::jsonb)",
                observation.invocation_id,
                observation.revision,
                observation.evidence_id,
                payload,
            )
            if observation.revision < int(reservation["revision"]):
                return
            if observation.outcome == "unknown" and reservation["state"] in {
                "settled",
                "released",
                "pending_usage",
            }:
                raise QuotaEvidenceConflict("unknown cannot replace a confirmed provider outcome")

            allocations = await conn.fetch(
                "SELECT a.budget_id, a.maximum, a.measured, b.definition "
                "FROM invocation_quota_allocations a "
                "JOIN invocation_quota_budgets b USING (budget_id) "
                "WHERE a.invocation_id=$1",
                observation.invocation_id,
            )
            pending = False
            for allocation in allocations:
                unit = _json_value(allocation["definition"])["unit"]
                actual = observation.actual(unit)
                if actual is None:
                    pending = pending or not bool(allocation["measured"])
                    continue
                require_amount(actual, f"{unit} usage")
                await conn.execute(
                    "UPDATE invocation_quota_allocations "
                    "SET held=0, spent=$1, measured=TRUE "
                    "WHERE invocation_id=$2 AND budget_id=$3",
                    actual,
                    observation.invocation_id,
                    allocation["budget_id"],
                )
            state = (
                "released"
                if observation.outcome == "not_applied"
                else "unknown"
                if observation.outcome == "unknown"
                else "pending_usage"
                if pending
                else "settled"
            )
            await conn.execute(
                "UPDATE invocation_quota_reservations SET state=$1, revision=$2 "
                "WHERE invocation_id=$3",
                state,
                observation.revision,
                observation.invocation_id,
            )


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


__all__ = ["PgInvocationQuota"]
