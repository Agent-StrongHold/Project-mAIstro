"""Durable knowledge-stage transitions on the SQLite twin (M4-B1 / ADR-103).

The acceptance bar for #117 is that ladder transitions and their provenance
are *durable and auditable*: a restart must not demote a validated learning,
erase its audit trail, or resurrect a claim. These tests run against a real
in-process SQLite database, including the in-place upgrade of a file created
before the ladder existed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import aiosqlite
import pytest

from maistro.memory.learnings.lifecycle import InvalidStageTransition
from maistro.persistence.sqlite_learnings import SqliteLearningStore
from maistro.types.memory import Learning, LearningStage

ORG = "org-a"


def make_learning(**overrides: object) -> Learning:
    defaults: dict[str, object] = {
        "tool_name": "bash",
        "trigger_keys": ["timeout"],
        "learning": "retry once on timeout",
        "org_id": ORG,
        "user_id": "u1",
    }
    defaults.update(overrides)
    return Learning(**defaults)  # type: ignore[arg-type]


async def _open(path: str) -> tuple[SqliteLearningStore, aiosqlite.Connection]:
    conn = await aiosqlite.connect(path)
    store = SqliteLearningStore(conn)
    await store.ensure_schema()
    return store, conn


@pytest.fixture
async def store() -> AsyncIterator[SqliteLearningStore]:
    s, conn = await _open(":memory:")
    yield s
    await conn.close()


@pytest.mark.asyncio
@pytest.mark.ac("SPEC-100426-b103/AC-2")
async def test_a_transition_persists_row_and_ledger_together(
    store: SqliteLearningStore,
) -> None:
    lid = await store.store(make_learning())
    # A stored row enters at LEARNING (ADR-100126-9a4b); the first durable
    # rung is the Gauntlet's LEARNING -> VALIDATED confirmation.
    learning = await store.advance_stage(
        lid, to_stage=LearningStage.VALIDATED, actor="gauntlet", reason="asserted", org_id=ORG
    )
    assert learning.stage is LearningStage.VALIDATED

    # Read back through a fresh SELECT, not the returned object.
    rows = await store.list_all(org_id=ORG)
    assert rows[0].stage is LearningStage.VALIDATED
    history = await store.stage_history(lid, org_id=ORG)
    assert len(history) == 1
    assert history[0].actor == "gauntlet"
    assert history[0].reason == "asserted"
    assert history[0].from_stage is LearningStage.LEARNING
    assert history[0].to_stage is LearningStage.VALIDATED


@pytest.mark.asyncio
@pytest.mark.ac("SPEC-100426-b103/AC-2")
async def test_the_ladder_survives_a_reconnect() -> None:
    """A restart cannot demote a validated learning or erase its provenance."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "learnings.db")
        s1, conn1 = await _open(db_path)
        lid = await s1.store(make_learning())
        await s1.advance_stage(lid, to_stage=LearningStage.VALIDATED, actor="gauntlet", org_id=ORG)
        await conn1.close()

        s2, conn2 = await _open(db_path)  # a "restart"
        try:
            rows = await s2.list_all(org_id=ORG)
            assert rows[0].stage is LearningStage.VALIDATED
            assert rows[0].validated_by == "gauntlet"
            history = await s2.stage_history(lid, org_id=ORG)
            assert [(t.from_stage, t.to_stage) for t in history] == [
                (LearningStage.LEARNING, LearningStage.VALIDATED),
            ]
        finally:
            await conn2.close()


@pytest.mark.asyncio
@pytest.mark.ac("SPEC-100426-b103/AC-3")
async def test_repertoire_commit_flips_status_so_promoted_readers_keep_working(
    store: SqliteLearningStore,
) -> None:
    lid = await store.store(make_learning())
    await store.advance_stage(lid, to_stage=LearningStage.VALIDATED, actor="gauntlet", org_id=ORG)
    learning = await store.advance_stage(
        lid, to_stage=LearningStage.REPERTOIRE, actor="curator", org_id=ORG
    )
    assert learning.status == "promoted"
    assert learning.promoted_by == "curator"
    promoted = await store.get_promoted(org_id=ORG)
    assert [lr.id for lr in promoted] == [lid]


