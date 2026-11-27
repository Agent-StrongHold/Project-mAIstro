"""PostgreSQL persistence for the per-Workspace working log (#301, M4-H).

The durable twin of `sqlite_store.py` and of `InMemoryWorkspaceLogStore`, run
against the same conformance suite. This is the ``PgWorkspaceLogStore`` the
wiring docstring reserved the ``WorkspaceLogStore`` protocol seam for: a
PostgreSQL deployment used to fall back to the in-process log no matter what
its URL said, because ``_wire_working_memory_backend`` was handed only the
SQLite pool — the retained-observation requirement of ADR-082226-5104/#105
(read: a log that outlives the process) was unreachable on the backend the
container's own PostgreSQL branch selects.

For a managed deployment the tables come from Alembic migration ``072``;
``ensure_working_log_schema`` mirrors that DDL for tests and single-command dev
runs the way ``ensure_goal_schema`` mirrors migration 063 — a database that
never ran the chain still gets the real durable tables, never a substitute
schema nobody migrates. The two DDL sources are held to one catalogue by
``tests/memory/test_working_log_pg_schema_agreement.py``.

The JSONB convention is the one ``runs/evidence_json`` documents for every PG
store: payloads are bound as JSON **text** with an explicit
``$n::text::jsonb`` cast so no pool-construction choice (a raw
``asyncpg.create_pool`` vs ``maistro.persistence.get_pool``'s registered JSON
codec) changes what the row stores, and reads go through ``decode_payload``,
which accepts either the driver's text or a codec-decoded dict.

What differs from the reference is not the rules but the concurrency, and
there is little of it: every statement is a single atomic INSERT/SELECT/DELETE
on the pool, ``put_result`` resolves the idempotency with
``ON CONFLICT ... DO NOTHING RETURNING`` rather than a rowcount string, and
``purge_workspace`` runs its two driven deletions in one transaction so a
Workspace never keeps its results while having lost its log.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from maistro.memory.working.types import (
    ObservationKind,
    WorkingResult,
    WorkspaceObservation,
)
from maistro.runs.evidence_json import decode_payload

if TYPE_CHECKING:  # pragma: no cover - typing only
    import asyncpg
    import asyncpg.pool

#: Tables the PostgreSQL working log answers through. Migration 072 owns their
#: DDL for managed deployments; ``_PG_SCHEMA`` below mirrors it.
WORKING_LOG_PG_TABLES: Final = (
    "workspace_working_log",
    "workspace_working_results",
)

#: The working-log tables' DDL, mirroring
#: ``alembic/versions/072_workspace_working_log.py`` statement for statement.
#: Written out rather than imported on purpose — a migration must keep creating
#: what it created on the day it ran, so it cannot import live application code
#: — which is exactly why the agreement test compares the two against a real
#: catalogue instead of trusting the review.
_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_working_log (
    seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    cycle INTEGER NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    result_ref TEXT,
    digest TEXT NOT NULL DEFAULT '',
    survive_reset BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    UNIQUE (workspace_id, entry_id)
);
CREATE INDEX IF NOT EXISTS idx_workspace_working_log_ws
    ON workspace_working_log (workspace_id, seq);

CREATE TABLE IF NOT EXISTS workspace_working_results (
    workspace_id TEXT NOT NULL,
    result_id TEXT NOT NULL,
    source TEXT NOT NULL,
    digest TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    content TEXT NOT NULL,
    meta JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (workspace_id, result_id)
);
"""

#: Namespace for the working-log bootstrap advisory lock. Arbitrary but fixed,
#: and distinct from the event stores' ``0x6D61_6973`` and the Goal store's
#: ``0x676F_616C``: any two processes running ``ensure_working_log_schema``
#: must pick the same number, and no unrelated advisory lock in this database
#: should pick it either.
_SCHEMA_LOCK_KEY = 0x776F_726B  # "work"


