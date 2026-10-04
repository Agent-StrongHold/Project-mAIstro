"""Durable lifecycle state on the SQLite learning twin (M4-B / ADR-100126-9a4b).

The in-memory store loses its rows at process end, so "a restart must not
demote a validated learning back to a local belief" is only provable against a
store that survives one. These tests round-trip the lifecycle fields through a
real SQLite file and through the pre-M4B upgrade path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest

from maistro.persistence.sqlite_learnings import SqliteLearningStore
from maistro.types.memory import EpistemicType, Learning, LearningStage

_VALIDATED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_CONFIRMED_AT = datetime(2026, 1, 2, 8, 30, 0, tzinfo=UTC)


def _validated_learning() -> Learning:
    return Learning(
        trigger_keys=["deploy", "prod"],
        learning="snapshot before deploying",
        run_id="run-77",
        stage=LearningStage.VALIDATED,
        epistemic_type=EpistemicType.ANTI_PATTERN,
        confidence=0.8,
        applicability={"task_types": ["deploy"], "tools": ["bash"]},
        reinforcement_count=6,
        contradiction_count=1,
        created_at=_VALIDATED_AT,
        last_confirmed_at=_CONFIRMED_AT,
        validated_by="outcome-evidence",
        validated_at=_VALIDATED_AT,
        supersedes=3,
        superseded_by=None,
    )


@pytest.mark.asyncio
async def test_lifecycle_state_survives_a_round_trip(tmp_path: Path) -> None:
    # A file, not ":memory:", so the second store is a genuine cold read: the
    # claim under test is persistence, not object identity.
    db = tmp_path / "learnings.db"
    async with aiosqlite.connect(db) as conn:
        store = SqliteLearningStore(conn)
        await store.ensure_schema()
        await store.store(_validated_learning())

    async with aiosqlite.connect(db) as conn:
        rows = await SqliteLearningStore(conn).produced_by("run-77")

    assert len(rows) == 1
    revived = rows[0]
    assert revived.stage is LearningStage.VALIDATED
    assert revived.epistemic_type is EpistemicType.ANTI_PATTERN
    assert revived.confidence == 0.8
    assert revived.applicability == {"task_types": ["deploy"], "tools": ["bash"]}
    assert revived.reinforcement_count == 6
    assert revived.contradiction_count == 1
    assert revived.last_confirmed_at == _CONFIRMED_AT
    assert revived.validated_by == "outcome-evidence"
    assert revived.validated_at == _VALIDATED_AT
    assert revived.supersedes == 3
    assert revived.superseded_by is None
    assert revived.run_id == "run-77"


@pytest.mark.asyncio
async def test_pre_m4b_rows_upgrade_to_the_defaults_they_always_meant(
    tmp_path: Path,
) -> None:
    """A database created before M4-B upgrades in place, rows keep their meaning.

    The legacy schema is the pre-lifecycle `learnings` table. After
    `ensure_schema`, old rows read back as local empirical learnings at the
    default confidence -- the state they implicitly had -- never as validated
    or repertoire knowledge the system never claimed.
    """
    db = tmp_path / "legacy.db"
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            """
            CREATE TABLE learnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL DEFAULT 'general',
                trigger_keys TEXT NOT NULL DEFAULT '[]',
                learning TEXT NOT NULL DEFAULT '',
                tool_name TEXT NOT NULL DEFAULT '',
                agent_id TEXT NOT NULL DEFAULT '',
                user_id TEXT,
                org_id TEXT NOT NULL DEFAULT '',
                scope TEXT NOT NULL DEFAULT 'agent',
                hit_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                rca_category TEXT,
                rca_prevention TEXT NOT NULL DEFAULT '',
                success_after_use INTEGER NOT NULL DEFAULT 0,
                failure_after_use INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await conn.execute(
            "INSERT INTO learnings (trigger_keys, learning, org_id) VALUES (?, ?, ?)",
            ('["deploy"]', "an old belief", "org-1"),
        )
        await conn.commit()

        store = SqliteLearningStore(conn)
        await store.ensure_schema()
        rows = await store.list_all(org_id="org-1")

    assert len(rows) == 1
    old = rows[0]
    assert old.learning == "an old belief"
    assert old.stage is LearningStage.LEARNING
    assert old.epistemic_type is EpistemicType.EMPIRICAL
    assert old.confidence == 0.5
    assert old.applicability == {}
    assert old.reinforcement_count == 0
    assert old.contradiction_count == 0
    assert old.last_confirmed_at is None
    assert old.validated_by == ""
    assert old.validated_at is None
    assert old.supersedes is None
    assert old.superseded_by is None
    # The upgrade must not have invented Gauntlet provenance.
    assert old.stage is not LearningStage.VALIDATED
