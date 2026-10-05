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
