"""Atomic SQLite quota reservation/accounting at the canonical Invocation seam.

This is an accounting collaborator, not an executor, router, or Run authority.
Each transaction uses a separate connection and BEGIN IMMEDIATE. No process-local
mutex is relied on for admission. All replicas must use the SAME database file;
this is not a distributed SQLite solution for separate pod-local files.

No elapsed-time reclamation: an unresolved provider outcome continues to hold
its reservation in its original budget period. Recovery observes a persisted
Invocation or supplies versioned, trusted evidence; it never guesses success
from a timeout. Database failure refuses dispatch rather than downgrading to an
in-memory ledger. No request, result, error string, or credential is copied here.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import TypeVar

from maistro.capabilities.binding import Binding
from maistro.capabilities.invocation import Invocation, InvocationStatus
from maistro.quota.invocation_quota import (
    EstimateResolver,
    InvocationQuotaDenied,
    Outcome,
    QuotaBalance,
    QuotaBudget,
    QuotaEstimate,
    QuotaEvidenceConflict,
    QuotaObservation,
    require_amount,
)

T = TypeVar("T")

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS invocation_quota_budgets (
        budget_id TEXT PRIMARY KEY,
        definition TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS invocation_quota_reservations (
        invocation_id TEXT PRIMARY KEY,
        identity_json TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN
            ('held', 'unknown', 'pending_usage', 'settled', 'released', 'denied')),
        reason TEXT NOT NULL DEFAULT '',
        revision INTEGER NOT NULL DEFAULT -1
    )""",
    """CREATE TABLE IF NOT EXISTS invocation_quota_allocations (
        invocation_id TEXT NOT NULL REFERENCES invocation_quota_reservations(invocation_id),
        budget_id TEXT NOT NULL REFERENCES invocation_quota_budgets(budget_id),
        maximum INTEGER NOT NULL CHECK (maximum >= 0),
        held INTEGER NOT NULL CHECK (held >= 0),
        spent INTEGER NOT NULL DEFAULT 0 CHECK (spent >= 0),
        measured INTEGER NOT NULL DEFAULT 0 CHECK (measured IN (0, 1)),
        PRIMARY KEY (invocation_id, budget_id)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_invocation_quota_budget
        ON invocation_quota_allocations(budget_id)""",
    """CREATE TABLE IF NOT EXISTS invocation_quota_evidence (
        invocation_id TEXT NOT NULL REFERENCES invocation_quota_reservations(invocation_id),
        revision INTEGER NOT NULL CHECK (revision >= 0),
        evidence_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (invocation_id, revision),
        UNIQUE (invocation_id, evidence_id)
    )""",
)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class SqliteInvocationQuota:
    """Opt-in SQLite accounting backend for InvocationExecutionService.

    ``estimate`` is supplied once by trusted composition, not by each invocation
    caller. It must resolve the principal from authoritative Run context. Calling
    code cannot select budgets: every matching database policy is enforced here.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        estimate: EstimateResolver,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if str(path) == ":memory:" or not str(path).strip():
            raise ValueError("Invocation quotas require an explicit shared SQLite file")
        self._path = str(path)
        self._estimate = estimate
        self._clock = clock

    def _transaction(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        conn = sqlite3.connect(self._path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = operation(conn)
                conn.commit()
                return result
            except BaseException:
                conn.rollback()
                raise
        finally:
            conn.close()

    async def _run(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        # Join a started SQLite transaction even under repeated cancellation.
        # Otherwise a caller could release a hold before this worker commits it.
        worker = asyncio.create_task(asyncio.to_thread(self._transaction, operation))
        cancelled = False
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            # Consume any transaction exception; cancellation remains observable.
            with contextlib.suppress(Exception):
                worker.result()
            raise asyncio.CancelledError
        return worker.result()

    async def ensure_schema(self) -> None:
        def create(conn: sqlite3.Connection) -> None:
            for sql in _SCHEMA:
                conn.execute(sql)

        await self._run(create)

    async def register_budget(self, budget: QuotaBudget) -> None:
        """Install an immutable policy with an explicitly attested opening balance.

        This is a trusted deployment/admin operation. Establish completeness of
        the opening balance and quiesce outstanding work before adding a new
        budget to a previously unmetered scope. Policy hot-reload/backfill is not
        implemented by this slice; existing history is not magically included.
        """
        definition = _json(asdict(budget))

        def register(conn: sqlite3.Connection) -> None:
            row = conn.execute(
                "SELECT definition FROM invocation_quota_budgets WHERE budget_id = ?",
                (budget.budget_id,),
            ).fetchone()
            if row is not None:
                if row["definition"] != definition:
                    raise QuotaEvidenceConflict("budget identity is immutable")
                return
            conn.execute(
                "INSERT INTO invocation_quota_budgets VALUES (?, ?)",
                (budget.budget_id, definition),
            )

        await self._run(register)

    @staticmethod
    def _balance(conn: sqlite3.Connection, budget: QuotaBudget) -> QuotaBalance:
        rows = conn.execute(
            "SELECT spent, held FROM invocation_quota_allocations WHERE budget_id = ?",
            (budget.budget_id,),
        ).fetchall()
        return QuotaBalance(
            budget.budget_id,
            budget.limit - budget.reserve,
            budget.opening_spend + sum(row["spent"] for row in rows),
            sum(row["held"] for row in rows),
        )

    async def balance(self, budget_id: str) -> QuotaBalance:
        def read(conn: sqlite3.Connection) -> QuotaBalance:
            row = conn.execute(
                "SELECT definition FROM invocation_quota_budgets WHERE budget_id = ?",
                (budget_id,),
            ).fetchone()
            if row is None:
                raise KeyError(budget_id)
            return self._balance(conn, QuotaBudget(**json.loads(row["definition"])))

        return await self._run(read)

    async def reserve(  # noqa: C901 - transaction policy covers all matching budgets
        self, invocation: Invocation, binding: Binding
    ) -> None:
        estimate = await self._estimate(invocation, binding)
        if not isinstance(estimate, QuotaEstimate):
            raise TypeError("trusted estimate resolver must return QuotaEstimate")
        if (
            binding.binding_id != invocation.binding.binding_id
            or binding.capability != invocation.binding.capability
        ):
            raise QuotaEvidenceConflict("Binding does not match Invocation")
        identity = _json(
            {
                "workspace_id": binding.workspace_id,
                "principal_id": estimate.principal_id,
                "provider_name": invocation.binding.provider_name,
                "capability": invocation.binding.capability,
                "run_id": invocation.run_id,
                "node_run_id": invocation.node_run_id,
                "attempt_id": invocation.attempt_id,
                "binding_id": binding.binding_id,
                "effect_key": invocation.effect_key,
                "tokens": estimate.tokens,
                "micro_usd": estimate.micro_usd,
            }
        )

        def admit(conn: sqlite3.Connection) -> str:
            old = conn.execute(
                "SELECT * FROM invocation_quota_reservations WHERE invocation_id = ?",
                (invocation.invocation_id,),
            ).fetchone()
            if old is not None:
                if old["identity_json"] != identity:
                    raise QuotaEvidenceConflict("Invocation quota identity was reused")
                if old["state"] == "denied":
                    return str(old["reason"])
                # Idempotent reserve is not permission to dispatch again. The
                # canonical InvocationStore owns effect replay safety (#1133).
                return ""
            # Clock is sampled after acquiring the database write lock, so a
            # queued admission cannot reserve against an already-ended period.
            now = self._clock()
            if not math.isfinite(now):
                raise ValueError("invalid admission clock")
            budgets = [
                QuotaBudget(**json.loads(row["definition"]))
                for row in conn.execute("SELECT definition FROM invocation_quota_budgets")
            ]
            applicable = [
                b
                for b in budgets
                if (
                    b.period_start <= now < b.period_end
                    and (
                        b.provider_name is None
                        or b.provider_name == invocation.binding.provider_name
                    )
                    and (b.workspace_id is None or b.workspace_id == binding.workspace_id)
                    and (b.principal_id is None or b.principal_id == estimate.principal_id)
                    and (b.capability is None or b.capability == binding.capability)
                )
            ]
            reason = "missing applicable quota policy" if not applicable else ""
            allocations: list[tuple[str, str, int, int]] = []
            for budget in applicable:
                maximum = estimate.maximum(budget.unit)
                if maximum is None:
                    reason = f"missing upper bound for budget {budget.budget_id}"
                    break
                if maximum > self._balance(conn, budget).available:
                    reason = f"quota exhausted for budget {budget.budget_id}"
                    break
                allocations.append((invocation.invocation_id, budget.budget_id, maximum, maximum))
            conn.execute(
                "INSERT INTO invocation_quota_reservations "
                "(invocation_id, identity_json, state, reason) VALUES (?, ?, ?, ?)",
                (invocation.invocation_id, identity, "denied" if reason else "held", reason),
            )
            if not reason:
                conn.executemany(
                    "INSERT INTO invocation_quota_allocations "
                    "(invocation_id, budget_id, maximum, held) VALUES (?, ?, ?, ?)",
                    allocations,
                )
            return reason

        reason = await self._run(admit)
        if reason:
            # Refusal evidence commits, but NO budget has been charged/reserved.
            raise InvocationQuotaDenied(reason)

    async def observe(self, invocation: Invocation) -> None:
        """Project a canonical terminal fact into the same Invocation's allocations."""
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
        observation = QuotaObservation(
            invocation_id=invocation.invocation_id,
            provider_name=invocation.binding.provider_name,
            evidence_id="canonical-terminal",
            revision=0,
            outcome=outcome,
            tokens=tokens,
            micro_usd=micro_usd,
        )
        # FAILED can be a refusal before reservation. A completed/unknown call
        # without a reservation is an accounting coverage gap, not free usage.
        await self._apply(observation, missing_ok=invocation.status is InvocationStatus.FAILED)

    async def reconcile(self, observation: QuotaObservation) -> None:
        """Trusted absolute provider correction; does not authorize effect replay.

        The caller must authenticate/verify evidence and assign monotonically
        increasing revisions for this Invocation, not for an entire provider.
        An ambient account aggregate cannot identify this call's spend: include
        it in a separately attested opening balance, never attach it arbitrarily.
        """
        if observation.revision == 0:
            raise ValueError("revision zero is reserved for canonical terminal evidence")
        await self._apply(observation, missing_ok=False)

    async def _apply(  # noqa: C901 - settlement is one atomic evidence fold
        self, observation: QuotaObservation, *, missing_ok: bool
    ) -> None:
        payload = _json(observation.payload())

        def apply(conn: sqlite3.Connection) -> None:  # noqa: C901 - atomic settlement fold
            reservation = conn.execute(
                "SELECT * FROM invocation_quota_reservations WHERE invocation_id = ?",
                (observation.invocation_id,),
            ).fetchone()
            if reservation is None:
                if missing_ok:
                    return  # Admission may have failed before reserving anything.
                raise KeyError(
                    f"unreserved Invocation {observation.invocation_id}: reconcile coverage"
                )
            identity = json.loads(reservation["identity_json"])
            if identity["provider_name"] != observation.provider_name:
                raise QuotaEvidenceConflict("provider evidence does not match Invocation")
            if reservation["state"] == "denied":
                if observation.outcome != "not_applied":
                    raise QuotaEvidenceConflict("denied Invocation has no provider dispatch")
                return
            prior = conn.execute(
                "SELECT payload FROM invocation_quota_evidence WHERE invocation_id = ? "
                "AND (revision = ? OR evidence_id = ?)",
                (observation.invocation_id, observation.revision, observation.evidence_id),
            ).fetchall()
            if prior:
                if any(row["payload"] != payload for row in prior):
                    raise QuotaEvidenceConflict("evidence identity/revision was reused")
                return
            conn.execute(
                "INSERT INTO invocation_quota_evidence VALUES (?, ?, ?, ?)",
                (observation.invocation_id, observation.revision, observation.evidence_id, payload),
            )
            if observation.revision < reservation["revision"]:
                return  # Keep stale evidence, but never roll accounting backwards.
            if observation.outcome == "unknown" and reservation["state"] in {
                "settled",
                "released",
                "pending_usage",
            }:
                raise QuotaEvidenceConflict("unknown cannot replace a confirmed provider outcome")
            rows = conn.execute(
                "SELECT a.*, b.definition FROM invocation_quota_allocations a "
                "JOIN invocation_quota_budgets b USING (budget_id) WHERE invocation_id = ?",
                (observation.invocation_id,),
            ).fetchall()
            pending = False
            for row in rows:
                unit = json.loads(row["definition"])["unit"]
                actual = observation.actual(unit)
                if actual is None:
                    if reservation["state"] == "released" and observation.outcome == "completed":
                        # A correction retracting not-applied proof also retracts
                        # its zeros. Missing usage becomes held again, not free.
                        conn.execute(
                            "UPDATE invocation_quota_allocations "
                            "SET spent = 0, held = maximum, measured = 0 "
                            "WHERE invocation_id = ? AND budget_id = ?",
                            (observation.invocation_id, row["budget_id"]),
                        )
                        pending = True
                    else:
                        # Same-outcome partial corrections retain known dimensions.
                        pending = pending or not bool(row["measured"])
                    continue
                conn.execute(
                    "UPDATE invocation_quota_allocations SET spent = ?, held = 0, measured = 1 "
                    "WHERE invocation_id = ? AND budget_id = ?",
                    (actual, observation.invocation_id, row["budget_id"]),
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
            conn.execute(
                "UPDATE invocation_quota_reservations SET state = ?, revision = ? "
                "WHERE invocation_id = ?",
                (state, observation.revision, observation.invocation_id),
            )

        await self._run(apply)