async def ensure_working_log_schema(pool: asyncpg.Pool) -> None:
    """Create the two working-log tables when the database does not have them.

    Idempotent, and safe to call concurrently: ``CREATE TABLE IF NOT EXISTS``
    is idempotent but **not** serialised, so — same failure
    ``ensure_goal_schema`` documents — two workers that both observe the tables
    as absent can both run the DDL and one loses with a ``pg_type`` unique
    violation rather than a clean no-op. A transaction-scoped advisory lock
    serialises them and is released when the transaction ends, including by
    crash.

    Migration 072 remains the real path for a managed deployment; this is what
    lets the Container come up — with the observation log on the same durable
    PostgreSQL the deployment already selected — in tests and single-command
    dev runs that never ran the chain.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", _SCHEMA_LOCK_KEY)
        await conn.execute(_PG_SCHEMA)


def _entry_from_row(seq: int, payload_raw: Any) -> WorkspaceObservation:
    """Rebuild an entry with its log position from the row, not the payload.

    ``seq`` belongs to the log (it is assigned on ``append``), so the column
    is authoritative and the payload's ``seq`` (``None`` for a pre-append
    entry) is ignored — the same rule ``sqlite_store._entry_from_row`` pins.
    The payload itself is decoded defensively: a raw ``asyncpg.create_pool``
    hands back text, ``maistro.persistence.get_pool``'s registered codec hands
    back a dict, and the store must be right over either.
    """
    payload = decode_payload(payload_raw)
    payload["kind"] = ObservationKind(str(payload["kind"]))
    payload["created_at"] = datetime.fromisoformat(str(payload["created_at"]))
    return replace(WorkspaceObservation(**payload), seq=int(seq))


class PgWorkspaceLogStore:
    """The PostgreSQL durable twin. Must agree with
    :class:`InMemoryWorkspaceLogStore` on every rule the conformance suite
    exercises.

    M1 product-local projection: Workspace
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def append(self, entry: WorkspaceObservation) -> WorkspaceObservation:
        row = await self._pool.fetchrow(
            """
            INSERT INTO workspace_working_log
                (workspace_id, entry_id, kind, cycle, run_id, result_ref,
                 digest, survive_reset, created_at, payload)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::text::jsonb)
            RETURNING seq
            """,
            entry.workspace_id,
            entry.entry_id,
            entry.kind.value,
            entry.cycle,
            entry.run_id,
            entry.result_ref,
            entry.digest,
            entry.survive_reset,
            entry.created_at,
            entry.to_json(),
        )
        return replace(entry, seq=int(row["seq"]))

    async def list_entries(
        self,
        workspace_id: str,
        *,
        kinds: tuple[ObservationKind, ...] | None = None,
        after_seq: int = 0,
        limit: int | None = None,
        survive_reset: bool | None = None,
    ) -> list[WorkspaceObservation]:
        sql = "SELECT seq, payload FROM workspace_working_log WHERE workspace_id = $1 AND seq > $2"
        params: list[Any] = [workspace_id, after_seq]
        if kinds is not None:
            params.append([k.value for k in kinds])
            sql += f" AND kind = ANY(${len(params)})"
        if survive_reset is not None:
            params.append(survive_reset)
            sql += f" AND survive_reset = ${len(params)}"
        sql += " ORDER BY seq ASC"
        if limit is not None:
            params.append(limit)
            sql += f" LIMIT ${len(params)}"
        rows = await self._pool.fetch(sql, *params)
        return [_entry_from_row(row["seq"], row["payload"]) for row in rows]

    async def get_entry(self, workspace_id: str, entry_id: str) -> WorkspaceObservation | None:
        row = await self._pool.fetchrow(
            "SELECT seq, payload FROM workspace_working_log"
            " WHERE workspace_id = $1 AND entry_id = $2",
            workspace_id,
            entry_id,
        )
        return _entry_from_row(row["seq"], row["payload"]) if row is not None else None

    async def latest_entry(
        self,
        workspace_id: str,
        *,
        kinds: tuple[ObservationKind, ...] | None = None,
    ) -> WorkspaceObservation | None:
        sql = "SELECT seq, payload FROM workspace_working_log WHERE workspace_id = $1"
        params: list[Any] = [workspace_id]
        if kinds is not None:
            params.append([k.value for k in kinds])
            sql += f" AND kind = ANY(${len(params)})"
        sql += " ORDER BY seq DESC LIMIT 1"
        row = await self._pool.fetchrow(sql, *params)
        return _entry_from_row(row["seq"], row["payload"]) if row is not None else None

    async def put_result(self, result: WorkingResult) -> bool:
        """Store a full result under its content address.

        ``RETURNING`` turns the idempotency into a row answer: an empty result
        is the conflict path (identical ``result_id`` already stored), a row is
        the first insert — no parsing of a driver status string.
        """
        rows = await self._pool.fetch(
            """
            INSERT INTO workspace_working_results
                (workspace_id, result_id, source, digest, created_at, content, meta)
            VALUES ($1, $2, $3, $4, $5, $6, $7::text::jsonb)
            ON CONFLICT (workspace_id, result_id) DO NOTHING
            RETURNING result_id
            """,
            result.workspace_id,
            result.result_id,
            result.source,
            result.digest,
            result.created_at,
            result.content,
            _meta_json(result.meta),
        )
        return len(rows) > 0

    async def get_result(self, workspace_id: str, result_id: str) -> WorkingResult | None:
        row = await self._pool.fetchrow(
            "SELECT source, digest, created_at, content, meta"
            " FROM workspace_working_results WHERE workspace_id = $1 AND result_id = $2",
            workspace_id,
            result_id,
        )
        if row is None:
            return None
        return WorkingResult(
            workspace_id=workspace_id,
            result_id=result_id,
            source=str(row["source"]),
            content=str(row["content"]),
            created_at=row["created_at"],
            meta=decode_payload(row["meta"]),
        )

    async def purge_workspace(self, workspace_id: str) -> int:
        """Delete every log entry and result for a Workspace, in one
        transaction. Returns the number of entries purged (results are not
        counted — they are payload, not observations)."""
        async with self._pool.acquire() as conn, conn.transaction():
            rows = await conn.fetch(
                "DELETE FROM workspace_working_log WHERE workspace_id = $1 RETURNING seq",
                workspace_id,
            )
            await conn.execute(
                "DELETE FROM workspace_working_results WHERE workspace_id = $1",
                workspace_id,
            )
        return len(rows)


def _meta_json(meta: dict[str, Any]) -> str:
    """Result metadata as JSON text for the ``::text::jsonb`` cast, matching
    the SQLite twin's ``json.dumps(meta, sort_keys=True)`` byte for byte."""
    return json.dumps(meta, sort_keys=True)
