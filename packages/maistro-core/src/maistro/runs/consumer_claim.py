"""Atomic physical claims for the admitted-Run consumer (#544).

A consumer claim is not a bare ``RunStatus.RUNNING`` write. The write that makes
that statement true also persists the logical NodeRun and a leased physical
``AttemptStatus.RUNNING`` Attempt in the same transaction. The returned claim
therefore always names already-running physical evidence. If the claimant dies
after the transaction commits, the ordinary Attempt lease sweep has evidence to
reclaim; if it dies before commit, the Run is still QUEUED. There is no third
state and no second recovery mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from maistro.runs.evidence_json import json_of, model_of, model_of_json
from maistro.runs.lifecycle import (
    renewed_lease,
    transition_attempt,
    transition_node_run,
    transition_run,
)
from maistro.runs.model import (
    Attempt,
    AttemptStatus,
    ExecutionLease,
    NodeRun,
    Run,
    RunStatus,
)
from maistro.runs.pg_store import PgRunStore
from maistro.runs.sqlite_store import SqliteRunStore
from maistro.runs.store import InMemoryRunStore, RunIntegrityError, RunStore


class ConsumerClaimLost(RunIntegrityError):
    """Another consumer moved the Run before this claimant could own it."""


@dataclass(frozen=True)
class ConsumerClaim:
    run: Run
    node_run: NodeRun
    attempt: Attempt


@runtime_checkable
class ConsumerClaimStore(RunStore, Protocol):
    async def claim_consumer_run(
        self,
        run_id: str,
        *,
        node_id: str,
        runtime_id: str,
        executor_id: str,
        lease_ttl: timedelta,
        deadline_at: datetime | None = None,
    ) -> ConsumerClaim: ...


def _claim_models(
    run: Run,
    *,
    node_id: str,
    node_ordinal: int,
    runtime_id: str,
    executor_id: str,
    lease_ttl: timedelta,
    deadline_at: datetime | None,
) -> ConsumerClaim:
    if run.status is not RunStatus.QUEUED:
        raise ConsumerClaimLost(
            f"Run {run.run_id!r} is {run.status.value}, not queued for consumer claim"
        )
    graph = run.graph.materialize()
    if not any(node.node_id == node_id for node in graph.nodes):
        raise RunIntegrityError(f"node_id {node_id!r} is not present in the Run Graph snapshot")

    node_run = NodeRun(run_id=run.run_id, node_id=node_id, ordinal=node_ordinal)
    node_run = transition_node_run(node_run, RunStatus.QUEUED)
    node_run = transition_node_run(node_run, RunStatus.RUNNING)

    attempt = Attempt(
        node_run_id=node_run.node_run_id,
        ordinal=1,
        runtime_id=runtime_id,
        executor_id=executor_id,
        deadline_at=deadline_at,
    )
    lease = ExecutionLease(
        node_run_id=node_run.node_run_id,
        attempt_id=attempt.attempt_id,
        lease_epoch=attempt.ordinal,
        holder=executor_id or runtime_id,
    )
    lease = renewed_lease(lease, at=lease.issued_at, ttl=lease_ttl)
    attempt = Attempt.model_validate(
        {**attempt.model_dump(mode="python"), "execution_lease": lease}
    )
    attempt = transition_attempt(attempt, AttemptStatus.RUNNING)
    return ConsumerClaim(
        run=transition_run(run, RunStatus.RUNNING),
        node_run=node_run,
        attempt=attempt,
    )


class ClaimingInMemoryRunStore(InMemoryRunStore):
    async def claim_consumer_run(
        self,
        run_id: str,
        *,
        node_id: str,
        runtime_id: str,
        executor_id: str,
        lease_ttl: timedelta,
        deadline_at: datetime | None = None,
    ) -> ConsumerClaim:
        # No await between read and all three writes: this store is used from
        # one event loop, so the block is atomic with respect to other tasks.
        run = self._require_run(run_id)
        ordinal = 1 + sum(node_run.run_id == run_id for node_run in self._node_runs.values())
        claim = _claim_models(
            run,
            node_id=node_id,
            node_ordinal=ordinal,
            runtime_id=runtime_id,
            executor_id=executor_id,
            lease_ttl=lease_ttl,
            deadline_at=deadline_at,
        )
        self._runs[run_id] = claim.run
        self._node_runs[claim.node_run.node_run_id] = claim.node_run
        self._attempts[claim.attempt.attempt_id] = claim.attempt
        return claim


class ClaimingSqliteRunStore(SqliteRunStore):
    async def claim_consumer_run(
        self,
        run_id: str,
        *,
        node_id: str,
        runtime_id: str,
        executor_id: str,
        lease_ttl: timedelta,
        deadline_at: datetime | None = None,
    ) -> ConsumerClaim:
        async with self._write_lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = await self._fetchone(
                    "SELECT payload FROM canonical_runs WHERE run_id = ?",
                    (run_id,),
                )
                if row is None:
                    raise RunIntegrityError(f"Run {run_id!r} does not exist")
                run = model_of_json(Run, row[0])
                ordinal_row = await self._fetchone(
                    "SELECT COALESCE(MAX(ordinal), 0) FROM canonical_node_runs WHERE run_id = ?",
                    (run_id,),
                )
                ordinal = int(ordinal_row[0]) + 1 if ordinal_row is not None else 1
                claim = _claim_models(
                    run,
                    node_id=node_id,
                    node_ordinal=ordinal,
                    runtime_id=runtime_id,
                    executor_id=executor_id,
                    lease_ttl=lease_ttl,
                    deadline_at=deadline_at,
                )
                await self._conn.execute(
                    "UPDATE canonical_runs SET status = ?, payload = ? WHERE run_id = ?",
                    (claim.run.status.value, json_of(claim.run), run_id),
                )
                await self._conn.execute(
                    """INSERT INTO canonical_node_runs
                       (node_run_id, run_id, node_id, ordinal, status, payload)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        claim.node_run.node_run_id,
                        claim.node_run.run_id,
                        claim.node_run.node_id,
                        claim.node_run.ordinal,
                        claim.node_run.status.value,
                        json_of(claim.node_run),
                    ),
                )
                await self._conn.execute(
                    """INSERT INTO canonical_attempts
                       (attempt_id, node_run_id, ordinal, status, payload)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        claim.attempt.attempt_id,
                        claim.attempt.node_run_id,
                        claim.attempt.ordinal,
                        claim.attempt.status.value,
                        json_of(claim.attempt),
                    ),
                )
                await self._conn.commit()
                return claim
            except Exception:
                await self._conn.rollback()
                raise


class ClaimingPgRunStore(PgRunStore):
    async def claim_consumer_run(
        self,
        run_id: str,
        *,
        node_id: str,
        runtime_id: str,
        executor_id: str,
        lease_ttl: timedelta,
        deadline_at: datetime | None = None,
    ) -> ConsumerClaim:
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT payload FROM canonical_runs WHERE run_id = $1 FOR UPDATE",
                run_id,
            )
            if row is None:
                raise RunIntegrityError(f"Run {run_id!r} does not exist")
            run = model_of(Run, row["payload"])
            ordinal = (
                await conn.fetchval(
                    "SELECT COALESCE(MAX(ordinal), 0) FROM canonical_node_runs WHERE run_id = $1",
                    run_id,
                )
            ) + 1
            claim = _claim_models(
                run,
                node_id=node_id,
                node_ordinal=ordinal,
                runtime_id=runtime_id,
                executor_id=executor_id,
                lease_ttl=lease_ttl,
                deadline_at=deadline_at,
            )
            await conn.execute(
                "UPDATE canonical_runs SET status = $1, payload = $2::text::jsonb WHERE run_id = $3",
                claim.run.status.value,
                json_of(claim.run),
                run_id,
            )
            await conn.execute(
                """INSERT INTO canonical_node_runs
                   (node_run_id, run_id, node_id, ordinal, status, payload)
                   VALUES ($1, $2, $3, $4, $5, $6::text::jsonb)""",
                claim.node_run.node_run_id,
                claim.node_run.run_id,
                claim.node_run.node_id,
                claim.node_run.ordinal,
                claim.node_run.status.value,
                json_of(claim.node_run),
            )
            await conn.execute(
                """INSERT INTO canonical_attempts
                   (attempt_id, node_run_id, ordinal, status, payload)
                   VALUES ($1, $2, $3, $4, $5::text::jsonb)""",
                claim.attempt.attempt_id,
                claim.attempt.node_run_id,
                claim.attempt.ordinal,
                claim.attempt.status.value,
                json_of(claim.attempt),
            )
            return claim


__all__ = [
    "ClaimingInMemoryRunStore",
    "ClaimingPgRunStore",
    "ClaimingSqliteRunStore",
    "ConsumerClaim",
    "ConsumerClaimLost",
    "ConsumerClaimStore",
]
