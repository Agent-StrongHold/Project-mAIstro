"""Durable lifecycle state on the SQLite learning twin (M4-B / ADR-100126-8c2d).

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

from maistro.memory.exposure import MemoryExposureMode
from maistro.memory.learnings.promoter import LearningPromoter
from maistro.persistence.sqlite_learnings import SqliteLearningStore
from maistro.protocols.memory import IneffectiveLearningSource
from maistro.types.memory import EpistemicType, Learning, LearningStage

pytestmark = [pytest.mark.contract("behavioral")]

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
        store = SqliteLearningStore(conn, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        await store.ensure_schema()
        await store.store(_validated_learning())

    async with aiosqlite.connect(db) as conn:
        rows = await SqliteLearningStore(
            conn, exposure_mode=MemoryExposureMode.AGENT_MANAGED
        ).produced_by("run-77")

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
async def test_repeated_failures_are_captured_as_anti_patterns_on_the_durable_twin(
    tmp_path: Path,
) -> None:
    """#121 reaches production through the durable store, not only in memory.

    The in-memory store is the dev/test default; the capture sweep runs in
    production against the SQL twins, whose reads return detached copies.
    This pins the full durable path: the twin answers the
    ``IneffectiveLearningSource`` read with the same predicate the in-memory
    store applies, the promoter's reclassification is written back through
    ``mark_anti_pattern``, and a cold read sees the anti-pattern -- not the
    empirical learning that was first stored.
    """
    db = tmp_path / "learnings.db"

    async with aiosqlite.connect(db) as conn:
        store = SqliteLearningStore(conn, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        await store.ensure_schema()
        chronic = Learning(
            trigger_keys=["force-push"],
            learning="force-pushing over the protected branch",
            run_id="run-1",
            org_id="org-1",
            success_after_use=1,
            failure_after_use=4,
        )
        healthy = Learning(
            trigger_keys=["snapshot"],
            learning="snapshot before deploying",
            run_id="run-2",
            org_id="org-1",
            success_after_use=4,
            failure_after_use=1,
        )
        chronic_id = await store.store(chronic)
        healthy_id = await store.store(healthy)
        assert isinstance(store, IneffectiveLearningSource)

        ineffective = await store.list_ineffective(min_uses=3)
        assert [lr.id for lr in ineffective] == [chronic_id]

        # The org boundary binds the write too: a row from another scope is
        # not reclassified by a guessed id under a blank org.
        assert await store.mark_anti_pattern(healthy_id, 0.6, org_id="") is False

        captured = await LearningPromoter(store).capture_anti_patterns("org-1", min_uses=3)
        assert [lr.id for lr in captured] == [chronic_id]
        assert captured[0].epistemic_type is EpistemicType.ANTI_PATTERN
        assert captured[0].confidence >= 0.6

    # The reclassification is durable: a cold read sees the anti-pattern,
    # not the empirical learning that was first stored.
    async with aiosqlite.connect(db) as conn:
        revived = await SqliteLearningStore(
            conn, exposure_mode=MemoryExposureMode.AGENT_MANAGED
        ).produced_by("run-1", org_id="org-1")
    assert len(revived) == 1
    assert revived[0].id == chronic_id
    assert revived[0].epistemic_type is EpistemicType.ANTI_PATTERN
    assert revived[0].confidence >= 0.6
    assert revived[0].failure_after_use == 4


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

        store = SqliteLearningStore(conn, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        await store.ensure_schema()
        rows = await store.list_all(org_id="org-1")

    assert len(rows) == 1
    old = rows[0]
    assert old.learning == "an old belief"
    # ADR-103: a pre-ladder row lands on the bottom rung with no actors --
    # nothing validated or promoted it, and fabricating one would lie.
    assert old.stage is LearningStage.MEMORY
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


@pytest.mark.asyncio
async def test_a_malformed_instant_column_costs_that_instant_nothing_more(
    tmp_path: Path,
) -> None:
    """A row whose instant text cannot parse reads back as the default, not as
    a crash of every read that touches it -- the same tolerance the JSON
    columns get. One bad row must not turn the capture sweep (which reads the
    whole twin) into an outage of the whole store."""
    db = tmp_path / "learnings.db"
    async with aiosqlite.connect(db) as conn:
        store = SqliteLearningStore(conn, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        await store.ensure_schema()
        await conn.execute(
            """INSERT INTO learnings (learning, run_id, org_id, created_at,
                                      last_confirmed_at, validated_at)
               VALUES ('unparseable instants', 'run-bad', 'org-1',
                       'not-a-timestamp', 'also-not', 'still-not')"""
        )
        await conn.commit()

    async with aiosqlite.connect(db) as conn:
        [revived] = await SqliteLearningStore(
            conn, exposure_mode=MemoryExposureMode.AGENT_MANAGED
        ).produced_by("run-bad", org_id="org-1")

    assert revived.validated_at is None
    assert revived.last_confirmed_at is None
    # created_at falls back to read time rather than inventing an instant.
    assert (datetime.now(UTC) - revived.created_at).total_seconds() < 60


def test_the_instant_and_applicability_decoders_tolerate_every_shape_a_row_holds() -> None:
    """Mirrors the pg twins' decoder contracts (#121 touched both).

    `applicability` is NOT NULL today, but `_row_to_learning` also builds rows
    from dictionaries that may lack the key -- a row written before migration
    052 read through the upgrade path -- so `None` decodes to no applicability
    rather than raising. `_utc_text` accepts naive datetimes because the
    aiosqlite default adapter era wrote some; they name UTC, the same instant
    an aware writer would have stored.
    """
    from maistro.persistence.sqlite_learnings import (
        _load_applicability,
        _load_moment,
        _utc_text,
    )

    assert _load_applicability(None) == {}
    assert _load_applicability({"task_types": ["deploy"]}) == {"task_types": ["deploy"]}
    assert _load_applicability('{"task_types": ["deploy"]}') == {"task_types": ["deploy"]}
    assert _load_applicability("not json at all") == {}
    assert _load_applicability('["not", "a", "dict"]') == {}
    assert _load_applicability(42) == {}

    assert _load_moment(None) is None
    assert _load_moment(42) is None
    assert _load_moment("2026-01-01T12:00:00+00:00") == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    naive = datetime(2026, 1, 1, 12, 0, 0)
    assert _utc_text(naive) == "2026-01-01T12:00:00+00:00"
    assert _utc_text(naive.replace(tzinfo=UTC)) == "2026-01-01T12:00:00+00:00"
