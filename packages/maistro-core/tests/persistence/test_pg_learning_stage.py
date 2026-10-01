"""Knowledge-stage transitions on the PostgreSQL twin (M4-B1 / ADR-103).

Same approach as `test_pg_learnings.py`: asyncpg is faked with an in-process
double that records the exact SQL and params, so these tests pin the guarded
UPDATE (a concurrent move fails loudly instead of double-applying), the
ledger INSERT in the same transaction, and the round-tripped row shape.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.memory.learnings.lifecycle import InvalidStageTransition
from maistro.persistence.pg_learnings import PgLearningStore
from maistro.types.memory import Learning, LearningStage

ORG = "org-a"


class FakeRecord(dict):
    """Mimics asyncpg.Record: supports both ``row["x"]`` and ``row.get("x")``."""


class Call:
    def __init__(self, method: str, query: str, args: tuple[Any, ...]) -> None:
        self.method = method
        self.query = query
        self.args = args


class TransactionedFakeConnection:
    """FakeConnection plus the `transaction()` context asyncpg pools expose."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._fetchrow_results: list[FakeRecord | None] = []
        self._execute_results: list[str] = []

    def queue_fetchrow(self, row: dict[str, Any] | None) -> None:
        self._fetchrow_results.append(FakeRecord(row) if row is not None else None)

    def queue_execute(self, status: str = "UPDATE 1") -> None:
        self._execute_results.append(status)

    async def fetch(self, query: str, *args: Any) -> list[FakeRecord]:
        self.calls.append(Call("fetch", query, args))
        return []

    async def fetchrow(self, query: str, *args: Any) -> FakeRecord | None:
        self.calls.append(Call("fetchrow", query, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append(Call("execute", query, args))
        return self._execute_results.pop(0) if self._execute_results else "OK"

    def transaction(self) -> _FakeTransaction:
        self.calls.append(Call("transaction", "", ()))
        return _FakeTransaction()


class _FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: Any) -> None:
        return None


class FakePool:
    def __init__(self, conn: TransactionedFakeConnection) -> None:
        self._conn = conn

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self._conn)


class _AcquireCtx:
    def __init__(self, conn: TransactionedFakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> TransactionedFakeConnection:
        return self._conn

    async def __aexit__(self, *exc: Any) -> None:
        return None


def row_for(learning: Learning) -> dict[str, Any]:
    """The shape a `SELECT *` hands the mapper, with the stage columns on it."""
    return {
        "id": learning.id,
        "category": learning.category,
        "trigger_keys": '["timeout"]',
        "learning": learning.learning,
        "tool_name": learning.tool_name,
        "source_query": learning.source_query,
        "agent_id": learning.agent_id,
        "user_id": learning.user_id,
        "org_id": learning.org_id,
        "team_id": learning.team_id,
        "scope": str(learning.scope),
        "hit_count": learning.hit_count,
        "status": learning.status,
        "rca_category": learning.rca_category,
        "rca_prevention": learning.rca_prevention,
        "success_after_use": learning.success_after_use,
        "failure_after_use": learning.failure_after_use,
        "run_id": learning.run_id,
        "node_run_id": learning.node_run_id,
        "attempt_id": learning.attempt_id,
        "stage": str(learning.stage),
        "validated_by": learning.validated_by,
        "promoted_by": learning.promoted_by,
    }


@pytest.fixture
def conn() -> TransactionedFakeConnection:
    return TransactionedFakeConnection()


@pytest.fixture
def store(conn: TransactionedFakeConnection) -> PgLearningStore:
    return PgLearningStore(FakePool(conn))  # type: ignore[arg-type]


def make_learning(**overrides: Any) -> Learning:
    defaults: dict[str, Any] = {
        "id": 7,
        "tool_name": "bash",
        "trigger_keys": ["timeout"],
        "learning": "retry once on timeout",
        "org_id": ORG,
    }
    defaults.update(overrides)
    return Learning(**defaults)


@pytest.mark.asyncio
async def test_advance_stage_updates_the_row_and_writes_the_ledger_in_one_transaction(
    store: PgLearningStore, conn: TransactionedFakeConnection
) -> None:
    conn.queue_fetchrow(row_for(make_learning(stage=LearningStage.LEARNING)))
    learning = await store.advance_stage(
        7, to_stage=LearningStage.VALIDATED, actor="gauntlet", org_id=ORG
    )

    assert learning.stage is LearningStage.VALIDATED
    assert learning.validated_by == "gauntlet"

    methods = [c.method for c in conn.calls]
    assert methods == ["transaction", "fetchrow", "execute", "execute"], (
        "row update and ledger row must be one transaction, in that order"
    )
    update = conn.calls[2]
    assert "UPDATE learnings SET stage" in update.query
    assert "AND stage = $6" in update.query, (
        "the guarded UPDATE is what makes a concurrent move fail loudly"
    )
    assert "org_id = $7" in update.query
    ledger = conn.calls[3]
    assert "INSERT INTO learning_stage_transitions" in ledger.query
    assert ledger.args == (
        7,
        ORG,
        LearningStage.LEARNING,
        LearningStage.VALIDATED,
        "gauntlet",
        "",
    )


@pytest.mark.asyncio
async def test_a_row_that_moved_concurrently_raises_instead_of_half_applying(
    store: PgLearningStore, conn: TransactionedFakeConnection
) -> None:
    conn.queue_fetchrow(row_for(make_learning(stage=LearningStage.LEARNING)))
    conn.queue_execute("UPDATE 0")
    with pytest.raises(InvalidStageTransition, match="left stage"):
        await store.advance_stage(7, to_stage=LearningStage.VALIDATED, actor="gauntlet", org_id=ORG)


@pytest.mark.asyncio
async def test_a_row_outside_the_callers_scope_is_not_found(
    store: PgLearningStore, conn: TransactionedFakeConnection
) -> None:
    conn.queue_fetchrow(None)
    with pytest.raises(KeyError):
        await store.advance_stage(7, to_stage=LearningStage.LEARNING, actor="x", org_id="org-b")


@pytest.mark.asyncio
async def test_stage_history_reads_the_ledger_scoped(
    store: PgLearningStore, conn: TransactionedFakeConnection
) -> None:
    conn.queue_fetchrow({"1": 1})
    conn.calls.clear()  # the scope probe is asserted separately below

    async def fake_fetch(query: str, *args: Any) -> list[FakeRecord]:
        conn.calls.append(Call("fetch", query, args))
        return [
            FakeRecord(
                {
                    "learning_id": 7,
                    "org_id": ORG,
                    "from_stage": "memory",
                    "to_stage": "learning",
                    "actor": "planner",
                    "reason": "asserted",
                }
            )
        ]

    conn.fetch = fake_fetch  # type: ignore[method-assign]
    history = await store.stage_history(7, org_id=ORG)
    assert len(history) == 1
    assert history[0].from_stage is LearningStage.MEMORY
    assert history[0].actor == "planner"
    assert "ORDER BY id" in conn.calls[-1].query

    conn.queue_fetchrow(None)
    with pytest.raises(KeyError):
        await store.stage_history(7, org_id="org-b")


@pytest.mark.asyncio
async def test_store_writes_the_stage_columns(
    store: PgLearningStore, conn: TransactionedFakeConnection
) -> None:
    conn.queue_execute("INSERT 0 1")
    conn.queue_fetchrow({"id": 7})
    await store.store(make_learning(id=None))

    insert = next(c for c in conn.calls if "INSERT INTO learnings" in c.query)
    assert "stage, validated_by, promoted_by" in insert.query
    assert insert.args[-3:] == (LearningStage.MEMORY, "", "")
