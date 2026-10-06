"""Durability of Gauntlet validation provenance on the SQLite twin (M4-B2).

The promotion verdict — the exact evaluation Runs, the evaluator version, the
frozen-content hash — is written by `promote_learning` and must survive a
restart, because a promoted learning that cannot say why it is in the
repertoire is indistinguishable from one that waved itself through. Also
covered: a pre-Gauntlet database upgrades in place and reads old rows as the
never-validated learnings they honestly were.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import aiosqlite
import pytest

from maistro.memory.exposure import MemoryExposureMode
from maistro.persistence.sqlite_learnings import SqliteLearningStore
from maistro.types.memory import Learning


@pytest.fixture
async def store() -> AsyncIterator[SqliteLearningStore]:
    conn = await aiosqlite.connect(":memory:")
    s = SqliteLearningStore(conn, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
    await s.ensure_schema()
    yield s
    await conn.close()


def make_learning(**kwargs: object) -> Learning:
    defaults: dict[str, object] = {
        "category": "tooling",
        "trigger_keys": ["deploy"],
        "learning": "snapshot the workspace before deploying",
        "tool_name": "bash",
        "run_id": "run-producer-1",
    }
    defaults.update(kwargs)
    return Learning(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_promote_learning_writes_provenance_that_round_trips(
    store: SqliteLearningStore,
) -> None:
    lid = await store.store(make_learning())

    promoted = await store.promote_learning(
        lid,
        validated_by="independent-trials",
        evaluator_version="1.4.2",
        validated_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        validation_run_ids=("run-eval-1", "run-eval-2", "run-eval-3"),
        validation_content_hash="0f1e2d3c",
    )

    assert promoted is not None
    assert promoted.status == "promoted"
    assert promoted.validated_by == "independent-trials"
    assert promoted.validated_evaluator_version == "1.4.2"
    assert promoted.validated_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert promoted.validation_run_ids == ["run-eval-1", "run-eval-2", "run-eval-3"]
    assert promoted.validation_content_hash == "0f1e2d3c"

    # A fresh read — the shape a restarted process sees — carries the same
    # evidence, in order, exactly.
    rows = await store.list_all()
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "promoted"
    assert row.validated_by == "independent-trials"
    assert row.validated_evaluator_version == "1.4.2"
    assert row.validated_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert row.validation_run_ids == ["run-eval-1", "run-eval-2", "run-eval-3"]
    assert row.validation_content_hash == "0f1e2d3c"

    shared = await store.get_promoted()
    assert len(shared) == 1
    assert shared[0].validation_run_ids == ["run-eval-1", "run-eval-2", "run-eval-3"]


@pytest.mark.asyncio
async def test_promote_learning_refuses_non_active_and_out_of_scope_rows(
    store: SqliteLearningStore,
) -> None:
    active_id = await store.store(make_learning())
    other_org_id = await store.store(make_learning(org_id="org-b"))
    # Distinct trigger keys per row: `store` deduplicates same-scope rows whose
    # trigger keys overlap >= 50% into the *active* row (`_bump_dedup_hit`),
    # so same-key rows would collapse into the active id and the refusal
    # checks below would probe the wrong row.
    promoted_id = await store.store(make_learning(trigger_keys=["migrate"], status="promoted"))
    rejected_id = await store.store(make_learning(trigger_keys=["rollback"], status="rejected"))

    assert await store.promote_learning(other_org_id, org_id="org-a") is None
    assert await store.promote_learning(promoted_id, org_id="") is None
    assert await store.promote_learning(rejected_id, org_id="") is None
    assert await store.promote_learning(9999, org_id="") is None

    # The rejected row — the anti-learning and its evidence — is untouched.
    rows = {row.id: row for row in await store.list_all()}
    rejected = rows[rejected_id]
    assert rejected.status == "rejected"
    assert rejected.validated_by == ""

    ok = await store.promote_learning(active_id, org_id="")
    assert ok is not None
    assert ok.status == "promoted"


@pytest.mark.asyncio
async def test_store_persists_validation_provenance_on_insert(
    store: SqliteLearningStore,
) -> None:
    await store.store(
        make_learning(
            status="promoted",
            validated_by="independent-trials",
            validated_evaluator_version="2.0.0",
            validated_at=datetime(2026, 2, 1, 9, 30, 0, tzinfo=UTC),
            validation_run_ids=["run-x"],
            validation_content_hash="abc",
        )
    )

    row = (await store.list_all())[0]
    assert row.validated_by == "independent-trials"
    assert row.validated_evaluator_version == "2.0.0"
    assert row.validated_at == datetime(2026, 2, 1, 9, 30, 0, tzinfo=UTC)
    assert row.validation_run_ids == ["run-x"]
    assert row.validation_content_hash == "abc"


@pytest.mark.asyncio
async def test_pre_gauntlet_database_upgrades_and_rows_read_as_never_validated(
    tmp_path: object,
) -> None:
    """A file created before the Gauntlet upgrades in place.

    Old rows must come back as the never-validated learnings they are —
    with the honest defaults, not fabricated provenance — and promote
    normally afterwards.
    """
    import pathlib

    db_path = pathlib.Path(str(tmp_path)) / "learnings-pre-gauntlet.db"
    conn = await aiosqlite.connect(db_path)
    await conn.execute(
        """
        CREATE TABLE learnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL DEFAULT 'general',
            trigger_keys TEXT NOT NULL DEFAULT '[]',
            learning TEXT NOT NULL DEFAULT '',
            tool_name TEXT NOT NULL DEFAULT '',
            source_query TEXT NOT NULL DEFAULT '',
            agent_id TEXT NOT NULL DEFAULT '',
            user_id TEXT,
            org_id TEXT NOT NULL DEFAULT '',
            team_id TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT 'agent',
            hit_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            rca_category TEXT,
            rca_prevention TEXT NOT NULL DEFAULT '',
            success_after_use INTEGER NOT NULL DEFAULT 0,
            failure_after_use INTEGER NOT NULL DEFAULT 0,
            run_id TEXT,
            node_run_id TEXT,
            attempt_id TEXT
        )
        """
    )
    await conn.execute(
        """INSERT INTO learnings
           (category, trigger_keys, learning, tool_name, org_id, hit_count, status, run_id)
           VALUES ('tooling', '["deploy"]', 'old row', 'bash', '', 10, 'active', 'run-old')"""
    )
    await conn.commit()
    await conn.close()

    conn = await aiosqlite.connect(db_path)
    store = SqliteLearningStore(conn, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
    await store.ensure_schema()

    row = (await store.list_all())[0]
    assert row.learning == "old row"
    assert row.validated_by == ""
    assert row.validated_evaluator_version == ""
    assert row.validated_at is None
    assert row.validation_run_ids == []
    assert row.validation_content_hash == ""

    # And the upgraded store promotes normally, writing real provenance.
    promoted = await store.promote_learning(
        row.id or 0,
        validated_by="independent-trials",
        evaluator_version="1.0.0",
        validated_at=datetime(2026, 3, 1, 8, 0, 0, tzinfo=UTC),
        validation_run_ids=("run-eval-9",),
        validation_content_hash="cafe",
    )
    assert promoted is not None
    assert promoted.validation_run_ids == ["run-eval-9"]
    await conn.close()


class _LosingSelectRowsConn:
    """Answers writes through a real connection; SELECTs lose their row.

    `promote_learning` re-reads the row it just promoted with a second
    statement. On a shared database another writer can delete that row in
    between; the store must answer None rather than crash or fabricate a
    learning. The vanishing act cannot happen on a private in-memory
    database, so the read half is intercepted to reach the defensive branch.
    """

    def __init__(self, real: aiosqlite.Connection) -> None:
        self._real = real

    async def execute(self, sql: str, parameters: object = ()) -> object:
        cursor = await self._real.execute(sql, parameters)  # type: ignore[arg-type]
        if sql.lstrip().upper().startswith("SELECT"):
            return _VanishingCursor(cursor)
        return cursor

    async def commit(self) -> None:
        await self._real.commit()


class _VanishingCursor:
    """The shape the store reads: real `description`, nothing to fetch."""

    def __init__(self, cursor: aiosqlite.Cursor) -> None:
        self.description = cursor.description
        self.rowcount = cursor.rowcount

    async def fetchone(self) -> None:
        return None


@pytest.mark.asyncio
async def test_promote_learning_returns_none_when_the_row_vanishes_before_the_read() -> None:
    """A row deleted between the UPDATE and the re-read is a None, not a crash."""
    conn = await aiosqlite.connect(":memory:")
    base = SqliteLearningStore(conn, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
    await base.ensure_schema()
    lid = await base.store(make_learning())

    vanishing = SqliteLearningStore(
        _LosingSelectRowsConn(conn),  # type: ignore[arg-type]
        exposure_mode=MemoryExposureMode.AGENT_MANAGED,
    )
    try:
        assert await vanishing.promote_learning(lid, org_id="") is None
        # The UPDATE itself did land: the row was genuinely promoted before it
        # vanished, so the None means "gone", not "no-op".
        rows = await base.list_all()
        assert [row.status for row in rows] == ["promoted"]
    finally:
        await conn.close()