@pytest.mark.asyncio
@pytest.mark.ac("SPEC-100426-b103/AC-3")
async def test_a_pre_ladder_database_is_upgraded_without_fabricated_provenance() -> None:
    """A file created before the ladder lands on the entry rung, honestly.

    Old rows enter at `learning` — extraction was always the MEMORY ->
    LEARNING step — with blank actors: the upgrade must not stamp a validation
    or promotion that never happened. Nothing is backfilled — the ledger
    starts empty and records only transitions from now on.
    """
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "legacy.db")
        s1, conn1 = await _open(db_path)
        lid = await s1.store(make_learning())
        await s1.advance_stage(lid, to_stage=LearningStage.VALIDATED, actor="gauntlet", org_id=ORG)
        # Simulate the pre-ladder file: drop the stage columns' content the
        # way an old writer would have left them — by removing the columns.
        await conn1.execute("DROP TABLE learning_stage_transitions")
        await conn1.execute(
            "CREATE TABLE learnings_old AS SELECT id, category, trigger_keys, learning, "
            "tool_name, source_query, agent_id, user_id, org_id, team_id, scope, "
            "hit_count, status, rca_category, rca_prevention, success_after_use, "
            "failure_after_use, run_id, node_run_id, attempt_id FROM learnings"
        )
        await conn1.execute("DROP TABLE learnings")
        await conn1.execute("ALTER TABLE learnings_old RENAME TO learnings")
        await conn1.commit()
        await conn1.close()

        s2, conn2 = await _open(db_path)  # ensure_schema performs the upgrade
        try:
            rows = await s2.list_all(org_id=ORG)
            assert rows[0].stage is LearningStage.LEARNING
            assert rows[0].validated_by == ""
            assert rows[0].promoted_by == ""
            assert await s2.stage_history(rows[0].id, org_id=ORG) == []
            # The upgraded row can still climb the ladder normally.
            advanced = await s2.advance_stage(
                rows[0].id, to_stage=LearningStage.VALIDATED, actor="gauntlet", org_id=ORG
            )
            assert advanced.stage is LearningStage.VALIDATED
        finally:
            await conn2.close()


@pytest.mark.asyncio
@pytest.mark.ac("SPEC-100426-b103/AC-2")
async def test_an_illegal_transition_writes_neither_row_nor_ledger(
    store: SqliteLearningStore,
) -> None:
    lid = await store.store(make_learning())
    # From the entry rung both degenerate moves are illegal: the same-rung
    # no-op (the ladder never repeats) and the two-rung skip (it is
    # single-step). Neither may move the row or write a ledger row.
    with pytest.raises(InvalidStageTransition):
        await store.advance_stage(lid, to_stage=LearningStage.LEARNING, actor="x", org_id=ORG)
    with pytest.raises(InvalidStageTransition):
        await store.advance_stage(lid, to_stage=LearningStage.REPERTOIRE, actor="x", org_id=ORG)
    rows = await store.list_all(org_id=ORG)
    assert rows[0].stage is LearningStage.LEARNING
    assert await store.stage_history(lid, org_id=ORG) == []


@pytest.mark.asyncio
@pytest.mark.ac("SPEC-100426-b103/AC-2")
async def test_another_org_cannot_read_or_advance(
    store: SqliteLearningStore,
) -> None:
    lid = await store.store(make_learning())
    with pytest.raises(KeyError):
        await store.advance_stage(lid, to_stage=LearningStage.VALIDATED, actor="x", org_id="org-b")
    with pytest.raises(KeyError):
        await store.stage_history(lid, org_id="org-b")


@pytest.mark.asyncio
@pytest.mark.ac("SPEC-100426-b103/AC-2")
async def test_a_losing_concurrent_transition_raises_and_leaves_no_ledger_row() -> None:
    """Two writers race for the same rung: one wins, one loses loudly.

    ADR-103 rule 3: a concurrent double-transition must *lose loudly* — the
    loser raises instead of half-applying, and the ledger never records a
    transition the row does not carry. The interleave is deterministic: the
    loser's read is parked on a gate while the winner commits, so the
    loser's guarded UPDATE provably runs against the row the winner already
    moved (its `plan_advance` still sees the stale `learning` stage, so the
    rejection can only come from the rowcount check on the UPDATE itself).
    """
    import asyncio
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "race.db")
        winner, conn_w = await _open(db_path)
        loser, conn_l = await _open(db_path)
        try:
            lid = await winner.store(make_learning())

            real_scoped_row = loser._scoped_row
            loser_has_read = asyncio.Event()
            winner_may_commit = asyncio.Event()

            async def parked_scoped_row(learning_id: int, *, org_id: str) -> dict[str, Any]:
                row = await real_scoped_row(learning_id, org_id=org_id)
                loser_has_read.set()  # holding a stale read of stage=learning
                await winner_may_commit.wait()
                return row

            loser._scoped_row = parked_scoped_row  # type: ignore[method-assign]
            losing_task = asyncio.create_task(
                loser.advance_stage(
                    lid, to_stage=LearningStage.VALIDATED, actor="loser", org_id=ORG
                )
            )
            await loser_has_read.wait()
            winner_learning = await winner.advance_stage(
                lid, to_stage=LearningStage.VALIDATED, actor="winner", org_id=ORG
            )
            assert winner_learning.stage is LearningStage.VALIDATED
            winner_may_commit.set()

            with pytest.raises(InvalidStageTransition):
                await losing_task

            # Exactly one applied transition, exactly one ledger row: the
            # loser left neither a moved row nor a phantom audit record.
            rows = await winner.list_all(org_id=ORG)
            assert rows[0].stage is LearningStage.VALIDATED
            history = await winner.stage_history(lid, org_id=ORG)
            assert [(t.actor, t.from_stage, t.to_stage) for t in history] == [
                ("winner", LearningStage.LEARNING, LearningStage.VALIDATED)
            ]
        finally:
            await conn_l.close()
            await conn_w.close()
